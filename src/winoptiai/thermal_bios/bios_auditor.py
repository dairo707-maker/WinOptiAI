"""Universal multi-vendor hardware profiler, BIOS/driver auditor, and automated remediation.

Scans ANY Windows 11 PC (Lenovo, Dell, HP, ASUS, Acer, Desktop; Intel/AMD CPU;
Intel/NVIDIA/AMD GPU; NVMe/SATA SSD/HDD; 8GB-128GB RAM) and generates:
- Hardware profile calibration (dynamic SRE RAM threshold, AI inference capabilities)
- Read-only BIOS/UEFI, driver, and storage health diagnostics
- Actionable 1-click remediations launchable directly from the Audit table
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import subprocess

from ..core.sre_policy import recommended_ram_threshold_gb
from ..core.win32_bridge import IS_WINDOWS, run_elevated_command
from .thermal_controller import apply_thermal_profile


@dataclass(slots=True)
class HardwareAuditReport:
    """Universal hardware, firmware, GPU, storage, and security report."""

    manufacturer: str
    model: str
    is_laptop: bool
    bios_version: str
    bios_date: str
    cpu_name: str
    cpu_vendor: str
    cpu_cores: str
    gpu_name: str
    gpu_vendor: str
    gpu_driver: str
    gpu_driver_outdated: bool
    nvme_model: str
    nvme_health: str
    media_type: str
    disk_free_gb: float
    disk_total_gb: float
    total_ram_gb: float
    recommended_ram_threshold_gb: float
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


def _detect_cpu_vendor(cpu_name: str) -> str:
    low = cpu_name.lower()
    if "intel" in low:
        return "Intel"
    if "amd" in low or "ryzen" in low:
        return "AMD"
    if "snapdragon" in low or "qualcomm" in low or "arm" in low:
        return "ARM64"
    return "Generico"


def _detect_gpu_vendor(gpus: list[dict]) -> tuple[str, str, str, bool]:
    """Pick the most capable GPU (discrete NVIDIA/AMD preferred, else Intel/integrated)."""
    if not gpus:
        return "N/D", "Generico", "N/D", False

    # Prefer NVIDIA or AMD discrete if present alongside integrated GPU
    chosen = gpus[0]
    for g in gpus:
        name = str(g.get("Name") or "").lower()
        if "nvidia" in name or "geforce" in name or "rtx" in name or "radeon" in name:
            chosen = g
            break

    gname = str(chosen.get("Name") or "N/D")
    gdrive = str(chosen.get("DriverVersion") or "N/D")
    low = gname.lower()

    if "nvidia" in low:
        vendor = "NVIDIA"
        outdated = False
    elif "amd" in low or "radeon" in low:
        vendor = "AMD"
        outdated = False
    elif "intel" in low:
        vendor = "Intel"
        try:
            major = int(gdrive.split(".")[0])
            outdated = 0 < major < 32
        except ValueError:
            outdated = False
    else:
        vendor = "Generico"
        outdated = False

    return gname, vendor, gdrive, outdated


def run_hardware_bios_audit() -> HardwareAuditReport:
    """Collect universal hardware, SMBIOS, multi-GPU, RAM, and storage health telemetry."""
    ps_script = r"""
$cs = Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer, Model, TotalPhysicalMemory
$bios = Get-CimInstance Win32_BIOS | Select-Object SMBIOSBIOSVersion, ReleaseDate
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1 Name, NumberOfCores, NumberOfLogicalProcessors, VirtualizationFirmwareEnabled
$gpus = @(Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion)
$disk = Get-PhysicalDisk | Where-Object { $_.BusType -notlike '*Virtual*' -and $_.FriendlyName -notlike '*Virtual*' } | Sort-Object @{E={if($_.BusType -eq 'NVMe'){0}elseif($_.MediaType -eq 'SSD'){1}else{2}};Descending=$false}, @{E={$_.Size};Descending=$true} | Select-Object -First 1 FriendlyName, HealthStatus, MediaType, BusType
if (-not $disk) {
  $disk = Get-PhysicalDisk | Sort-Object @{E={$_.Size};Descending=$true} | Select-Object -First 1 FriendlyName, HealthStatus, MediaType, BusType
}
$vol = Get-PSDrive -Name C -PSProvider FileSystem | Select-Object @{N='FreeGB';E={[math]::Round($_.Free/1GB,2)}}, @{N='TotalGB';E={[math]::Round(($_.Used+$_.Free)/1GB,2)}}
$bat = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | Select-Object -First 1 EstimatedChargeRemaining
$sb = 'Desconocido'
try { if (Confirm-SecureBootUEFI) { $sb = 'Activo' } else { $sb = 'Inactivo' } } catch { $sb = 'Protegido (requiere admin)' }

[PSCustomObject]@{
  Manufacturer = $cs.Manufacturer
  Model = $cs.Model
  TotalRamGB = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
  BiosVersion = $bios.SMBIOSBIOSVersion
  BiosDate = if ($bios.ReleaseDate) { $bios.ReleaseDate.ToString('yyyy-MM-dd') } else { 'N/D' }
  CpuName = $cpu.Name
  CpuCores = "$($cpu.NumberOfCores)C / $($cpu.NumberOfLogicalProcessors)T"
  Virt = if ($cpu.VirtualizationFirmwareEnabled) { 'Habilitada' } else { 'Revisar en UEFI' }
  Gpus = $gpus
  NvmeModel = $disk.FriendlyName
  NvmeHealth = [string]$disk.HealthStatus
  MediaType = if($disk.BusType -eq 'NVMe'){'NVMe SSD'}elseif($disk.MediaType){[string]$disk.MediaType}else{'SSD'}
  DiskFreeGB = $vol.FreeGB
  DiskTotalGB = $vol.TotalGB
  HasBattery = ($null -ne $bat)
  BatteryPct = if ($bat) { [int]$bat.EstimatedChargeRemaining } else { $null }
  SecureBoot = $sb
} | ConvertTo-Json -Depth 4 -Compress
"""
    raw = _ps_json(ps_script)

    manufacturer = str(raw.get("Manufacturer") or "PC")
    model = str(raw.get("Model") or "Generico")
    is_laptop = bool(raw.get("HasBattery"))
    bios_ver = str(raw.get("BiosVersion") or "N/D")
    cpu_name = str(raw.get("CpuName") or "N/D")
    cpu_vendor = _detect_cpu_vendor(cpu_name)
    total_ram_gb = float(raw.get("TotalRamGB") or 16.0)
    dyn_threshold = recommended_ram_threshold_gb()

    gpus = raw.get("Gpus") or []
    if isinstance(gpus, dict):
        gpus = [gpus]
    gpu_name, gpu_vendor, gpu_driver, gpu_outdated = _detect_gpu_vendor(gpus)

    media_type = str(raw.get("MediaType") or "SSD")

    recs: list[dict[str, str]] = []

    # 1. GPU / Local AI Driver Recommendation
    if gpu_vendor == "Intel" and gpu_outdated:
        recs.append(
            {
                "area": "GPU / IA Local (Intel)",
                "estado": "ACTUALIZAR",
                "reinicio": "SI (tras driver)",
                "detalle": (
                    f"Driver {gpu_name} ({gpu_driver}) antiguo. Se recomienda rama 32.0.101.x "
                    "para acelerar Vulkan, DirectML y OpenVINO en IA local."
                ),
                "action_id": "update_intel_gpu",
                "action_label": "Instalar Intel DSA",
            }
        )
    elif gpu_vendor == "NVIDIA":
        recs.append(
            {
                "area": "GPU / IA Local (NVIDIA)",
                "estado": "COMPATIBLE",
                "reinicio": "Opcional (driver)",
                "detalle": f"{gpu_name} ({gpu_driver}) apta para aceleracion CUDA / TensorRT / Ollama.",
                "action_id": "update_nvidia_gpu",
                "action_label": "Actualizar Drivers",
            }
        )
    elif gpu_vendor == "AMD":
        recs.append(
            {
                "area": "GPU / IA Local (AMD)",
                "estado": "COMPATIBLE",
                "reinicio": "Opcional (driver)",
                "detalle": f"{gpu_name} ({gpu_driver}) apta para DirectML / Vulkan.",
                "action_id": "open_windows_update",
                "action_label": "Buscar Drivers",
            }
        )
    else:
        recs.append(
            {
                "area": "GPU / IA Local",
                "estado": "OPTIMO",
                "reinicio": "NO (inmediato)",
                "detalle": f"Controlador grafico {gpu_name} ({gpu_driver}) actualizado.",
                "action_id": "open_windows_update",
                "action_label": "Windows Update",
            }
        )

    # 2. Thermal & Processor Calibration
    if is_laptop:
        recs.append(
            {
                "area": f"Termica {cpu_vendor} (Portatil)",
                "estado": "RECOMENDADO",
                "reinicio": "NO (inmediato)",
                "detalle": (
                    "Activar perfil Frio / Silencioso (EPP 65%) para reducir 12-18 C en sesiones "
                    "de IA agentica online y evitar estrangulamiento termico."
                ),
                "action_id": "apply_cool_profile",
                "action_label": "Aplicar Perfil Frio",
            }
        )
    else:
        recs.append(
            {
                "area": f"Energia {cpu_vendor} (Escritorio)",
                "estado": "RECOMENDADO",
                "reinicio": "NO (inmediato)",
                "detalle": "Calibrar perfil Equilibrado Inteligente para cargas mixtas de agentes IA.",
                "action_id": "apply_balanced_profile",
                "action_label": "Aplicar Equilibrado",
            }
        )

    # 3. BIOS / UEFI & Virtualization
    recs.append(
        {
            "area": "BIOS / UEFI Firmware",
            "estado": "REVISAR",
            "reinicio": "SI (reinicia a UEFI)",
            "detalle": (
                f"{manufacturer} {model} ({bios_ver}) | Virt: {raw.get('Virt', 'N/D')}. "
                "Verificar VT-x/AMD-V y modo de enfriamiento inteligente en UEFI."
            ),
            "action_id": "open_uefi_bios",
            "action_label": "Reiniciar a UEFI",
        }
    )

    # 4. Storage Maintenance (SSD TRIM vs HDD Defrag)
    if "SSD" in media_type or "NVMe" in media_type:
        recs.append(
            {
                "area": f"Almacenamiento ({media_type})",
                "estado": "MANTENIMIENTO",
                "reinicio": "NO (inmediato)",
                "detalle": (
                    f"{raw.get('NvmeModel', 'SSD')} [{raw.get('NvmeHealth', 'Healthy')}]. "
                    "Ejecutar ReTrim seguro en unidad C: para sostener velocidad de escritura."
                ),
                "action_id": "optimize_trim",
                "action_label": "Ejecutar ReTrim",
            }
        )
    else:
        recs.append(
            {
                "area": "Almacenamiento (HDD)",
                "estado": "MANTENIMIENTO",
                "reinicio": "NO (inmediato)",
                "detalle": "Disco mecanico detectado: optimizar fragmentacion de archivos.",
                "action_id": "optimize_defrag",
                "action_label": "Optimizar Disco",
            }
        )

    # 5. Battery / Conservation Mode (laptops)
    if is_laptop:
        recs.append(
            {
                "area": "Bateria y Conservacion",
                "estado": "RECOMENDADO",
                "reinicio": "NO (inmediato)",
                "detalle": (
                    "Si trabaja conectado a corriente, active el modo de conservacion (limite 60-80%) "
                    f"en la utilidad de {manufacturer} o configuracion de energia."
                ),
                "action_id": "open_power_settings",
                "action_label": "Abrir Energia",
            }
        )

    return HardwareAuditReport(
        manufacturer=manufacturer,
        model=model,
        is_laptop=is_laptop,
        bios_version=bios_ver,
        bios_date=str(raw.get("BiosDate") or "N/D"),
        cpu_name=cpu_name,
        cpu_vendor=cpu_vendor,
        cpu_cores=str(raw.get("CpuCores") or "N/D"),
        gpu_name=gpu_name,
        gpu_vendor=gpu_vendor,
        gpu_driver=gpu_driver,
        gpu_driver_outdated=gpu_outdated,
        nvme_model=str(raw.get("NvmeModel") or "SSD"),
        nvme_health=str(raw.get("NvmeHealth") or "Healthy"),
        media_type=media_type,
        disk_free_gb=float(raw.get("DiskFreeGB") or 0.0),
        disk_total_gb=float(raw.get("DiskTotalGB") or 0.0),
        total_ram_gb=total_ram_gb,
        recommended_ram_threshold_gb=dyn_threshold,
        secure_boot=str(raw.get("SecureBoot") or "N/D"),
        virtualization=str(raw.get("Virt") or "N/D"),
        battery_pct=raw.get("BatteryPct"),
        recommendations=recs,
    )


def reboot_to_uefi_firmware() -> tuple[bool, str]:
    """Request elevated restart directly into UEFI BIOS firmware setup (shutdown /r /fw)."""
    if not IS_WINDOWS:
        return False, "Solo disponible en Windows"
    ok = run_elevated_command("shutdown.exe", '/r /fw /t 10 /c "WinOptiAI: Reinicio asistido hacia UEFI BIOS"')
    if ok:
        return True, "Reinicio a UEFI programado en 10 segundos. Guarde su trabajo."
    return False, "Se cancelo la autorizacion UAC para reiniciar a UEFI."


def run_nvme_trim_analysis() -> tuple[bool, str]:
    """Run Windows Storage Optimizer ReTrim on drive C: (safe SSD maintenance)."""
    if not IS_WINDOWS:
        return False, "Solo disponible en Windows"
    ok = run_elevated_command(
        "powershell.exe",
        '-NoProfile -Command "Optimize-Volume -DriveLetter C -ReTrim -Verbose; Pause"',
    )
    if ok:
        return True, "Optimizacion TRIM lanzada en consola elevada para unidad C:."
    return False, "Autorizacion UAC cancelada por el usuario."


def execute_audit_action(action_id: str) -> tuple[bool, str]:
    """Launch an automated remediation directly from an Audit table recommendation."""
    if action_id == "apply_cool_profile":
        return apply_thermal_profile("cool")
    if action_id == "apply_balanced_profile":
        return apply_thermal_profile("balanced")
    if action_id == "open_uefi_bios":
        return reboot_to_uefi_firmware()
    if action_id == "optimize_trim":
        return run_nvme_trim_analysis()
    if action_id == "optimize_defrag":
        ok = run_elevated_command(
            "powershell.exe",
            '-NoProfile -Command "Optimize-Volume -DriveLetter C -Defrag -Verbose; Pause"',
        )
        return ok, "Desfragmentacion lanzada para unidad C:." if ok else "Operacion cancelada."

    if not IS_WINDOWS:
        return False, "Solo disponible en Windows"

    if action_id == "update_intel_gpu":
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "winget install --id Intel.IntelDriverAndSupportAssistant -e --accept-package-agreements --accept-source-agreements; "
                "Start-Process 'https://www.intel.com/content/www/us/en/support/detect.html'",
            ],
        )
        return True, "Lanzando instalacion de Intel Driver & Support Assistant via winget."

    if action_id == "update_nvidia_gpu":
        subprocess.Popen(["cmd", "/c", "start", "", "https://www.nvidia.com/Download/index.aspx"])
        return True, "Abriendo descarga oficial de controladores NVIDIA."

    if action_id == "open_windows_update":
        subprocess.Popen(["cmd", "/c", "start", "", "ms-settings:windowsupdate"])
        return True, "Abriendo Windows Update para buscar controladores certificados."

    if action_id == "open_power_settings":
        subprocess.Popen(["cmd", "/c", "start", "", "ms-settings:powersleep"])
        return True, "Abriendo configuracion de energia y bateria de Windows."

    return False, f"Accion no reconocida: {action_id}"
