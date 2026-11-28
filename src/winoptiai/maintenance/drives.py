"""v0.6.9: unidades (optimizar segun su tipo), salud del SSD y espacio que ocupa el sistema.

Principios (lo que dice la ingenieria de almacenamiento, no el marketing):
- SSD/NVMe: NO se desfragmenta (desgasta celdas sin beneficio: el acceso no depende de la posicion).
  Lo que mantiene su velocidad es TRIM/ReTrim: avisar al SSD que bloques ya no se usan para que su
  recolector de basura prepare celdas libres. Windows lo hace con ``Optimize-Volume -ReTrim``.
- HDD: la posicion fisica importa (busqueda del cabezal): se analiza y desfragmenta.
- Todo se ejecuta con las herramientas oficiales de Windows y UAC. WinOptiAI no mueve bloques por
  su cuenta.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
import subprocess

from ..core.win32_bridge import IS_WINDOWS, is_user_admin, run_elevated_command

_PS_VOLUMES = r"""
$ErrorActionPreference = 'SilentlyContinue'; $ProgressPreference = 'SilentlyContinue'
$out = @()
foreach ($v in (Get-Volume | Where-Object { $_.DriveLetter -and $_.DriveType -eq 'Fixed' })) {
  $p = Get-Partition -DriveLetter $v.DriveLetter
  $d = $p | Get-Disk
  $pd = Get-PhysicalDisk | Where-Object { $_.DeviceId -eq "$($d.Number)" } | Select-Object -First 1
  $rel = $null
  if ($pd) { $rel = $pd | Get-StorageReliabilityCounter }
  $out += [PSCustomObject]@{
    letter = [string]$v.DriveLetter; label = [string]$v.FileSystemLabel; fs = [string]$v.FileSystemType
    size = [int64]$v.Size; free = [int64]$v.SizeRemaining
    media = [string]$pd.MediaType; bus = [string]$pd.BusType; health = [string]$pd.HealthStatus
    model = [string]$pd.FriendlyName
    wear = $(if ($rel -and $rel.Wear -ne $null) { [int]$rel.Wear } else { -1 })
    temp = $(if ($rel -and $rel.Temperature) { [int]$rel.Temperature } else { -1 })
    hours = $(if ($rel -and $rel.PowerOnHours) { [int64]$rel.PowerOnHours } else { -1 })
  }
}
[Console]::Out.Write((ConvertTo-Json @($out) -Compress -Depth 3))
"""


@dataclass(slots=True)
class VolumeInfo:
    letter: str
    label: str = ""
    fs: str = ""
    size: int = 0
    free: int = 0
    media: str = ""  # "SSD" | "HDD" | "Unspecified"
    bus: str = ""
    health: str = ""
    model: str = ""
    wear_pct: int = -1      # % de vida usada segun el SSD (-1 = no disponible sin admin)
    temp_c: int = -1
    power_on_hours: int = -1

    @property
    def is_ssd(self) -> bool:
        return self.media.upper() == "SSD" or self.bus.upper() == "NVME"

    @property
    def kind_label(self) -> str:
        if self.is_ssd:
            return f"SSD {self.bus}".strip()
        if self.media.upper() == "HDD":
            return f"HDD {self.bus}".strip()
        return self.bus or "Desconocido"

    @property
    def recommended_action(self) -> str:
        return "ReTrim (TRIM)" if self.is_ssd else ("Analizar y desfragmentar" if self.media.upper() == "HDD" else "Optimizar (Windows elige)")

    @property
    def health_label(self) -> str:
        h = (self.health or "").lower()
        return {"healthy": "Sana", "warning": "Advertencia", "unhealthy": "Con fallas"}.get(h, self.health or "--")


def _run_ps(script: str, timeout: float = 60.0) -> str:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return res.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def parse_volumes(raw: str) -> list[VolumeInfo]:
    try:
        data = json.loads((raw or "").strip() or "[]")
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    out: list[VolumeInfo] = []
    for it in data if isinstance(data, list) else []:
        if not isinstance(it, dict) or not it.get("letter"):
            continue
        out.append(
            VolumeInfo(
                letter=str(it["letter"]).strip()[:1].upper(), label=str(it.get("label") or ""),
                fs=str(it.get("fs") or ""), size=int(it.get("size") or 0), free=int(it.get("free") or 0),
                media=str(it.get("media") or ""), bus=str(it.get("bus") or ""), health=str(it.get("health") or ""),
                model=str(it.get("model") or ""), wear_pct=int(it.get("wear", -1)), temp_c=int(it.get("temp", -1)),
                power_on_hours=int(it.get("hours", -1)),
            )
        )
    return sorted(out, key=lambda v: v.letter)


def list_volumes() -> list[VolumeInfo]:
    """Unidades internas con tipo de disco y salud (desgaste/horas solo si la app es administradora)."""
    if not IS_WINDOWS:
        return []
    return parse_volumes(_run_ps(_PS_VOLUMES))


def ssd_health_summary(vol: VolumeInfo) -> str:
    if not vol.is_ssd:
        return f"Disco {vol.kind_label}: estado {vol.health_label}."
    parts = [f"SSD {vol.model or ''}".strip(), f"estado {vol.health_label}"]
    if vol.wear_pct >= 0:
        parts.append(f"vida usada {vol.wear_pct}% (le queda ~{max(0, 100 - vol.wear_pct)}%)")
    if vol.temp_c > 0:
        parts.append(f"{vol.temp_c} C")
    if vol.power_on_hours >= 0:
        parts.append(f"{vol.power_on_hours:,} h encendido".replace(",", "."))
    if vol.wear_pct < 0:
        parts.append("desgaste exacto: usa 'Elevar Admin' (Windows solo lo muestra a administradores)")
    alert = ""
    if (vol.health or "").lower() not in ("", "healthy") or vol.wear_pct >= 80:
        alert = " ALERTA: haz copia de seguridad de tus archivos."
    return ", ".join(parts) + "." + alert


def optimize_volume_elevated(vol: VolumeInfo) -> tuple[bool, str]:
    """Optimiza con la herramienta oficial de Windows en una consola con UAC (visible)."""
    if vol.is_ssd:
        args = f"-NoProfile -Command \"Optimize-Volume -DriveLetter {vol.letter} -ReTrim -Verbose; Write-Host; Pause\""
        what = f"ReTrim de {vol.letter}: (SSD, sin desfragmentar)"
    else:
        args = f"-NoProfile -Command \"Optimize-Volume -DriveLetter {vol.letter} -Analyze -Defrag -Verbose; Write-Host; Pause\""
        what = f"Analisis y desfragmentacion de {vol.letter}: (HDD)"
    ok = run_elevated_command("powershell.exe", args)
    return ok, (f"{what} en curso en una consola de Windows." if ok else "Operacion cancelada (UAC).")


# ------------------------------------------------------------------ espacio del sistema
@dataclass(slots=True)
class SpaceItem:
    key: str
    title: str
    size_bytes: int
    explanation: str
    action_label: str = ""  # "" = solo informativo


def _root_file_size(name: str, drive: str = "C") -> int:
    try:
        for entry in os.scandir(f"{drive}:\\"):
            if entry.name.lower() == name.lower():
                return int(entry.stat(follow_symlinks=False).st_size)
    except OSError:
        pass
    return 0


def system_space_items() -> list[SpaceItem]:
    """Lo que ocupa el sistema en C: y que se puede ajustar (con explicacion honesta)."""
    hib = _root_file_size("hiberfil.sys")
    page = _root_file_size("pagefile.sys")
    items = [
        SpaceItem(
            "winsxs", "Componentes viejos de actualizaciones de Windows (WinSxS)", 0,
            "Windows guarda versiones anteriores de sus componentes tras cada actualizacion. Limpiarlas "
            "libera espacio y no afecta nada (solo impide desinstalar actualizaciones ya instaladas).",
            "Limpiar componentes (UAC)",
        ),
        SpaceItem(
            "restore", "Puntos de restauracion", 0,
            "Limita su espacio al 5 % del disco: Windows borra solo los mas antiguos y conserva los recientes.",
            "Limitar al 5 % (UAC)",
        ),
    ]
    if hib:
        items.insert(0, SpaceItem(
            "hiber_off", "Archivo de hibernacion (hiberfil.sys)", hib,
            "Permite hibernar y el Inicio rapido. Desactivarlo libera este espacio, pero ya no podras "
            "hibernar y el arranque en frio puede tardar unos segundos mas. Se puede reactivar.",
            "Desactivar hibernacion (UAC)",
        ))
    else:
        items.insert(0, SpaceItem(
            "hiber_on", "Hibernacion desactivada", 0,
            "La hibernacion y el Inicio rapido estan apagados. Reactivalos si quieres hibernar.",
            "Reactivar hibernacion (UAC)",
        ))
    if page:
        items.append(SpaceItem(
            "pagefile", "Memoria virtual (pagefile.sys)", page,
            "Windows lo agranda cuando falta RAM (con 16 GB y muchas apps abiertas puede crecer mucho). "
            "No conviene borrarlo: si ya no lo necesita, se reduce solo al reiniciar.",
        ))
    return items


def run_space_action(key: str) -> tuple[bool, str]:
    """Ejecuta la accion de espacio con herramientas oficiales de Windows (consola con UAC)."""
    if key == "winsxs":
        ok = run_elevated_command(
            "powershell.exe",
            '-NoProfile -Command "Dism.exe /Online /Cleanup-Image /StartComponentCleanup; Write-Host; Pause"',
        )
        return ok, ("Limpieza de componentes en curso (puede tardar varios minutos)." if ok else "Operacion cancelada (UAC).")
    if key == "restore":
        ok = run_elevated_command("cmd.exe", "/c vssadmin resize shadowstorage /for=C: /on=C: /maxsize=5% & pause")
        return ok, ("Espacio de puntos de restauracion limitado al 5 %." if ok else "Operacion cancelada (UAC).")
    if key == "hiber_off":
        ok = run_elevated_command("powercfg.exe", "/hibernate off", track=False)
        return ok, ("Hibernacion desactivada: hiberfil.sys se borra en unos segundos." if ok else "Operacion cancelada (UAC).")
    if key == "hiber_on":
        ok = run_elevated_command("powercfg.exe", "/hibernate on", track=False)
        return ok, ("Hibernacion reactivada." if ok else "Operacion cancelada (UAC).")
    return False, "Elemento solo informativo."


def admin_hint() -> str:
    return "" if is_user_admin() else "Algunas lecturas (desgaste del SSD) requieren 'Elevar Admin'."
