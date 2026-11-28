"""v0.6.9: limpieza del Registro SOLO de entradas rotas (decision del propietario 28/11/2026).

Una entrada se considera rota unicamente si apunta a un programa/archivo que NO existe en un disco
interno (fijo). Nunca se tocan: rutas de red o de unidades extraibles (podrian estar desconectadas),
entradas de Windows Installer (MSI), componentes del sistema, ni nada que no sea de estas 4 listas:

1. Desinstaladores de apps ya borradas (Uninstall: el desinstalador y la carpeta no existen).
2. Rutas de programas (App Paths) cuyo .exe ya no existe.
3. Inicio automatico (Run) que apunta a un .exe inexistente.
4. "Abrir con" de programas borrados (Software\\Classes\\Applications\\<exe>).

Antes de borrar se exporta cada clave a un .reg (``reg export``) en
``%LOCALAPPDATA%\\WinOptiAI\\registry_backups\\<fecha>`` y se puede restaurar con ``reg import``.
Las entradas de HKEY_LOCAL_MACHINE requieren permisos de administrador (UAC).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess

from ..core.win32_bridge import IS_WINDOWS

_HIVES = {"HKCU": "HKEY_CURRENT_USER", "HKLM": "HKEY_LOCAL_MACHINE"}
_DRIVE_FIXED = 3


@dataclass(slots=True)
class BrokenEntry:
    category: str          # "uninstall" | "app_path" | "run" | "open_with"
    hive: str              # "HKCU" | "HKLM"
    key: str               # ruta sin la colmena, p. ej. Software\\...\\Uninstall\\X
    value: str = ""        # nombre del valor (solo Run); "" = se borra la clave completa
    name: str = ""         # nombre legible
    target: str = ""       # ruta que ya no existe

    @property
    def needs_admin(self) -> bool:
        return self.hive == "HKLM"

    @property
    def full_key(self) -> str:
        return f"{_HIVES[self.hive]}\\{self.key}"

    @property
    def category_label(self) -> str:
        return {
            "uninstall": "Desinstalador de app borrada",
            "app_path": "Ruta de programa inexistente",
            "run": "Inicio automatico roto",
            "open_with": "'Abrir con' de programa borrado",
        }.get(self.category, self.category)


def _fixed_drive(path: str) -> bool:
    if len(path) < 3 or path[1] != ":" or not path[0].isalpha():
        return False
    if not IS_WINDOWS:
        return True
    try:
        import ctypes

        return ctypes.windll.kernel32.GetDriveTypeW(f"{path[0]}:\\") == _DRIVE_FIXED
    except (OSError, AttributeError):
        return False


_EXE_RE = re.compile(r'^\s*"([^"]+\.(?:exe|com|bat|cmd))"|^\s*([^\s"]+\.(?:exe|com|bat|cmd))\b', re.IGNORECASE)


def extract_command_path(command: str) -> str:
    """Ruta del ejecutable de un comando del Registro ('' si no se puede determinar con seguridad)."""
    cmd = os.path.expandvars((command or "").strip())
    if not cmd:
        return ""
    m = _EXE_RE.match(cmd)
    if m:
        return (m.group(1) or m.group(2) or "").strip()
    # Ruta sin comillas con espacios: tomar hasta el primer .exe
    m2 = re.match(r"^\s*([A-Za-z]:\\.+?\.(?:exe|com))(?:\s|$)", cmd, re.IGNORECASE)
    return m2.group(1).strip() if m2 else ""


def path_is_missing(path: str) -> bool:
    """True solo si la ruta es de un disco interno (fijo), su unidad existe y el archivo no."""
    p = (path or "").strip().strip('"')
    if not p or p.startswith(("\\\\", "//")) or not _fixed_drive(p):
        return False
    if not os.path.exists(f"{p[0]}:\\"):
        return False
    base = os.path.basename(p).lower()
    # Comandos del sistema que se resuelven por PATH (rundll32, msiexec...) nunca son "rotos".
    if base in {"rundll32.exe", "msiexec.exe", "cmd.exe", "powershell.exe", "regsvr32.exe", "explorer.exe"}:
        return False
    return not os.path.exists(p)


# ------------------------------------------------------------------ lectura del Registro
def _open(hive: str, key: str):
    import winreg

    root = winreg.HKEY_CURRENT_USER if hive == "HKCU" else winreg.HKEY_LOCAL_MACHINE
    return winreg.OpenKey(root, key, 0, winreg.KEY_READ)


def _subkeys(hive: str, key: str) -> list[str]:
    import winreg

    out: list[str] = []
    try:
        with _open(hive, key) as k:
            i = 0
            while True:
                try:
                    out.append(winreg.EnumKey(k, i))
                    i += 1
                except OSError:
                    break
    except OSError:
        pass
    return out


def _values(hive: str, key: str) -> dict[str, object]:
    import winreg

    out: dict[str, object] = {}
    try:
        with _open(hive, key) as k:
            i = 0
            while True:
                try:
                    name, val, _t = winreg.EnumValue(k, i)
                    out[name] = val
                    i += 1
                except OSError:
                    break
    except OSError:
        pass
    return out


_UNINSTALL_ROOTS = (
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKLM", r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
)
_APP_PATH_ROOTS = (
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
    ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
)
_RUN_ROOTS = (
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    ("HKLM", r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
)


def _scan_uninstall(out: list[BrokenEntry]) -> None:
    for hive, root in _UNINSTALL_ROOTS:
        for sub in _subkeys(hive, root):
            vals = _values(hive, f"{root}\\{sub}")
            name = str(vals.get("DisplayName") or "").strip()
            if not name or vals.get("SystemComponent") == 1 or vals.get("WindowsInstaller") == 1:
                continue
            if re.fullmatch(r"\{[0-9A-Fa-f-]{36}\}", sub):  # producto MSI
                continue
            cmd = str(vals.get("QuietUninstallString") or vals.get("UninstallString") or "")
            if "msiexec" in cmd.lower():
                continue
            exe = extract_command_path(cmd)
            loc = str(vals.get("InstallLocation") or "").strip().strip('"')
            if not exe or not path_is_missing(exe):
                continue
            if loc and not path_is_missing(loc.rstrip("\\/")):
                continue  # la carpeta de la app sigue ahi: no es seguro
            out.append(BrokenEntry("uninstall", hive, f"{root}\\{sub}", name=name, target=exe))


def _scan_app_paths(out: list[BrokenEntry]) -> None:
    for hive, root in _APP_PATH_ROOTS:
        for sub in _subkeys(hive, root):
            vals = _values(hive, f"{root}\\{sub}")
            raw = os.path.expandvars(str(vals.get("") or "").strip())
            # Algunos programas guardan parametros junto al .exe ("appinstall.exe -tvsu")
            exe = raw.strip('"') if raw.strip('"').lower().endswith((".exe", ".com")) else extract_command_path(raw)
            if exe and path_is_missing(exe):
                out.append(BrokenEntry("app_path", hive, f"{root}\\{sub}", name=sub, target=exe))


def _scan_run(out: list[BrokenEntry]) -> None:
    for hive, root in _RUN_ROOTS:
        for name, val in _values(hive, root).items():
            exe = extract_command_path(str(val or ""))
            if exe and path_is_missing(exe):
                out.append(BrokenEntry("run", hive, root, value=name, name=name, target=exe))


def _scan_open_with(out: list[BrokenEntry]) -> None:
    root = r"Software\Classes\Applications"
    for sub in _subkeys("HKCU", root):
        cmd_vals = _values("HKCU", f"{root}\\{sub}\\shell\\open\\command")
        exe = extract_command_path(str(cmd_vals.get("") or ""))
        if exe and path_is_missing(exe):
            out.append(BrokenEntry("open_with", "HKCU", f"{root}\\{sub}", name=sub, target=exe))


def scan_broken_registry_entries() -> list[BrokenEntry]:
    """Busca entradas rotas (solo lectura, sin UAC)."""
    if not IS_WINDOWS:
        return []
    out: list[BrokenEntry] = []
    for fn in (_scan_uninstall, _scan_app_paths, _scan_run, _scan_open_with):
        try:
            fn(out)
        except Exception:  # noqa: BLE001 - una categoria con error no detiene las demas
            continue
    return out


# ------------------------------------------------------------------ respaldo, borrado y restauracion
def backups_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WinOptiAI" / "registry_backups"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _reg(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["reg.exe", *args], capture_output=True, text=True, errors="replace", timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def backup_entries(entries: list[BrokenEntry]) -> Path:
    """Exporta cada clave a .reg y guarda un manifiesto. Devuelve la carpeta del respaldo."""
    folder = backups_root() / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, e in enumerate(entries):
        reg_file = folder / f"{i:03d}_{e.category}.reg"
        res = _reg("export", e.full_key, str(reg_file), "/y")
        manifest.append({**asdict(e), "file": reg_file.name, "exported": res.returncode == 0})
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return folder


def _delete_args(e: BrokenEntry) -> list[str]:
    if e.value:
        return ["delete", e.full_key, "/v", e.value, "/f"]
    return ["delete", e.full_key, "/f"]


def clean_entries(entries: list[BrokenEntry], subtask_cb=None) -> tuple[list[BrokenEntry], list[BrokenEntry], Path]:
    """Respalda y borra las entradas de HKCU. Devuelve (borradas, pendientes_admin, carpeta_respaldo).

    Las de HKLM se devuelven aparte: la UI las borra con UAC (``clean_admin_entries_elevated``).
    Una entrada sin respaldo exportado nunca se borra.
    """
    folder = backup_entries(entries)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    exported = {(m["hive"], m["key"], m["value"]) for m in manifest if m.get("exported")}
    done: list[BrokenEntry] = []
    admin: list[BrokenEntry] = []
    for e in entries:
        sub_key = f"{e.hive}:{e.key}:{e.value}"
        if subtask_cb:
            subtask_cb(sub_key, label=f"{e.category_label}: {e.name}", state="running", pct=40)
        if (e.hive, e.key, e.value) not in exported:
            if subtask_cb:
                subtask_cb(sub_key, state="skipped", detail="Sin respaldo: no se toca")
            continue
        if e.needs_admin:
            admin.append(e)
            if subtask_cb:
                subtask_cb(sub_key, state="pending", detail="Requiere administrador (UAC)")
            continue
        res = _reg(*_delete_args(e))
        if res.returncode == 0:
            done.append(e)
        if subtask_cb:
            subtask_cb(sub_key, state="ok" if res.returncode == 0 else "error",
                       detail="Borrada (respaldo guardado)" if res.returncode == 0 else (res.stderr or "").strip()[:120])
    return done, admin, folder


def elevated_delete_command(entries: list[BrokenEntry]) -> str:
    """Argumentos de ``cmd /c`` para borrar entradas de HKLM en una sola consola elevada."""
    parts = []
    for e in entries:
        args = _delete_args(e)
        quoted = " ".join(f'"{a}"' if (" " in a or "\\" in a) else a for a in args)
        parts.append(f"reg {quoted}")
    return "/c " + " & ".join(parts)


def list_backups() -> list[Path]:
    root = backups_root()
    return sorted((p for p in root.iterdir() if (p / "manifest.json").exists()), reverse=True)


def restore_backup(folder: Path) -> tuple[int, int, list[str]]:
    """Reimporta los .reg de HKCU. Devuelve (restauradas, fallidas, archivos_hklm_para_uac)."""
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    ok = fail = 0
    hklm_files: list[str] = []
    for m in manifest:
        if not m.get("exported"):
            continue
        reg_file = folder / m["file"]
        if m["hive"] == "HKLM":
            hklm_files.append(str(reg_file))
            continue
        res = _reg("import", str(reg_file))
        if res.returncode == 0:
            ok += 1
        else:
            fail += 1
    return ok, fail, hklm_files
