"""Real-time CPU frequency, Turbo ratio, per-core load, and thermal sensor telemetry."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import json
import subprocess
import threading
import time

import psutil

from .win32_bridge import IS_WINDOWS


PDH_FMT_DOUBLE = 0x00000200
PDH_FMT_NOCAP100 = 0x00008000
PDH_MORE_DATA = 0x800007D2


class _PDH_FMT_COUNTERVALUE(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [
            ("longValue", ctypes.c_long),
            ("doubleValue", ctypes.c_double),
            ("largeValue", ctypes.c_longlong),
        ]

    _fields_ = [("CStatus", wintypes.DWORD), ("u", _U)]


class _PDH_FMT_COUNTERVALUE_ITEM_W(ctypes.Structure):
    _fields_ = [
        ("szName", wintypes.LPCWSTR),
        ("FmtValue", _PDH_FMT_COUNTERVALUE),
    ]


class _PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("CommitTotal", ctypes.c_size_t),
        ("CommitLimit", ctypes.c_size_t),
        ("CommitPeak", ctypes.c_size_t),
        ("PhysicalTotal", ctypes.c_size_t),
        ("PhysicalAvailable", ctypes.c_size_t),
        ("SystemCache", ctypes.c_size_t),
        ("KernelTotal", ctypes.c_size_t),
        ("KernelPaged", ctypes.c_size_t),
        ("KernelNonpaged", ctypes.c_size_t),
        ("PageSize", ctypes.c_size_t),
        ("HandleCount", wintypes.DWORD),
        ("ProcessCount", wintypes.DWORD),
        ("ThreadCount", wintypes.DWORD),
    ]


def read_performance_info() -> dict[str, float | int]:
    """Read kernel Commit charge, handle count, and thread count via psapi.GetPerformanceInfo (zero UAC)."""
    if not IS_WINDOWS:
        return {}
    try:
        info = _PERFORMANCE_INFORMATION()
        info.cb = ctypes.sizeof(_PERFORMANCE_INFORMATION)
        psapi = ctypes.WinDLL("psapi.dll")
        psapi.GetPerformanceInfo.argtypes = [ctypes.POINTER(_PERFORMANCE_INFORMATION), wintypes.DWORD]
        psapi.GetPerformanceInfo.restype = wintypes.BOOL
        if not psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
            return {}
        page = max(4096, int(info.PageSize))
        gb = float(1024**3)
        used_gb = (int(info.CommitTotal) * page) / gb
        limit_gb = (int(info.CommitLimit) * page) / gb
        pct = (used_gb * 100.0 / limit_gb) if limit_gb > 0 else 0.0
        return {
            "commit_used_gb": round(used_gb, 2),
            "commit_limit_gb": round(limit_gb, 2),
            "commit_pct": round(min(100.0, max(0.0, pct)), 1),
            "handles": int(info.HandleCount),
            "threads": int(info.ThreadCount),
        }
    except OSError:
        return {}


@dataclass(slots=True)
class LiveSystemTelemetry:
    """Real-time CPU, frequency, Turbo, Disk I/O, Commit, GPU, Network, and thermal readings."""

    cpu_utility_pct: float
    cpu_freq_mhz: float
    cpu_turbo_pct: float
    per_core_pct: list[float]
    cpu_temp_c: float | None
    nvme_temp_c: float | None
    temp_status: str  # "OK" | "UAC_REQUIRED" | "UNAVAILABLE"
    disk_active_pct: float = 0.0
    disk_queue_len: float = 0.0
    disk_read_mb_s: float = 0.0
    disk_write_mb_s: float = 0.0
    commit_pct: float = 0.0
    commit_used_gb: float = 0.0
    commit_limit_gb: float = 0.0
    page_reads_per_sec: float = 0.0
    handles_count: int = 0
    threads_count: int = 0
    gpu_vram_shared_mb: float = 0.0
    gpu_util_pct: float = 0.0
    net_rx_mb_s: float = 0.0
    net_tx_mb_s: float = 0.0


@dataclass(slots=True)
class BottleneckDiagnosis:
    """Actionable automatic diagnosis derived from live system telemetry."""

    code: str  # "balanced" | "elevated" | "disk_io" | "memory_commit" | "thermal" | "compute"
    tone: str  # "ok" | "warn" | "risk"
    label: str
    detail: str
    action_tab: int = 0


def diagnose_bottleneck(
    live: LiveSystemTelemetry,
    ram_used_pct: float,
    free_ram_gb: float,
    ram_threshold_gb: float,
) -> BottleneckDiagnosis:
    """Identify the dominant resource bottleneck honestly without false alarms."""
    if live.cpu_temp_c is not None and live.cpu_temp_c >= 88.0:
        return BottleneckDiagnosis(
            code="thermal",
            tone="risk",
            label="Termica Critica",
            detail=f"CPU a {live.cpu_temp_c:.0f} C (riesgo de estrangulamiento). Activa perfil Frio en Termica.",
            action_tab=3,
        )
    if live.disk_active_pct >= 90.0 or live.disk_queue_len >= 4.0:
        return BottleneckDiagnosis(
            code="disk_io",
            tone="risk",
            label="Disco Saturado",
            detail=f"Disco al {live.disk_active_pct:.0f}% (cola {live.disk_queue_len:.1f}). Revisa procesos en E/S.",
            action_tab=2,
        )
    if free_ram_gb < ram_threshold_gb or live.commit_pct >= 88.0 or live.page_reads_per_sec >= 250.0:
        sev = "risk" if (free_ram_gb < ram_threshold_gb or live.commit_pct >= 92.0) else "warn"
        return BottleneckDiagnosis(
            code="memory_commit",
            tone=sev,
            label="Presion Memoria",
            detail=(
                f"RAM libre {free_ram_gb:.2f} GB | Commit {live.commit_pct:.0f}% "
                f"| Pag. disco {live.page_reads_per_sec:.0f}/s. Sugerencia: AI Boost."
            ),
            action_tab=2,
        )
    if live.cpu_utility_pct >= 90.0 or live.gpu_util_pct >= 90.0:
        return BottleneckDiagnosis(
            code="compute",
            tone="warn",
            label="CPU/GPU Alta",
            detail=f"CPU {live.cpu_utility_pct:.0f}% | GPU {live.gpu_util_pct:.0f}%. Carga de computo sostenida.",
            action_tab=2,
        )
    if (
        (live.cpu_temp_c is not None and live.cpu_temp_c >= 75.0)
        or ram_used_pct >= 82.0
        or live.disk_active_pct >= 65.0
    ):
        return BottleneckDiagnosis(
            code="elevated",
            tone="warn",
            label="Carga Media",
            detail=f"RAM {ram_used_pct:.0f}% | Disco {live.disk_active_pct:.0f}% | GPU {live.gpu_util_pct:.0f}%.",
            action_tab=0,
        )
    return BottleneckDiagnosis(
        code="balanced",
        tone="ok",
        label="Fluido",
        detail=f"Commit {live.commit_pct:.0f}% | Disco {live.disk_active_pct:.0f}% | GPU {live.gpu_util_pct:.0f}%.",
        action_tab=0,
    )


class SustainedBottleneckMonitor:
    """Emit at most one alert after a severe bottleneck holds continuously for ``sustain_seconds``."""

    ALERT_CODES = frozenset({"thermal", "disk_io", "memory_commit"})

    def __init__(self, sustain_seconds: float = 30.0, cooldown_seconds: float = 600.0) -> None:
        self.sustain_seconds = float(sustain_seconds)
        self.cooldown_seconds = float(cooldown_seconds)
        self._active_code: str | None = None
        self._started_ts: float = 0.0
        self._last_alert_ts: dict[str, float] = {}

    def feed(self, diag: BottleneckDiagnosis, now: float | None = None) -> BottleneckDiagnosis | None:
        ts = time.monotonic() if now is None else float(now)
        if diag.code not in self.ALERT_CODES or diag.tone != "risk":
            self._active_code = None
            self._started_ts = 0.0
            return None
        if self._active_code != diag.code:
            self._active_code = diag.code
            self._started_ts = ts
            return None
        if (ts - self._started_ts) < self.sustain_seconds:
            return None
        last = self._last_alert_ts.get(diag.code, -1e9)
        if (ts - last) < self.cooldown_seconds:
            return None
        self._last_alert_ts[diag.code] = ts
        return diag


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
        self._prev_io_ts: float = 0.0
        self._prev_disk_bytes: tuple[int, int] | None = None
        self._prev_net_bytes: tuple[int, int] | None = None

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
                pdh.PdhGetFormattedCounterValue.argtypes = [
                    wintypes.HANDLE,
                    wintypes.DWORD,
                    ctypes.POINTER(wintypes.DWORD),
                    ctypes.POINTER(_PDH_FMT_COUNTERVALUE),
                ]
                pdh.PdhGetFormattedCounterValue.restype = ctypes.c_ulong
                pdh.PdhGetFormattedCounterArrayW.argtypes = [
                    wintypes.HANDLE,
                    wintypes.DWORD,
                    ctypes.POINTER(wintypes.DWORD),
                    ctypes.POINTER(wintypes.DWORD),
                    ctypes.c_void_p,
                ]
                pdh.PdhGetFormattedCounterArrayW.restype = ctypes.c_ulong
                query = wintypes.HANDLE()
                rc = pdh.PdhOpenQueryW(None, 0, ctypes.byref(query))
                if rc == 0:
                    handles: dict[str, wintypes.HANDLE] = {}
                    counters = {
                        "utility": r"\Processor Information(_Total)\% Processor Utility",
                        "freq": r"\Processor Information(_Total)\Processor Frequency",
                        "perf": r"\Processor Information(_Total)\% Processor Performance",
                        "disk_active": r"\PhysicalDisk(_Total)\% Disk Time",
                        "disk_queue": r"\PhysicalDisk(_Total)\Current Disk Queue Length",
                        "disk_read": r"\PhysicalDisk(_Total)\Disk Read Bytes/sec",
                        "disk_write": r"\PhysicalDisk(_Total)\Disk Write Bytes/sec",
                        "commit_pct": r"\Memory\% Committed Bytes In Use",
                        "page_reads": r"\Memory\Page Reads/sec",
                        "gpu_vram": r"\GPU Adapter Memory(*)\Shared Usage",
                        "gpu_util": r"\GPU Engine(*)\Utilization Percentage",
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

    def _read_array_sum(self, key: str) -> float | None:
        if not self._pdh or key not in self._handles:
            return None
        buf_size = wintypes.DWORD(0)
        item_count = wintypes.DWORD(0)
        rc = self._pdh.PdhGetFormattedCounterArrayW(
            self._handles[key],
            PDH_FMT_DOUBLE | PDH_FMT_NOCAP100,
            ctypes.byref(buf_size),
            ctypes.byref(item_count),
            None,
        )
        if rc != PDH_MORE_DATA or buf_size.value <= 0:
            return 0.0 if rc == 0 else None
        buf = (ctypes.c_byte * int(buf_size.value))()
        rc = self._pdh.PdhGetFormattedCounterArrayW(
            self._handles[key],
            PDH_FMT_DOUBLE | PDH_FMT_NOCAP100,
            ctypes.byref(buf_size),
            ctypes.byref(item_count),
            ctypes.byref(buf),
        )
        if rc != 0:
            return None
        items = ctypes.cast(buf, ctypes.POINTER(_PDH_FMT_COUNTERVALUE_ITEM_W))
        total = 0.0
        for idx in range(int(item_count.value)):
            fv = items[idx].FmtValue
            if fv.CStatus in (0, 1):
                total += max(0.0, float(fv.u.doubleValue))
        return total

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
        disk_active = 0.0
        disk_queue = 0.0
        disk_read_mb = 0.0
        disk_write_mb = 0.0
        commit_pct = 0.0
        page_reads = 0.0
        gpu_vram_mb = 0.0
        gpu_util_pct = 0.0
        pdh_disk_rw_ok = False

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

                da = self._read_double("disk_active")
                dq = self._read_double("disk_queue")
                dr = self._read_double("disk_read")
                dw = self._read_double("disk_write")
                cp = self._read_double("commit_pct")
                pr = self._read_double("page_reads")
                gv = self._read_array_sum("gpu_vram")
                gu = self._read_array_sum("gpu_util")

                if da is not None and da >= 0.0:
                    disk_active = min(100.0, round(da, 1))
                if dq is not None and dq >= 0.0:
                    disk_queue = round(dq, 2)
                if dr is not None and dw is not None:
                    disk_read_mb = round(max(0.0, dr) / (1024 * 1024), 2)
                    disk_write_mb = round(max(0.0, dw) / (1024 * 1024), 2)
                    pdh_disk_rw_ok = True
                if cp is not None and cp >= 0.0:
                    commit_pct = min(100.0, round(cp, 1))
                if pr is not None and pr >= 0.0:
                    page_reads = round(pr, 1)
                if gv is not None:
                    gpu_vram_mb = round(gv / (1024 * 1024), 1)
                if gu is not None:
                    gpu_util_pct = min(100.0, round(gu, 1))
            finally:
                self._lock.release()

        now_mono = time.monotonic()
        dt = now_mono - self._prev_io_ts if self._prev_io_ts > 0.0 else 0.0
        net_rx_mb = 0.0
        net_tx_mb = 0.0
        try:
            nio = psutil.net_io_counters()
            if nio is not None:
                cur_net = (int(nio.bytes_recv), int(nio.bytes_sent))
                if self._prev_net_bytes is not None and dt > 0.15:
                    net_rx_mb = round(max(0, cur_net[0] - self._prev_net_bytes[0]) / dt / (1024 * 1024), 2)
                    net_tx_mb = round(max(0, cur_net[1] - self._prev_net_bytes[1]) / dt / (1024 * 1024), 2)
                self._prev_net_bytes = cur_net
        except Exception:  # noqa: BLE001
            pass

        if not pdh_disk_rw_ok:
            try:
                dio = psutil.disk_io_counters()
                if dio is not None:
                    cur_disk = (int(dio.read_bytes), int(dio.write_bytes))
                    if self._prev_disk_bytes is not None and dt > 0.15:
                        disk_read_mb = round(max(0, cur_disk[0] - self._prev_disk_bytes[0]) / dt / (1024 * 1024), 2)
                        disk_write_mb = round(max(0, cur_disk[1] - self._prev_disk_bytes[1]) / dt / (1024 * 1024), 2)
                    self._prev_disk_bytes = cur_disk
            except Exception:  # noqa: BLE001
                pass
        self._prev_io_ts = now_mono

        pinfo = read_performance_info()
        commit_used_gb = float(pinfo.get("commit_used_gb", 0.0))
        commit_limit_gb = float(pinfo.get("commit_limit_gb", 0.0))
        if commit_pct <= 0.0 and pinfo:
            commit_pct = float(pinfo.get("commit_pct", 0.0))
        handles_count = int(pinfo.get("handles", 0))
        threads_count = int(pinfo.get("threads", 0))

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
            disk_active_pct=disk_active,
            disk_queue_len=disk_queue,
            disk_read_mb_s=disk_read_mb,
            disk_write_mb_s=disk_write_mb,
            commit_pct=commit_pct,
            commit_used_gb=commit_used_gb,
            commit_limit_gb=commit_limit_gb,
            page_reads_per_sec=page_reads,
            handles_count=handles_count,
            threads_count=threads_count,
            gpu_vram_shared_mb=gpu_vram_mb,
            gpu_util_pct=gpu_util_pct,
            net_rx_mb_s=net_rx_mb,
            net_tx_mb_s=net_tx_mb,
        )


TEMP_PROBE_UAC_WAIT_S = 120  # tiempo para aceptar el aviso de UAC


PROBE_EXIT_BASE = 1_000_000  # codigo de salida = BASE + cpu_decimas*1000 + nvme (sin archivos)
PROBE_NO_CPU = 2047
PROBE_NO_NVME = 255


def build_temperature_probe_script(mode: str = "exit") -> str:
    """Script PowerShell de la sonda termica. NO escribe archivos.

    v0.6.5 (seguridad): antes el proceso elevado escribia un JSON en una carpeta del usuario, y otro
    proceso podia desviar esa escritura (junction/symlink) con permisos de administrador. Ahora:
    - ``mode="exit"`` (via UAC): devuelve las lecturas codificadas en el CODIGO DE SALIDA, que el
      lanzador no elevado lee con ``Start-Process -PassThru``.
    - ``mode="stdout"`` (la app ya es administradora): imprime el JSON por la salida estandar.
    """
    body = (
        "$ErrorActionPreference='SilentlyContinue'; $ProgressPreference='SilentlyContinue'; $cpu=$null; $nvme=$null; $err=''; "
        "try { $tz=Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop | "
        "Select-Object -First 1; if($tz){ $cpu=[math]::Round(($tz.CurrentTemperature/10.0)-273.15,1) } } "
        "catch { $err=$_.Exception.Message }; "
        "try { $d=Get-PhysicalDisk | Where-Object { $_.MediaType -eq 'SSD' -or $_.BusType -eq 'NVMe' } | "
        "Select-Object -First 1 | Get-StorageReliabilityCounter -ErrorAction Stop; "
        "if($d -and $d.Temperature){ $nvme=[double]$d.Temperature } } catch { if(-not $err){ $err=$_.Exception.Message } }; "
    )
    if mode == "stdout":
        return body + "[Console]::Out.Write(([PSCustomObject]@{cpu=$cpu;nvme=$nvme;error=$err} | ConvertTo-Json -Compress))"
    return body + (
        f"$c={PROBE_NO_CPU}; if($cpu -ne $null -and $cpu -ge 0 -and $cpu -le 200){{ $c=[int][math]::Round($cpu*10) }}; "
        f"$n={PROBE_NO_NVME}; if($nvme -ne $null -and $nvme -ge 0 -and $nvme -le 200){{ $n=[int][math]::Round($nvme) }}; "
        f"exit ({PROBE_EXIT_BASE} + $c*1000 + $n)"
    )


def decode_probe_exit_code(code: int | None) -> dict | None:
    """Codigo de salida de la sonda elevada -> {'cpu', 'nvme'}; None si no es un resultado de la sonda."""
    if code is None or code < PROBE_EXIT_BASE:
        return None
    rest = code - PROBE_EXIT_BASE
    c, n = divmod(rest, 1000)
    if c > PROBE_NO_CPU or n > PROBE_NO_NVME:
        return None
    return {
        "cpu": None if c == PROBE_NO_CPU else round(c / 10.0, 1),
        "nvme": None if n == PROBE_NO_NVME else float(n),
    }


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

    v0.6.5: el script va codificado (-EncodedCommand; antes la PowerShell externa borraba $cpu, $tz...
    y se informaba 'UAC cancelada' aunque se aceptara). El resultado vuelve por el codigo de salida
    (via UAC) o por stdout (si la app ya es administradora): ningun proceso elevado escribe archivos.
    """
    if not IS_WINDOWS:
        return None, None, "Solo Windows"
    from .win32_bridge import is_user_admin

    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    stderr_txt = ""
    data: dict | None = None
    try:
        if is_user_admin():
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                   _encode_ps(build_temperature_probe_script("stdout"))]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60, creationflags=no_window)
            try:
                parsed = json.loads((res.stdout or "").strip() or "null")
                data = parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                data = None
        else:
            encoded = _encode_ps(build_temperature_probe_script("exit"))
            launcher = (
                "$ProgressPreference='SilentlyContinue'; "
                "$p=Start-Process -FilePath powershell -Verb RunAs -WindowStyle Hidden -Wait -PassThru "
                f"-ArgumentList '-NoProfile','-NonInteractive','-EncodedCommand','{encoded}'; "
                "if($p){ [Console]::Out.Write($p.ExitCode) }"
            )
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", launcher]
            res = subprocess.run(
                cmd, capture_output=True, text=True, timeout=TEMP_PROBE_UAC_WAIT_S, creationflags=no_window
            )
            out = (res.stdout or "").strip()
            data = decode_probe_exit_code(int(out)) if out.lstrip("-").isdigit() else None
        stderr_txt = (res.stderr or "").strip()
    except subprocess.TimeoutExpired:
        stderr_txt = ""
    except OSError as exc:
        return None, None, f"Error leyendo sensores: {exc}"
    return interpret_temperature_probe(data, stderr_txt)
