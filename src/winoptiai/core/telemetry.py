"""Real-time CPU frequency, Turbo ratio, per-core load, and thermal sensor telemetry."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import json
import subprocess
import threading

import psutil

from .win32_bridge import IS_WINDOWS


PDH_FMT_DOUBLE = 0x00000200


class _PDH_FMT_COUNTERVALUE(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [
            ("longValue", ctypes.c_long),
            ("doubleValue", ctypes.c_double),
            ("largeValue", ctypes.c_longlong),
        ]

    _fields_ = [("CStatus", wintypes.DWORD), ("u", _U)]


@dataclass(slots=True)
class LiveSystemTelemetry:
    """Real-time CPU, frequency, Turbo, and thermal readings."""

    cpu_utility_pct: float
    cpu_freq_mhz: float
    cpu_turbo_pct: float
    per_core_pct: list[float]
    cpu_temp_c: float | None
    nvme_temp_c: float | None
    temp_status: str  # "OK" | "UAC_REQUIRED" | "UNAVAILABLE"


class PdhTelemetryReader:
    """Zero-overhead Windows PDH English-counter reader (language-independent)."""

    def __init__(self, lazy_init: bool = False) -> None:
        self._lock = threading.Lock()
        self._initialized = False
        self._pdh = None
        self._query = wintypes.HANDLE()
        self._handles: dict[str, wintypes.HANDLE] = {}
        self._last_elevated_cpu_temp: float | None = None
        self._last_elevated_nvme_temp: float | None = None

        if not lazy_init:
            self.ensure_initialized()

    def ensure_initialized(self) -> None:
        """Initialize Windows PDH counters once (safe to call from a background thread)."""
        if self._initialized or not IS_WINDOWS:
            return
        with self._lock:
            if self._initialized:
                return
            try:
                pdh = ctypes.WinDLL("pdh.dll")
                query = wintypes.HANDLE()
                rc = pdh.PdhOpenQueryW(None, 0, ctypes.byref(query))
                if rc == 0:
                    handles: dict[str, wintypes.HANDLE] = {}
                    counters = {
                        "utility": r"\Processor Information(_Total)\% Processor Utility",
                        "freq": r"\Processor Information(_Total)\Processor Frequency",
                        "perf": r"\Processor Information(_Total)\% Processor Performance",
                    }
                    for key, path in counters.items():
                        ch = wintypes.HANDLE()
                        if pdh.PdhAddEnglishCounterW(query, path, 0, ctypes.byref(ch)) == 0:
                            handles[key] = ch
                    pdh.PdhCollectQueryData(query)
                    self._pdh = pdh
                    self._query = query
                    self._handles = handles
            except OSError:
                self._pdh = None
            finally:
                self._initialized = True

    def _read_double(self, key: str) -> float | None:
        if not self._pdh or key not in self._handles:
            return None
        val = _PDH_FMT_COUNTERVALUE()
        rc = self._pdh.PdhGetFormattedCounterValue(
            self._handles[key], PDH_FMT_DOUBLE, None, ctypes.byref(val)
        )
        if rc != 0:
            return None
        return float(val.u.doubleValue)

    def _try_non_elevated_thermal_c(self) -> float | None:
        if not IS_WINDOWS:
            return None
        # Check psutil sensors if supported on host, else return cached elevated probe
        if hasattr(psutil, "sensors_temperatures"):
            try:
                temps = psutil.sensors_temperatures()  # type: ignore[attr-defined]
                for entries in temps.values():
                    for entry in entries:
                        if entry.current and 15.0 < entry.current < 115.0:
                            return round(float(entry.current), 1)
            except Exception:  # noqa: BLE001
                pass
        return self._last_elevated_cpu_temp

    def set_elevated_temps(self, cpu_c: float | None, nvme_c: float | None) -> None:
        self._last_elevated_cpu_temp = cpu_c
        self._last_elevated_nvme_temp = nvme_c

    def sample(self) -> LiveSystemTelemetry:
        per_core = [round(float(x), 1) for x in psutil.cpu_percent(interval=None, percpu=True)]
        fallback_cpu = round(sum(per_core) / len(per_core), 1) if per_core else 0.0

        utility = fallback_cpu
        freq_mhz = 0.0
        turbo_pct = 100.0

        if self._initialized and self._pdh and self._query and self._lock.acquire(blocking=False):
            try:
                self._pdh.PdhCollectQueryData(self._query)
                u = self._read_double("utility")
                f = self._read_double("freq")
                p = self._read_double("perf")
                if u is not None and u >= 0.0:
                    utility = min(100.0, round(u, 1))
                if f is not None and f > 0.0:
                    freq_mhz = round(f, 0)
                if p is not None and p > 0.0:
                    turbo_pct = round(p, 0)
            finally:
                self._lock.release()

        if freq_mhz <= 0.0:
            cf = psutil.cpu_freq()
            if cf and cf.current:
                freq_mhz = round(float(cf.current), 0)

        cpu_temp = self._try_non_elevated_thermal_c()
        nvme_temp = self._last_elevated_nvme_temp
        status = "OK" if (cpu_temp is not None or nvme_temp is not None) else "UAC_REQUIRED"

        return LiveSystemTelemetry(
            cpu_utility_pct=utility,
            cpu_freq_mhz=freq_mhz,
            cpu_turbo_pct=turbo_pct,
            per_core_pct=per_core,
            cpu_temp_c=cpu_temp,
            nvme_temp_c=nvme_temp,
            temp_status=status,
        )


TEMP_PROBE_UAC_WAIT_S = 120  # tiempo para aceptar el aviso de UAC


def build_temperature_probe_script(out_file: str) -> str:
    """Script PowerShell que escribe {cpu, nvme, error} en ``out_file`` (siempre lo escribe)."""
    safe = out_file.replace("'", "''")
    return (
        "$ErrorActionPreference='SilentlyContinue'; $ProgressPreference='SilentlyContinue'; $cpu=$null; $nvme=$null; $err=''; "
        "try { $tz=Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop | "
        "Select-Object -First 1; if($tz){ $cpu=[math]::Round(($tz.CurrentTemperature/10.0)-273.15,1) } } "
        "catch { $err=$_.Exception.Message }; "
        "try { $d=Get-PhysicalDisk | Where-Object { $_.MediaType -eq 'SSD' -or $_.BusType -eq 'NVMe' } | "
        "Select-Object -First 1 | Get-StorageReliabilityCounter -ErrorAction Stop; "
        "if($d -and $d.Temperature){ $nvme=[double]$d.Temperature } } catch { if(-not $err){ $err=$_.Exception.Message } }; "
        f"[PSCustomObject]@{{cpu=$cpu;nvme=$nvme;error=$err}} | ConvertTo-Json -Compress | "
        f"Set-Content -LiteralPath '{safe}' -Encoding UTF8"
    )


def _encode_ps(script: str) -> str:
    import base64

    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def clean_ps_stderr(text: str) -> str:
    """Quitar el ruido CLIXML de progreso de PowerShell; conservar solo mensajes de error reales."""
    import re

    raw = (text or "").strip()
    if not raw.startswith("#< CLIXML"):
        return raw
    errs = re.findall(r'<S S="Error">(.*?)</S>', raw, flags=re.S)
    msg = " ".join(e.replace("_x000D__x000A_", " ").strip() for e in errs)
    return re.sub(r"\s+", " ", msg).strip()


def interpret_temperature_probe(data: dict | None, launcher_stderr: str = "") -> tuple[float | None, float | None, str]:
    """Mensaje honesto segun lo que paso (sin confundir un fallo con 'UAC cancelada')."""
    launcher_stderr = clean_ps_stderr(launcher_stderr)
    low = launcher_stderr.lower()
    if data is None:
        if "cancel" in low or "1223" in low:
            return None, None, "Lectura de sensores cancelada: no se acepto el aviso de UAC."
        if launcher_stderr.strip():
            return None, None, f"No se pudo iniciar la lectura elevada: {launcher_stderr.strip()[:140]}"
        return None, None, "La lectura de sensores no devolvio resultado (tiempo agotado o bloqueada)."
    cpu_t = data.get("cpu")
    nvme_t = data.get("nvme")
    # Algunas placas devuelven un valor fijo sin sentido (p. ej. -273 o >120 C): se descarta.
    if isinstance(cpu_t, (int, float)) and not (5.0 <= float(cpu_t) <= 115.0):
        cpu_t = None
    if isinstance(nvme_t, (int, float)) and not (5.0 <= float(nvme_t) <= 100.0):
        nvme_t = None
    if cpu_t is None and nvme_t is None:
        return None, None, "Esta placa no expone sensores de temperatura a Windows; se sigue monitoreando por MHz/Turbo."
    parts = []
    if cpu_t is not None:
        parts.append(f"CPU {cpu_t:.0f} C")
    if nvme_t is not None:
        parts.append(f"SSD {nvme_t:.0f} C")
    return cpu_t, nvme_t, "Lectura termica completada: " + ", ".join(parts)


def probe_elevated_temperatures() -> tuple[float | None, float | None, str]:
    """Lectura puntual de temperatura ACPI (CPU) y S.M.A.R.T. (NVMe/SSD) con permisos de administrador.

    v0.6.5: antes el script iba entre comillas dobles y la PowerShell externa reemplazaba $cpu, $tz,
    $d... por vacio: la ventana elevada recibia un script roto y la app decia 'UAC cancelada' aunque
    se aceptara. Ahora va codificado (-EncodedCommand) y, si la app ya es administradora, sin UAC.
    """
    if not IS_WINDOWS:
        return None, None, "Solo Windows"
    import os
    import tempfile
    import time
    from pathlib import Path

    from .win32_bridge import is_user_admin

    out_file = Path(tempfile.gettempdir()) / f"winoptiai_temps_{os.getpid()}_{int(time.time())}.json"
    out_file.unlink(missing_ok=True)
    encoded = _encode_ps(build_temperature_probe_script(str(out_file)))
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    stderr_txt = ""
    try:
        if is_user_admin():
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60, creationflags=no_window)
        else:
            launcher = (
                "$ProgressPreference='SilentlyContinue'; Start-Process -FilePath powershell -Verb RunAs -WindowStyle Hidden -Wait "
                f"-ArgumentList '-NoProfile','-NonInteractive','-EncodedCommand','{encoded}'"
            )
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", launcher]
            res = subprocess.run(
                cmd, capture_output=True, text=True, timeout=TEMP_PROBE_UAC_WAIT_S, creationflags=no_window
            )
        stderr_txt = (res.stderr or "").strip()
    except subprocess.TimeoutExpired:
        stderr_txt = ""
    except OSError as exc:
        return None, None, f"Error leyendo sensores: {exc}"
    data = None
    try:
        if out_file.exists():
            data = json.loads(out_file.read_text(encoding="utf-8-sig") or "null")
    except (OSError, json.JSONDecodeError):
        data = None
    finally:
        out_file.unlink(missing_ok=True)
    return interpret_temperature_probe(data if isinstance(data, dict) else None, stderr_txt)
