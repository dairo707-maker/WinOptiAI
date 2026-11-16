"""Real-time CPU frequency, Turbo ratio, per-core load, and thermal sensor telemetry."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import json
import subprocess

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

    def __init__(self) -> None:
        self._pdh = None
        self._query = wintypes.HANDLE()
        self._handles: dict[str, wintypes.HANDLE] = {}
        self._last_elevated_cpu_temp: float | None = None
        self._last_elevated_nvme_temp: float | None = None

        if IS_WINDOWS:
            try:
                self._pdh = ctypes.WinDLL("pdh.dll")
                rc = self._pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query))
                if rc == 0:
                    counters = {
                        "utility": r"\Processor Information(_Total)\% Processor Utility",
                        "freq": r"\Processor Information(_Total)\Processor Frequency",
                        "perf": r"\Processor Information(_Total)\% Processor Performance",
                    }
                    for key, path in counters.items():
                        ch = wintypes.HANDLE()
                        if self._pdh.PdhAddEnglishCounterW(self._query, path, 0, ctypes.byref(ch)) == 0:
                            self._handles[key] = ch
                    self._pdh.PdhCollectQueryData(self._query)
            except OSError:
                self._pdh = None

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

        if self._pdh and self._query:
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


def probe_elevated_temperatures() -> tuple[float | None, float | None, str]:
    """Run a one-shot elevated PowerShell sensor probe for ACPI CPU & NVMe SMART temperatures."""
    if not IS_WINDOWS:
        return None, None, "Solo Windows"
    import os
    import tempfile
    from pathlib import Path

    out_file = Path(tempfile.gettempdir()) / f"winoptiai_temps_{os.getpid()}.json"
    ps_cmd = (
        "$cpu=$null; $nvme=$null; "
        "try { $tz=Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -EA Stop | Select-Object -First 1; "
        "if($tz){ $cpu=[math]::Round(($tz.CurrentTemperature/10.0)-273.15,1) } } catch {}; "
        "try { $d=Get-PhysicalDisk | Where-Object {$_.MediaType -eq 'SSD' -or $_.BusType -eq 'NVMe'} | Select-Object -First 1 | Get-StorageReliabilityCounter -EA Stop; "
        "if($d -and $d.Temperature){ $nvme=[double]$d.Temperature } } catch {}; "
        f"[PSCustomObject]@{{cpu=$cpu;nvme=$nvme}} | ConvertTo-Json | Set-Content -Path '{out_file}' -Encoding UTF8"
    )
    # Use ShellExecuteEx-like Start-Process -Verb RunAs -Wait so we get exit synchronously
    wrapper = [
        "powershell",
        "-NoProfile",
        "-Command",
        f'Start-Process powershell -Verb RunAs -WindowStyle Hidden -Wait -ArgumentList "-NoProfile -Command {ps_cmd.replace(chr(34), chr(92) + chr(34))}"',
    ]
    try:
        subprocess.run(wrapper, timeout=25, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out_file.exists():
            data = json.loads(out_file.read_text(encoding="utf-8-sig"))
            out_file.unlink(missing_ok=True)
            cpu_t = data.get("cpu")
            nvme_t = data.get("nvme")
            if cpu_t is None and nvme_t is None:
                return None, None, "Placa ACPI no expone sonda termica directa; monitoreo por MHz/Turbo activo."
            return cpu_t, nvme_t, "Lectura termica elevada completada"
        return None, None, "Autorizacion UAC cancelada"
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return None, None, f"Error leyendo sensores: {exc}"
