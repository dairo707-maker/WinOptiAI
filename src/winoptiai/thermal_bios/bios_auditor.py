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
from datetime import datetime
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
    smart_summary: str = "N/D"
    disk_events_count: int = 0
    security_posture: str = "N/D"
    oem_tool: str = ""


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
$disk = Get-PhysicalDisk | Where-Object { $_.BusType -notlike '*Virtual*' -and $_.FriendlyName -notlike '*Virtual*' } | Sort-Object @{E={if($_.BusType -eq 'NVMe'){0}elseif($_.MediaType -eq 'SSD'){1}else{2}};Descending=$false}, @{E={$_.Size};Descending=$true} | Select-Object -First 1 FriendlyName, HealthStatus, MediaType, BusType, DeviceId
if (-not $disk) {
  $disk = Get-PhysicalDisk | Sort-Object @{E={$_.Size};Descending=$true} | Select-Object -First 1 FriendlyName, HealthStatus, MediaType, BusType, DeviceId
}
$smart = $null
try { if ($disk) { $smart = $disk | Get-StorageReliabilityCounter -EA SilentlyContinue | Select-Object Temperature, Wear, ReadErrorsTotal, WriteErrorsTotal, PowerOnHours } } catch {}
$diskErrs = 0
try {
  $since = (Get-Date).AddDays(-14)
  $ev = @(Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='disk','ntfs','Ntfs','WHEA-Logger','stornvme'; Level=1,2,3; StartTime=$since} -MaxEvents 40 -EA SilentlyContinue)
  $diskErrs = $ev.Count
} catch {}
$hvci = 'Desconocido'
try {
  $dg = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity' -EA SilentlyContinue
  if ($dg -and $dg.Enabled -eq 1) { $hvci = 'Activo' } else { $hvci = 'Inactivo' }
} catch {}
$fastBoot = $null
try {
  $fb = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -EA SilentlyContinue
  if ($null -ne $fb.HiberbootEnabled) { $fastBoot = [int]$fb.HiberbootEnabled }
} catch {}
$tpmReady = 'N/D'
try { $t = Get-Tpm -EA SilentlyContinue; if ($t) { $tpmReady = if ($t.TpmReady) { 'TPM 2.0 OK' } else { 'Revisar TPM' } } } catch {}
$bl = 'N/D'
try { $bv = Get-BitLockerVolume -MountPoint 'C:' -EA SilentlyContinue; if ($bv) { $bl = [string]$bv.ProtectionStatus } } catch {}
$vol = Get-PSDrive -Name C -PSProvider FileSystem | Select-Object @{N='FreeGB';E={[math]::Round($_.Free/1GB,2)}}, @{N='TotalGB';E={[math]::Round(($_.Used+$_.Free)/1GB,2)}}
$bat = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | Select-Object -First 1 EstimatedChargeRemaining
$sb = 'Desconocido'
try { if (Confirm-SecureBootUEFI) { $sb = 'Activo' } else { $sb = 'Inactivo' } } catch { $sb = 'Protegido (admin)' }

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
  SmartTemp = if($smart -and $null -ne $smart.Temperature){[int]$smart.Temperature}else{$null}
  SmartWear = if($smart -and $null -ne $smart.Wear){[int]$smart.Wear}else{$null}
  SmartReadErr = if($smart -and $null -ne $smart.ReadErrorsTotal){[int]$smart.ReadErrorsTotal}else{0}
  SmartWriteErr = if($smart -and $null -ne $smart.WriteErrorsTotal){[int]$smart.WriteErrorsTotal}else{0}
  SmartHours = if($smart -and $null -ne $smart.PowerOnHours){[int]$smart.PowerOnHours}else{$null}
  DiskEvents14d = $diskErrs
  Hvci = $hvci
  FastBoot = $fastBoot
  Tpm = $tpmReady
  BitLocker = $bl
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

    # 5. Deep Disk Integrity, SMART & Windows System Repair (CHKDSK /scan, SFC/DISM, WinSxS)
    smart_parts: list[str] = []
    if raw.get("SmartWear") is not None:
        smart_parts.append(f"Desgaste {raw['SmartWear']}%")
    if raw.get("SmartTemp") is not None:
        smart_parts.append(f"{raw['SmartTemp']} C")
    if raw.get("SmartHours") is not None:
        smart_parts.append(f"{raw['SmartHours']}h")
    read_err = int(raw.get("SmartReadErr") or 0)
    write_err = int(raw.get("SmartWriteErr") or 0)
    if read_err or write_err:
        smart_parts.append(f"Err R/W: {read_err}/{write_err}")
    smart_summary = " | ".join(smart_parts) if smart_parts else "SMART protegido (eleva UAC en disco)"
    disk_events = int(raw.get("DiskEvents14d") or 0)

    recs.append(
        {
            "area": "Salud Disco & SMART",
            "estado": "ALERTA" if (disk_events > 0 or read_err > 0 or write_err > 0) else "VERIFICAR",
            "reinicio": "NO (en linea)",
            "detalle": (
                f"SMART: {smart_summary} | Eventos NTFS/Disk/WHEA (14d): {disk_events}. "
                "Ejecutar CHKDSK C: /scan en linea sin desmontar el volumen."
            ),
            "action_id": "run_chkdsk_scan",
            "action_label": "CHKDSK /scan",
        }
    )
    recs.append(
        {
            "area": "Integridad SO (SFC/DISM)",
            "estado": "MANTENIMIENTO",
            "reinicio": "NO (inmediato)",
            "detalle": "Verificar y reparar archivos protegidos de Windows e imagen WinSxS.",
            "action_id": "run_sfc_dism",
            "action_label": "Reparar SFC+DISM",
        }
    )
    recs.append(
        {
            "area": "Almacen WinSxS",
            "estado": "ESPACIO",
            "reinicio": "NO (inmediato)",
            "detalle": "Depurar componentes obsoletos de actualizaciones de Windows (/StartComponentCleanup).",
            "action_id": "run_winsxs_cleanup",
            "action_label": "Limpiar WinSxS",
        }
    )

    # 6. OEM Firmware Updater + BIOS Age & Fast Startup
    mfg_low = manufacturer.lower()
    oem_tool = "Windows Update"
    oem_action = "open_windows_update"
    if "lenovo" in mfg_low:
        oem_tool = "Lenovo Vantage"
        oem_action = "launch_lenovo_vantage"
    elif "dell" in mfg_low:
        oem_tool = "Dell Command Update"
        oem_action = "launch_dell_command"
    elif "hp" in mfg_low or "hewlett" in mfg_low:
        oem_tool = "HP Support"
        oem_action = "launch_hp_support"
    elif "asus" in mfg_low:
        oem_tool = "MyASUS"
        oem_action = "launch_asus_myasus"

    bios_date_str = str(raw.get("BiosDate") or "N/D")
    bios_old = False
    if bios_date_str != "N/D":
        try:
            bdt = datetime.strptime(bios_date_str, "%Y-%m-%d")
            bios_old = (datetime.now() - bdt).days > 730
        except ValueError:
            pass
    if oem_action != "open_windows_update" or bios_old:
        recs.append(
            {
                "area": f"Firmware OEM ({manufacturer})",
                "estado": "ANTIGUA (>2a)" if bios_old else "ACTUALIZAR",
                "reinicio": "SI (si hay BIOS)",
                "detalle": f"BIOS actual {bios_ver} ({bios_date_str}). Revisar BIOS y drivers oficiales en {oem_tool}.",
                "action_id": oem_action,
                "action_label": f"Abrir {oem_tool[:14]}",
            }
        )

    if raw.get("FastBoot") == 1:
        recs.append(
            {
                "area": "Inicio Rapido (Kernel)",
                "estado": "OPCIONAL",
                "reinicio": "Prox. apagado",
                "detalle": "Fast Startup (Hiberboot) esta activo; desactivarlo evita sesiones sucias de drivers y RAM tras apagar.",
                "action_id": "disable_fast_startup",
                "action_label": "Desactivar FastBoot",
            }
        )

    # 7. Battery / Conservation Mode (laptops)
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

    sec_posture = (
        f"SecureBoot: {raw.get('SecureBoot', 'N/D')} | "
        f"HVCI: {raw.get('Hvci', 'N/D')} | "
        f"{raw.get('Tpm', 'TPM N/D')} | BitLocker C: {raw.get('BitLocker', 'N/D')}"
    )

    return HardwareAuditReport(
        manufacturer=manufacturer,
        model=model,
        is_laptop=is_laptop,
        bios_version=bios_ver,
        bios_date=bios_date_str,
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
        smart_summary=smart_summary,
        disk_events_count=disk_events,
        security_posture=sec_posture,
        oem_tool=oem_tool,
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

    if action_id == "run_chkdsk_scan":
        ok = run_elevated_command(
            "powershell.exe",
            '-NoProfile -Command "chkdsk C: /scan; Write-Host; Pause"',
        )
        return ok, "CHKDSK C: /scan en linea lanzado en consola elevada." if ok else "Operacion cancelada."

    if action_id == "run_sfc_dism":
        ok = run_elevated_command(
            "powershell.exe",
            '-NoProfile -Command "DISM /Online /Cleanup-Image /RestoreHealth; sfc /scannow; Write-Host; Pause"',
        )
        return ok, "Reparacion DISM + SFC /scannow lanzada en consola elevada." if ok else "Operacion cancelada."

    if action_id == "run_winsxs_cleanup":
        ok = run_elevated_command(
            "powershell.exe",
            '-NoProfile -Command "Dism.exe /Online /Cleanup-Image /StartComponentCleanup; Write-Host; Pause"',
        )
        return ok, "Limpieza profunda WinSxS lanzada en consola elevada." if ok else "Operacion cancelada."

    if action_id == "disable_fast_startup":
        ok = run_elevated_command(
            "reg.exe",
            r'add "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power" /v HiberbootEnabled /t REG_DWORD /d 0 /f',
        )
        return ok, "Fast Startup desactivado (aplicara en el proximo apagado/inicio)." if ok else "Operacion cancelada."

    oem_urls = {
        "launch_lenovo_vantage": ("lenovo-vantage:", "https://pcsupport.lenovo.com/"),
        "launch_dell_command": ("https://www.dell.com/support/home", "https://www.dell.com/support/home"),
        "launch_hp_support": ("https://support.hp.com/", "https://support.hp.com/"),
        "launch_asus_myasus": ("https://www.asus.com/support/", "https://www.asus.com/support/"),
    }
    if action_id in oem_urls:
        uri, fallback_url = oem_urls[action_id]
        subprocess.Popen(["cmd", "/c", "start", "", uri])
        return True, f"Abriendo soporte/actualizador oficial OEM ({fallback_url})."

    return False, f"Accion no reconocida: {action_id}"
