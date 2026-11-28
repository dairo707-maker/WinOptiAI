"""v0.6.9: apps en segundo plano que se pueden cerrar (como el administrador de Android).

Se listan solo programas del usuario SIN ninguna ventana visible que gastan memoria o CPU. Nunca
aparecen procesos del sistema, de seguridad, instaladores, agentes de IA/IDE ni WinOptiAI. Cerrar
es manual: primero se pide cierre normal (terminate) y solo si no responde se fuerza (kill).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import getpass
import os
import time

import psutil

from ..core.safety_guard import PROTECTED_PROCESS_NAMES
from .process_manager import AI_FOREGROUND_AGENTS, is_installer_process_name

MIN_RAM_MB = 40.0
MIN_CPU_PCT = 2.0

# Procesos de Windows que corren como el usuario pero son parte del escritorio.
_DESKTOP_SHELL_NAMES: frozenset[str] = frozenset(
    {
        "explorer.exe", "sihost.exe", "ctfmon.exe", "taskhostw.exe", "runtimebroker.exe",
        "searchhost.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe", "textinputhost.exe",
        "dllhost.exe", "conhost.exe", "openconsole.exe", "windowsterminal.exe", "widgets.exe",
        "widgetservice.exe", "smartscreen.exe", "securityhealthsystray.exe", "applicationframehost.exe",
        "systemsettings.exe", "lockapp.exe", "fontdrvhost.exe", "dwm.exe", "audiodg.exe",
        "crossdeviceresume.exe", "phoneexperiencehost.exe", "useroobebroker.exe", "backgroundtaskhost.exe",
        "msedgewebview2.exe", "nissrv.exe", "msmpeng.exe", "mpdefendercoreservice.exe",
        "winoptiai.exe", "winoptiai-portable.exe", "python.exe", "pythonw.exe",
    }
)
_SECURITY_MARKERS = ("bitdefender", "bdservice", "bdagent", "vsserv", "avast", "avg", "kaspersky", "eset",
                     "norton", "mcafee", "defender", "malwarebytes", "sophos")


# Avisos para apps cuyo cierre tiene efectos que la persona debe conocer.
_CAUTION_NOTES: dict[str, str] = {
    "onedrive": "Detiene la sincronizacion de OneDrive hasta que se vuelva a abrir.",
    "whatsapp": "Dejaras de recibir notificaciones de WhatsApp hasta abrirlo.",
    "teams": "Dejaras de recibir llamadas y chats de Teams hasta abrirlo.",
    "dropbox": "Detiene la sincronizacion de Dropbox.",
    "googledrive": "Detiene la sincronizacion de Google Drive.",
}


def caution_note(name: str) -> str:
    low = (name or "").lower().replace(" ", "")
    for key, note in _CAUTION_NOTES.items():
        if key in low:
            return note
    return "Sin ventana abierta: se puede cerrar sin perder trabajo."


@dataclass(slots=True)
class BackgroundApp:
    name: str  # nombre del ejecutable (clave de grupo)
    display: str
    exe: str = ""
    pids: list[int] = field(default_factory=list)
    ram_mb: float = 0.0
    cpu_pct: float = 0.0
    started_ts: float = 0.0


def _current_user() -> str:
    try:
        return getpass.getuser().lower()
    except Exception:  # noqa: BLE001
        return ""


def _is_excluded(name: str, exe: str) -> bool:
    low = (name or "").lower()
    exe_low = (exe or "").lower()
    if not low or low in PROTECTED_PROCESS_NAMES or low in AI_FOREGROUND_AGENTS or low in _DESKTOP_SHELL_NAMES:
        return True
    if is_installer_process_name(low):
        return True
    if any(m in low or m in exe_low for m in _SECURITY_MARKERS):
        return True
    windir = os.environ.get("WINDIR", r"C:\Windows").lower()
    return bool(exe_low) and exe_low.startswith(windir)


def list_closable_background_apps(
    visible_pids: set[int] | None = None,
    min_ram_mb: float = MIN_RAM_MB,
    min_cpu_pct: float = MIN_CPU_PCT,
    sample_s: float = 0.4,
) -> list[BackgroundApp]:
    """Programas del usuario sin ventana visible que consumen recursos, agrupados por ejecutable."""
    if visible_pids is None:
        from ..core.usage_telemetry import visible_window_pids

        visible_pids = visible_window_pids()
    me = _current_user()
    self_pid = os.getpid()
    groups: dict[str, BackgroundApp] = {}
    with_window: set[str] = set()
    procs: list[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "name", "exe", "username", "memory_info", "create_time"]):
        try:
            info = proc.info
            pid = int(info["pid"])
            name = (info.get("name") or "").strip()
            low = name.lower()
            if pid <= 4 or pid == self_pid:
                continue
            user = (info.get("username") or "").lower()
            if not user or (me and not user.endswith("\\" + me) and user != me):
                continue
            exe = info.get("exe") or ""
            if _is_excluded(low, exe):
                continue
            if pid in visible_pids:
                with_window.add(low)
                continue
            mem = info.get("memory_info")
            ram = (mem.rss if mem else 0) / (1024 * 1024)
            grp = groups.get(low)
            if grp is None:
                grp = groups[low] = BackgroundApp(name=low, display=name, exe=exe,
                                                  started_ts=float(info.get("create_time") or 0.0))
            grp.pids.append(pid)
            grp.ram_mb += ram
            procs.append(proc)
            proc.cpu_percent(None)  # primera lectura (base)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    if sample_s > 0 and procs:
        time.sleep(sample_s)
    for proc in procs:
        try:
            low = proc.name().lower()
            if low in groups:
                groups[low].cpu_pct += proc.cpu_percent(None) / max(1, psutil.cpu_count() or 1)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    out = [
        g for k, g in groups.items()
        if k not in with_window and (g.ram_mb >= min_ram_mb or g.cpu_pct >= min_cpu_pct)
    ]
    # Nombre legible (descripcion del .exe) para que la persona reconozca la app
    try:
        from ..apps.app_manager import exe_version_info

        for g in out:
            desc = exe_version_info(g.exe).get("description", "") if g.exe else ""
            if desc and desc.lower() not in g.name:
                g.display = f"{desc} ({g.display})"
    except Exception:  # noqa: BLE001
        pass
    out.sort(key=lambda g: (-g.ram_mb, -g.cpu_pct))
    return out


def close_background_app(app: BackgroundApp, grace_s: float = 3.0) -> tuple[bool, str]:
    """Cierra todos los procesos del grupo: cierre normal y, si no responde, forzado."""
    alive: list[psutil.Process] = []
    for pid in app.pids:
        try:
            proc = psutil.Process(pid)
            name = proc.name()
            if _is_excluded(name.lower(), proc.exe() if proc.pid else ""):
                continue
            proc.terminate()
            alive.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if not alive:
        return False, f"{app.display}: ya estaba cerrada o no se puede cerrar."
    _gone, still = psutil.wait_procs(alive, timeout=grace_s)
    for proc in still:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    freed = app.ram_mb
    return True, f"{app.display} cerrada ({len(alive)} proceso(s), ~{freed:.0f} MB liberados)."
