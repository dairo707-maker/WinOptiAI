"""Windows Startup Applications scanner and intelligent reversible optimizer."""

from __future__ import annotations

from dataclasses import dataclass
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Callable

import psutil

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

    if progress_cb:
        progress_cb(75, "Consultando tareas programadas de inicio...")
    items.extend(scan_scheduled_logon_tasks(usage_map=usage_map, ram_map=ram_map, now=now))

    if progress_cb:
        progress_cb(90, "Consultando servicios automaticos de terceros...")
    items.extend(scan_third_party_services(usage_map=usage_map, ram_map=ram_map, now=now))

    order = {"DESACTIVAR": 0, "PAUSAR": 1, "MANTENER": 2}
    items.sort(key=lambda it: (order.get(it.recommendation, 9), 0 if it.enabled else 1, it.name.lower()))
    if progress_cb:
        progress_cb(100, f"{len(items)} entradas de inicio analizadas")
    return items


def read_last_boot_summary() -> dict[str, object]:
    """Return system uptime and real Windows EventID 100 boot duration when elevated."""
    now = time.time()
    try:
        boot_ts = float(psutil.boot_time())
    except Exception:  # noqa: BLE001
        boot_ts = 0.0
    uptime_s = max(0.0, now - boot_ts) if boot_ts > 0 else 0.0
    days, rem = divmod(int(uptime_s), 86400)
    hours, mins = divmod(rem // 60, 60)
    uptime_lbl = f"{days}d {hours}h {mins:02d}m" if days > 0 else f"{hours}h {mins:02d}m"
    out: dict[str, object] = {
        "uptime_sec": round(uptime_s, 1),
        "uptime_label": uptime_lbl,
        "boot_ms": None,
        "boot_label": "",
        "requires_admin": True,
    }
    if not IS_WINDOWS or not is_user_admin():
        return out
    out["requires_admin"] = False
    try:
        ps = (
            "$e = Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-Diagnostics-Performance/Operational'; ID=100} "
            "-MaxEvents 1 -EA SilentlyContinue; "
            "if ($e) { $x = [xml]$e.ToXml(); "
            "$bt = ($x.Event.EventData.Data | Where-Object { $_.Name -eq 'BootTime' }).'#text'; "
            "if ($bt) { Write-Output $bt } }"
        )
        res = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw = (res.stdout or "").strip()
        if raw.isdigit():
            ms = int(raw)
            out["boot_ms"] = ms
            out["boot_label"] = f"{ms / 1000.0:.1f} s"
    except Exception:  # noqa: BLE001
        pass
    return out


_LOGON_TRIGGERS = ("al iniciar", "at logon", "at startup", "iniciar sesion", "na inicializacao", "ao fazer logon")


def parse_schtasks_logon_csv(
    csv_text: str,
    *,
    usage_map: dict[str, float] | None = None,
    ram_map: dict[str, float] | None = None,
    now: float | None = None,
) -> list[StartupItem]:
    """Parse localized ``schtasks /query /fo CSV /v`` output for non-Microsoft startup/logon tasks."""
    if not (csv_text or "").strip():
        return []
    cur = time.time() if now is None else float(now)
    umap = usage_map or {}
    rmap = ram_map or {}
    out: list[StartupItem] = []
    seen: set[str] = set()
    reader = csv.reader(io.StringIO(csv_text))
    headers = next(reader, None)
    if not headers or len(headers) < 9:
        return []

    norm = [h.strip().lower() for h in headers]

    def _idx(candidates: tuple[str, ...], fallback: int) -> int:
        for i, h in enumerate(norm):
            if any(c in h for c in candidates):
                return i
        return fallback

    i_name = _idx(("nombre de tarea", "taskname", "nome da tarefa"), 1)
    i_status = _idx(("estado", "status"), 3)
    i_cmd = _idx(("tarea que se ejecutara", "task to run", "tarefa a ser executada"), 8)
    i_author = _idx(("autor", "author"), 7)
    i_sched = _idx(("tipo de programacion", "schedule type", "tipo de agendamento"), 17 if len(headers) > 17 else len(headers) - 1)

    for row in reader:
        if not row or len(row) <= max(i_name, i_status, i_cmd):
            continue
        task_path = row[i_name].strip()
        if not task_path.startswith("\\") or task_path.lower().startswith("\\microsoft\\"):
            continue
        if task_path.lower() in seen:
            continue
        sched = row[i_sched].strip().lower() if i_sched < len(row) else ""
        if not any(t in sched for t in _LOGON_TRIGGERS):
            continue
        seen.add(task_path.lower())
        short_name = task_path.rsplit("\\", 1)[-1]
        cmd = row[i_cmd].strip()
        author = row[i_author].strip() if i_author < len(row) else ""
        st_low = row[i_status].strip().lower()
        enabled = not any(w in st_low for w in ("deshabilit", "disabled", "desativ"))
        ts = lookup_usage_ts(umap, name=short_name, command=cmd)
        exe_base = _extract_exe_name(cmd)
        ram_mb = round(float(rmap.get(exe_base, rmap.get(exe_base.removesuffix(".exe"), 0.0))), 1)
        rec, tone, reason, protected = classify_startup_item(
            name=short_name, command=cmd, last_used_ts=ts, ram_mb=ram_mb, scope="Tarea prog.", publisher=author, now=cur
        )
        out.append(
            StartupItem(
                item_id=f"SCHTASK:{task_path}",
                name=short_name,
                command=cmd,
                location_kind="SCHTASK",
                scope="Tarea",
                entry_name=task_path,
                enabled=enabled,
                last_used_ts=ts,
                ram_mb=ram_mb,
                publisher=author,
                recommendation=rec,
                rec_tone=tone,
                reason=reason,
                protected=protected,
            )
        )
    return out


def scan_scheduled_logon_tasks(
    *,
    usage_map: dict[str, float] | None = None,
    ram_map: dict[str, float] | None = None,
    now: float | None = None,
) -> list[StartupItem]:
    """Query non-Microsoft startup/logon scheduled tasks via schtasks CSV."""
    if not IS_WINDOWS:
        return []
    try:
        res = subprocess.run(
            ["schtasks.exe", "/query", "/fo", "CSV", "/v"],
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw = ""
        for enc in ("utf-8", "cp850", "cp1252"):
            try:
                raw = res.stdout.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if not raw:
            raw = res.stdout.decode("utf-8", errors="replace")
        return parse_schtasks_logon_csv(raw, usage_map=usage_map, ram_map=ram_map, now=now)
    except Exception:  # noqa: BLE001
        return []


def classify_third_party_services(
    rows: list[dict],
    *,
    usage_map: dict[str, float] | None = None,
    ram_map: dict[str, float] | None = None,
    now: float | None = None,
) -> list[StartupItem]:
    """Convert Win32_Service rows into StartupItem list, filtering core Windows services out."""
    cur = time.time() if now is None else float(now)
    umap = usage_map or {}
    rmap = ram_map or {}
    out: list[StartupItem] = []
    for row in rows:
        svc_name = str(row.get("Name") or "").strip()
        disp = str(row.get("DisplayName") or svc_name).strip()
        path_cmd = str(row.get("PathName") or "").strip()
        start_mode = str(row.get("StartMode") or "").strip().lower()
        if not svc_name or not path_cmd:
            continue
        low_path = path_cmd.lower()
        if "svchost.exe" in low_path or "\\windows\\system32\\" in low_path or "\\windows\\servicing\\" in low_path:
            continue
        if start_mode not in ("auto", "manual"):
            continue
        enabled = start_mode == "auto"
        ts = lookup_usage_ts(umap, name=disp, command=path_cmd)
        exe_base = _extract_exe_name(path_cmd)
        ram_mb = round(float(rmap.get(exe_base, rmap.get(exe_base.removesuffix(".exe"), 0.0))), 1)
        rec, tone, reason, protected = classify_startup_item(
            name=disp, command=path_cmd, last_used_ts=ts, ram_mb=ram_mb, scope="Servicio", now=cur
        )
        out.append(
            StartupItem(
                item_id=f"SERVICE:{svc_name}",
                name=disp,
                command=path_cmd,
                location_kind="SERVICE",
                scope="Servicio",
                entry_name=svc_name,
                enabled=enabled,
                last_used_ts=ts,
                ram_mb=ram_mb,
                recommendation=rec,
                rec_tone=tone,
                reason=reason,
                protected=protected,
            )
        )
    return out


def scan_third_party_services(
    *,
    usage_map: dict[str, float] | None = None,
    ram_map: dict[str, float] | None = None,
    now: float | None = None,
) -> list[StartupItem]:
    """List third-party auto/demand Windows services outside System32/svchost."""
    if not IS_WINDOWS:
        return []
    try:
        ps = (
            "Get-CimInstance Win32_Service -EA SilentlyContinue | "
            "Where-Object { $_.StartMode -in 'Auto','Manual' -and $_.PathName -notlike '*svchost.exe*' "
            "-and $_.PathName -notlike '*\\Windows\\System32\\*' } | "
            "Select-Object Name, DisplayName, PathName, StartMode | ConvertTo-Json -Compress"
        )
        res = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        txt = (res.stdout or "").strip()
        if not txt:
            return []
        parsed = json.loads(txt)
        rows = parsed if isinstance(parsed, list) else [parsed]
        return classify_third_party_services(rows, usage_map=usage_map, ram_map=ram_map, now=now)
    except Exception:  # noqa: BLE001
        return []


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
    """Reversibly enable or disable a Windows startup entry via StartupApproved, schtasks, or sc.exe."""
    if not enable and item.protected:
        return False, f"'{item.name}' esta protegida (seguridad/hardware/nube) y no debe desactivarse."

    if item.location_kind in ("SCHTASK", "SERVICE"):
        if not IS_WINDOWS:
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
        action_lbl = "reactivada" if enable else "pausada"
        if item.location_kind == "SCHTASK":
            flag = "/enable" if enable else "/disable"
            res = subprocess.run(
                ["schtasks.exe", "/change", "/tn", item.entry_name, flag],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if res.returncode == 0:
                item.enabled = enable
                return True, f"Tarea '{item.name}' {action_lbl} (100% reversible)."
            if not is_user_admin() and run_elevated_command("schtasks.exe", f'/change /tn "{item.entry_name}" {flag}'):
                item.enabled = enable
                return True, f"Tarea '{item.name}' {action_lbl} con permisos de Administrador."
            return False, f"No se pudo cambiar la tarea '{item.name}' (intenta Elevar Admin UAC)."

        mode_str = "auto" if enable else "demand"
        res = subprocess.run(
            ["sc.exe", "config", item.entry_name, f"start= {mode_str}"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if res.returncode == 0:
            item.enabled = enable
            return True, f"Servicio '{item.name}' configurado en '{mode_str}' (100% reversible)."
        if not is_user_admin() and run_elevated_command("sc.exe", f'config "{item.entry_name}" start= {mode_str}'):
            item.enabled = enable
            return True, f"Servicio '{item.name}' configurado en '{mode_str}' (Admin UAC)."
        return False, f"Permiso denegado modificando servicio '{item.name}' (requiere Admin UAC)."

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
