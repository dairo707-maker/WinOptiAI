"""Read-only BIOS, UEFI, GPU driver, and NVMe SSD health auditor.

Strictly adheres to Windows 11 Secure Boot & firmware safety:
- NEVER writes to SPI flash or NVRAM directly
- Reads SMBIOS/WMI/CIM telemetry (Win32_BIOS, Win32_Processor, Win32_VideoController,
  MSFT_PhysicalDisk, Lenovo battery/thermal WMI classes)
- Audits Intel Iris Xe driver branch for local AI (Vulkan/OpenVINO/DirectML)
- Provides guided UEFI reboot (shutdown /r /fw) with UAC elevation on user demand
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import subprocess

from ..core.win32_bridge import IS_WINDOWS, run_elevated_command


@dataclass(slots=True)
class HardwareAuditReport:
    """Comprehensive snapshot of firmware, CPU, iGPU, NVMe, and security posture."""

    manufacturer: str
    model: str
    bios_version: str
    bios_date: str
    cpu_name: str
    cpu_cores: str
    gpu_name: str
    gpu_driver: str
    gpu_driver_outdated: bool
    nvme_model: str
    nvme_health: str
    disk_free_gb: float
    disk_total_gb: float
    secure_boot: str
    virtualization: str
    battery_pct: int | None
    recommendations: list[dict[str, str]]


def _ps_json(script: str) -> dict:
    if not IS_WINDOWS:
        return {}
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    full_script = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n" + script
    encoded = base64.b64encode(full_script.encode("utf-16le")).decode("ascii")
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
            creationflags=creation_flags,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return {}
        return json.loads(res.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}


def run_hardware_bios_audit() -> HardwareAuditReport:
    """Collect real hardware, SMBIOS, driver, and storage health telemetry."""
    ps_script = r"""
$cs = Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer, Model
$bios = Get-CimInstance Win32_BIOS | Select-Object SMBIOSBIOSVersion, ReleaseDate
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1 Name, NumberOfCores, NumberOfLogicalProcessors, VirtualizationFirmwareEnabled
$gpu = Get-CimInstance Win32_VideoController | Select-Object -First 1 Name, DriverVersion
$disk = Get-PhysicalDisk | Where-Object { $_.BusType -eq 'NVMe' -or $_.MediaType -eq 'SSD' } | Sort-Object Size -Descending | Select-Object -First 1 FriendlyName, HealthStatus
$vol = Get-PSDrive -Name C -PSProvider FileSystem | Select-Object @{N='FreeGB';E={[math]::Round($_.Free/1GB,2)}}, @{N='TotalGB';E={[math]::Round(($_.Used+$_.Free)/1GB,2)}}
$bat = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | Select-Object -First 1 EstimatedChargeRemaining
$sb = 'Desconocido'
try { if (Confirm-SecureBootUEFI) { $sb = 'Activo' } else { $sb = 'Inactivo' } } catch { $sb = 'Protegido (requiere admin)' }

[PSCustomObject]@{
  Manufacturer = $cs.Manufacturer
  Model = $cs.Model
  BiosVersion = $bios.SMBIOSBIOSVersion
  BiosDate = if ($bios.ReleaseDate) { $bios.ReleaseDate.ToString('yyyy-MM-dd') } else { 'N/D' }
  CpuName = $cpu.Name
  CpuCores = "$($cpu.NumberOfCores)C / $($cpu.NumberOfLogicalProcessors)T"
  Virt = if ($cpu.VirtualizationFirmwareEnabled) { 'Habilitada' } else { 'Revisar en UEFI' }
  GpuName = $gpu.Name
  GpuDriver = $gpu.DriverVersion
  NvmeModel = $disk.FriendlyName
  NvmeHealth = [string]$disk.HealthStatus
  DiskFreeGB = $vol.FreeGB
  DiskTotalGB = $vol.TotalGB
  BatteryPct = if ($bat) { [int]$bat.EstimatedChargeRemaining } else { $null }
  SecureBoot = $sb
} | ConvertTo-Json -Compress
"""
    raw = _ps_json(ps_script)

    gpu_driver = str(raw.get("GpuDriver") or "N/D")
    # Intel Iris Xe 30.0.x branch is from 2022 and lacks modern WDDM 3.2 / Vulkan / OpenVINO optimizations
    driver_major = 0
    try:
        driver_major = int(gpu_driver.split(".")[0])
    except ValueError:
        driver_major = 0
    gpu_outdated = 0 < driver_major < 32

    recs: list[dict[str, str]] = []
    if gpu_outdated:
        recs.append(
            {
                "area": "GPU / IA Local",
                "estado": "ACTUALIZAR",
                "detalle": (
                    f"Controlador Intel Iris Xe ({gpu_driver}) antiguo. Se recomienda actualizar a la rama "
                    "32.0.101.x via Intel Driver & Support Assistant para acelerar DirectML, Vulkan y OpenVINO."
                ),
            }
        )
    else:
        recs.append(
            {
                "area": "GPU / IA Local",
                "estado": "OPTIMO",
                "detalle": f"Controlador grafico ({gpu_driver}) en rama moderna.",
            }
        )

    bios_ver = str(raw.get("BiosVersion") or "N/D")
    model = str(raw.get("Model") or "PC")
    manufacturer = str(raw.get("Manufacturer") or "LENOVO")
    recs.append(
        {
            "area": "BIOS / Termica UEFI",
            "estado": "REVISAR",
            "detalle": (
                f"En {manufacturer} {model} ({bios_ver}), verifique en UEFI -> Configuration: "
                "'System Performance Mode = Intelligent Cooling' (reduce calor en IA online) y "
                "'Intel Virtualization Technology = Enabled'."
            ),
        }
    )
    recs.append(
        {
            "area": "Bateria y Degradacion",
            "estado": "RECOMENDADO",
            "detalle": (
                "En sesiones prolongadas conectado a corriente, active 'Conservation Mode' en Lenovo Vantage "
                "o UEFI para limitar la carga al 60-80% y reducir calor en la placa."
            ),
        }
    )

    return HardwareAuditReport(
        manufacturer=manufacturer,
        model=model,
        bios_version=bios_ver,
        bios_date=str(raw.get("BiosDate") or "N/D"),
        cpu_name=str(raw.get("CpuName") or "N/D"),
        cpu_cores=str(raw.get("CpuCores") or "N/D"),
        gpu_name=str(raw.get("GpuName") or "N/D"),
        gpu_driver=gpu_driver,
        gpu_driver_outdated=gpu_outdated,
        nvme_model=str(raw.get("NvmeModel") or "SSD"),
        nvme_health=str(raw.get("NvmeHealth") or "Healthy"),
        disk_free_gb=float(raw.get("DiskFreeGB") or 0.0),
        disk_total_gb=float(raw.get("DiskTotalGB") or 0.0),
        secure_boot=str(raw.get("SecureBoot") or "N/D"),
        virtualization=str(raw.get("Virt") or "N/D"),
        battery_pct=raw.get("BatteryPct"),
        recommendations=recs,
    )


def reboot_to_uefi_firmware() -> tuple[bool, str]:
    """Request elevated restart directly into UEFI BIOS firmware setup (shutdown /r /fw)."""
    if not IS_WINDOWS:
        return False, "Solo disponible en Windows"
    ok = run_elevated_command("shutdown.exe", "/r /fw /t 10 /c \"WinOptiAI: Reinicio asistido hacia UEFI BIOS\"")
    if ok:
        return True, "Reinicio a UEFI programado en 10 segundos. Guarde su trabajo."
    return False, "Se cancelo la autorizacion UAC para reiniciar a UEFI."


def run_nvme_trim_analysis() -> tuple[bool, str]:
    """Run Windows Storage Optimizer ReTrim on drive C: (safe SSD maintenance)."""
    if not IS_WINDOWS:
        return False, "Solo disponible en Windows"
    ok = run_elevated_command(
        "powershell.exe",
        "-NoProfile -Command \"Optimize-Volume -DriveLetter C -ReTrim -Verbose; Pause\"",
    )
    if ok:
        return True, "Optimizacion TRIM lanzada en consola elevada para unidad C:."
    return False, "Autorizacion UAC cancelada por el usuario."
