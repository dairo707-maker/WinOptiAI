"""Windows Startup Applications scanner and intelligent reversible optimizer."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import time
from typing import Callable

from ..core.safety_guard import PreOpBackupManager
from ..core.usage_telemetry import get_running_ram_by_exe, lookup_usage_ts, read_windows_app_usage_map
from ..core.win32_bridge import IS_WINDOWS, is_user_admin, run_elevated_command


_CRITICAL_STARTUP_KEYWORDS: tuple[str, ...] = (
    "securityhealth",
    "windows defender",
    "msmpeng",
    "bitdefender",
    "bdagent",
    "seccenter",
    "onedrive",
    "realtek",
    "rtkaud",
    "igfx",
    "intel",
    "nvidia",
    "nvcontainer",
    "amd",
    "synaptics",
    "elan",
    "touchpad",
    "audio",
    "winoptiai",
)

_DEV_ACTIVE_KEYWORDS: tuple[str, ...] = (
    "claude",
    "antigravity",
    "code",
    "cursor",
    "docker",
    "wsl",
    "ollama",
)

_OPTIONAL_HEAVY_KEYWORDS: tuple[str, ...] = (
    "spotify",
    "steam",
    "epicgames",
    "discord",
    "teams",
    "ms-teams",
    "zoom",
    "skype",
    "adobe",
    "ccxprocess",
    "ccleaner",
    "xbox",
    "cortana",
    "overwolf",
    "riotclient",
    "battlenet",
    "edgeupdate",
    "googleupdater",
    "dropbox",
)


@dataclass(slots=True)
class StartupItem:
    """Single Windows startup item with live usage/RAM metrics and smart semaphore guidance."""

    item_id: str
    name: str
    command: str
    location_kind: str   # "HKCU_RUN" | "HKLM_RUN" | "HKCU_RUN32" | "HKLM_RUN32" | "STARTUP_USER" | "STARTUP_COMMON"
    scope: str           # "Usuario" | "Sistema"
    entry_name: str
    enabled: bool = True
    last_used_ts: float = 0.0
    ram_mb: float = 0.0
    publisher: str = ""
    recommendation: str = "PAUSAR"  # "MANTENER" | "PAUSAR" | "DESACTIVAR"
    rec_tone: str = "warn"          # "ok" | "warn" | "risk"
    reason: str = ""
    protected: bool = False


def classify_startup_item(
    name: str,
    command: str,
    last_used_ts: float,
    ram_mb: float,
    publisher: str = "",
    scope: str = "Usuario",
    now: float | None = None,
) -> tuple[str, str, str, bool]:
    """Classify startup item into ('MANTENER'|'PAUSAR'|'DESACTIVAR', tone, reason, protected)."""
    cur = time.time() if now is None else float(now)
    blob = f"{name} {command} {publisher}".lower()

    for kw in _CRITICAL_STARTUP_KEYWORDS:
        if kw in blob:
            return "MANTENER", "ok", "Servicio esencial de seguridad, hardware o nube", True

    age_days = ((cur - last_used_ts) / 86400.0) if last_used_ts > 0.0 else 999.0

    for kw in _DEV_ACTIVE_KEYWORDS:
        if kw in blob and age_days <= 14.0:
            return "MANTENER", "ok", f"Herramienta IA/dev usada recientemente (RAM {ram_mb:.0f} MB)", False

    is_optional_bloat = any(kw in blob for kw in _OPTIONAL_HEAVY_KEYWORDS)

    if last_used_ts <= 0.0:
        if is_optional_bloat or scope == "Usuario":
            return "DESACTIVAR", "risk", "Sin uso reciente registrado; alarga el arranque", False
        return "PAUSAR", "warn", "Sin actividad reciente; pausable si no lo usas a diario", False

    if age_days >= 30.0:
        return "DESACTIVAR", "risk", f"Inactiva hace {int(age_days)} dias; consume arranque sin uso", False

    if is_optional_bloat and (age_days > 7.0 or ram_mb >= 100.0):
        extra = f" · {ram_mb:.0f} MB RAM" if ram_mb > 0 else ""
        return "DESACTIVAR", "risk", f"App opcional de ocio/updater ({int(age_days)}d{extra})", False

    if ram_mb >= 120.0 or age_days > 7.0:
        return "PAUSAR", "warn", f"Uso moderado ({int(age_days)}d, {ram_mb:.0f} MB RAM): abrir bajo demanda", False

    return "MANTENER", "ok", f"Uso frecuente reciente ({ram_mb:.0f} MB RAM)", False


def _approved_subkey_for(location_kind: str) -> tuple[int, str] | None:
    if not IS_WINDOWS:
        return None
    import winreg

    mapping = {
        "HKCU_RUN": (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"),
        "HKCU_RUN32": (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run32"),
        "HKLM_RUN": (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"),
        "HKLM_RUN32": (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run32"),
        "STARTUP_USER": (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"),
        "STARTUP_COMMON": (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"),
    }
    return mapping.get(location_kind)


def _read_approved_map(location_kind: str) -> dict[str, bool]:
    spec = _approved_subkey_for(location_kind)
    if spec is None:
        return {}
    import winreg

    hkey, sub = spec
    out: dict[str, bool] = {}
    try:
        with winreg.OpenKey(hkey, sub) as k:
            idx = 0
            while True:
                try:
                    vname, val, vtype = winreg.EnumValue(k, idx)
                    idx += 1
                except OSError:
                    break
                if vtype == winreg.REG_BINARY and isinstance(val, (bytes, bytearray)) and len(val) >= 1:
                    # Windows Task Manager convention: even first byte (0x02, 0x06) = enabled, odd (0x03, 0x07) = disabled
                    out[str(vname).lower()] = (val[0] % 2 == 0)
    except OSError:
        pass
    return out


def _extract_exe_name(command: str) -> str:
    raw = (command or "").strip().strip('"').strip("'")
    low = raw.lower()
    if ".exe" in low:
        raw = raw[: low.find(".exe") + 4]
    return raw.replace("/", "\\").rsplit("\\", 1)[-1].lower()


def scan_startup_items(progress_cb: Callable[[int, str], None] | None = None) -> list[StartupItem]:
    """Enumerate Run registry keys and Startup folders with BAM usage, RAM footprint, and smart rules."""
    if progress_cb:
        progress_cb(15, "Escaneando entradas de inicio de Windows...")
    if not IS_WINDOWS:
        return []

    import winreg

    usage_map = read_windows_app_usage_map()
    ram_map = get_running_ram_by_exe()
    now = time.time()
    items: list[StartupItem] = []

    reg_sources = [
        ("HKCU_RUN", "Usuario", winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
        ("HKCU_RUN32", "Usuario", winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\WOW6432Node\Run"),
        ("HKLM_RUN", "Sistema", winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run"),
        ("HKLM_RUN32", "Sistema", winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\WOW6432Node\Run"),
    ]

    for loc_kind, scope, hkey, sub in reg_sources:
        approved = _read_approved_map(loc_kind)
        try:
            with winreg.OpenKey(hkey, sub) as k:
                idx = 0
                while True:
                    try:
                        vname, val, _vtype = winreg.EnumValue(k, idx)
                        idx += 1
                    except OSError:
                        break
                    name = str(vname).strip()
                    cmd = str(val or "").strip()
                    if not name or not cmd:
                        continue
                    enabled = approved.get(name.lower(), True)
                    ts = lookup_usage_ts(usage_map, name=name, command=cmd)
                    exe_base = _extract_exe_name(cmd)
                    ram_mb = round(float(ram_map.get(exe_base, ram_map.get(exe_base.removesuffix(".exe"), 0.0))), 1)
                    rec, tone, reason, protected = classify_startup_item(
                        name=name, command=cmd, last_used_ts=ts, ram_mb=ram_mb, scope=scope, now=now
                    )
                    items.append(
                        StartupItem(
                            item_id=f"{loc_kind}:{name}",
                            name=name,
                            command=cmd,
                            location_kind=loc_kind,
                            scope=scope,
                            entry_name=name,
                            enabled=enabled,
                            last_used_ts=ts,
                            ram_mb=ram_mb,
                            recommendation=rec,
                            rec_tone=tone,
                            reason=reason,
                            protected=protected,
                        )
                    )
        except OSError:
            continue

    if progress_cb:
        progress_cb(65, "Inspeccionando carpetas de Inicio...")

    startup_dirs = [
        ("STARTUP_USER", "Usuario", Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"),
        ("STARTUP_COMMON", "Sistema", Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"),
    ]
    for loc_kind, scope, folder in startup_dirs:
        if not folder.exists():
            continue
        approved = _read_approved_map(loc_kind)
        try:
            for entry in folder.iterdir():
                if not entry.is_file() or entry.name.lower() == "desktop.ini":
                    continue
                name = entry.stem
                enabled = approved.get(entry.name.lower(), True)
                cmd = str(entry)
                ts = lookup_usage_ts(usage_map, name=name, command=cmd)
                ram_mb = round(float(ram_map.get(name.lower(), 0.0)), 1)
                rec, tone, reason, protected = classify_startup_item(
                    name=name, command=cmd, last_used_ts=ts, ram_mb=ram_mb, scope=scope, now=now
                )
                items.append(
                    StartupItem(
                        item_id=f"{loc_kind}:{entry.name}",
                        name=name,
                        command=cmd,
                        location_kind=loc_kind,
                        scope=scope,
                        entry_name=entry.name,
                        enabled=enabled,
                        last_used_ts=ts,
                        ram_mb=ram_mb,
                        recommendation=rec,
                        rec_tone=tone,
                        reason=reason,
                        protected=protected,
                    )
                )
        except OSError:
            continue

    order = {"DESACTIVAR": 0, "PAUSAR": 1, "MANTENER": 2}
    items.sort(key=lambda it: (order.get(it.recommendation, 9), 0 if it.enabled else 1, it.name.lower()))
    if progress_cb:
        progress_cb(100, f"{len(items)} entradas de inicio analizadas")
    return items


def _startup_approved_payload(enable: bool, now: float | None = None) -> bytes:
    if enable:
        return b"\x02" + (b"\x00" * 11)
    ts = time.time() if now is None else float(now)
    ft = int((ts * 10_000_000) + 116_444_736_000_000_000)
    return b"\x03\x00\x00\x00" + ft.to_bytes(8, "little", signed=False)


def set_startup_item_enabled(
    item: StartupItem,
    enable: bool,
    backup_mgr: PreOpBackupManager | None = None,
) -> tuple[bool, str]:
    """Reversibly enable or disable a Windows startup entry via StartupApproved registry."""
    if not enable and item.protected:
        return False, f"'{item.name}' esta protegida (seguridad/hardware/nube) y no debe desactivarse."
    spec = _approved_subkey_for(item.location_kind)
    if spec is None:
        return False, "Solo compatible con Windows."

    if backup_mgr is not None:
        backup_mgr.create_operation_snapshot(
            "startup_toggle",
            [
                {
                    "item_id": item.item_id,
                    "name": item.name,
                    "location_kind": item.location_kind,
                    "previous_enabled": item.enabled,
                    "new_enabled": enable,
                }
            ],
        )

    import winreg

    hkey, sub = spec
    payload = _startup_approved_payload(enable)
    action_lbl = "reactivada" if enable else "desactivada"

    try:
        with winreg.CreateKeyEx(hkey, sub, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, item.entry_name, 0, winreg.REG_BINARY, payload)
        item.enabled = enable
        return True, f"'{item.name}' {action_lbl} (100% reversible)."
    except PermissionError:
        if hkey == winreg.HKEY_LOCAL_MACHINE and not is_user_admin():
            hex_str = payload.hex().upper()
            ok = run_elevated_command(
                "reg.exe",
                f'add "HKLM\\{sub}" /v "{item.entry_name}" /t REG_BINARY /d {hex_str} /f',
            )
            if ok:
                item.enabled = enable
                return True, f"'{item.name}' {action_lbl} con permisos de Administrador."
        return False, f"Permiso denegado modificando '{item.name}' (intenta Elevar Admin UAC)."
    except OSError as exc:
        return False, f"Error actualizando inicio de '{item.name}': {exc}"
