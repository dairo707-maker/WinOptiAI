"""User application inventory, winget update checker/upgrader, and safe uninstaller with leftover detection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Callable

from ..core.safety_guard import is_internal_app_path, is_protected_path
from ..core.usage_telemetry import lookup_usage_ts, read_windows_app_usage_map
from ..core.win32_bridge import IS_WINDOWS, is_user_admin, run_elevated_command


_PROTECTED_NAME_KEYWORDS: tuple[str, ...] = (
    "winoptiai",
    "windows defender",
    "microsoft defender",
    "bitdefender",
    "microsoft visual c++",
    "microsoft .net",
    "windows sdk",
    "windows software development",
    "update for windows",
    "security update",
    "realtek",
    "intel(r) graphics",
    "intel(r) management",
    "intel(r) wireless",
    "nvidia graphics driver",
    "amd chipset",
    "onedrive",
)

_PROTECTED_PREFIXES: tuple[str, ...] = (
    "kb",
    "windows driver package",
    "microsoft edge webview2",
)


@dataclass(slots=True)
class InstalledApp:
    """Installed Windows application discovered from Uninstall registry or winget."""

    app_id: str
    name: str
    version: str
    publisher: str = ""
    size_bytes: int = 0
    install_location: str = ""
    uninstall_command: str = ""
    quiet_uninstall: str = ""
    winget_id: str = ""
    available_version: str = ""
    last_used_ts: float = 0.0
    protected_reason: str = ""
    scope: str = "Usuario"  # "Usuario" | "Sistema"
    install_date_ts: float = 0.0


def is_protected_application(name: str, publisher: str = "", install_location: str = "") -> str:
    """Return non-empty reason when an app is critical OS/security/self software that must not be touched."""
    low = (name or "").strip().lower()
    pub = (publisher or "").strip().lower()
    loc = (install_location or "").strip().lower()
    if not low:
        return "Entrada sin nombre"
    if "winoptiai" in low or "trodai" in low:
        return "Aplicacion activa de mantenimiento (WinOptiAI)"
    for kw in _PROTECTED_NAME_KEYWORDS:
        if kw in low:
            return "Componente critico de sistema, seguridad o runtime"
    for pref in _PROTECTED_PREFIXES:
        if low.startswith(pref):
            return "Paquete de actualizacion/runtime del sistema operativo"
    if "bitdefender" in pub:
        return "Software de seguridad/antivirus protegido"
    if loc.startswith(r"c:\windows\system32"):
        return "Ruta interna del sistema Windows"
    return ""


def _extract_icon_dir(display_icon: str) -> str:
    raw = (display_icon or "").strip()
    if not raw:
        return ""
    if "," in raw:
        raw = raw.split(",", 1)[0]
    raw = raw.strip().strip('"').strip("'")
    if not raw:
        return ""
    p = Path(raw)
    if p.suffix.lower() in (".exe", ".ico", ".dll"):
        return str(p.parent)
    return raw


def _parse_install_date(raw: str) -> float:
    clean = (raw or "").strip()
    if len(clean) == 8 and clean.isdigit():
        try:
            return float(datetime.strptime(clean, "%Y%m%d").timestamp())
        except ValueError:
            pass
    return 0.0


def _extract_uninstall_dir(uninstall_cmd: str) -> str:
    raw = (uninstall_cmd or "").strip()
    if not raw or "msiexec" in raw.lower():
        return ""
    m = re.search(r'([A-Za-z]:[^"\r\n*?<>|]*?\.exe)', raw, re.IGNORECASE)
    if not m:
        return ""
    p = Path(m.group(1).strip())
    low_parent = str(p.parent).lower()
    if low_parent.startswith(r"c:\windows\system32") or "package cache" in low_parent:
        return ""
    return str(p.parent)


def list_installed_apps(progress_cb: Callable[[int, str], None] | None = None) -> list[InstalledApp]:
    """Enumerate installed apps from Windows Uninstall registry keys enriched with last-used timestamps."""
    if progress_cb:
        progress_cb(12, "Leyendo registro de aplicaciones instaladas...")
    if not IS_WINDOWS:
        return []

    import winreg

    usage_map = read_windows_app_usage_map()
    uninstall_roots = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", "Usuario"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", "Sistema"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", "Sistema"),
    ]
    seen: dict[str, InstalledApp] = {}

    for hkey, subkey_path, scope in uninstall_roots:
        try:
            root_key = winreg.OpenKey(hkey, subkey_path)
        except OSError:
            continue
        try:
            idx = 0
            while True:
                try:
                    sub_name = winreg.EnumKey(root_key, idx)
                    idx += 1
                except OSError:
                    break
                try:
                    with winreg.OpenKey(root_key, sub_name) as sk:
                        def _val(vname: str, default: object = "") -> object:
                            try:
                                val, _ = winreg.QueryValueEx(sk, vname)
                                return val
                            except OSError:
                                return default

                        sys_comp = _val("SystemComponent", 0)
                        parent_key = str(_val("ParentKeyName", "") or "")
                        release_type = str(_val("ReleaseType", "") or "")
                        if sys_comp == 1 or parent_key or release_type in ("Security Update", "Update Rollup", "Hotfix"):
                            continue

                        name = str(_val("DisplayName", "") or "").strip()
                        uninstall_cmd = str(_val("UninstallString", "") or "").strip()
                        quiet_cmd = str(_val("QuietUninstallString", "") or "").strip()
                        if not name or (not uninstall_cmd and not quiet_cmd):
                            continue

                        version = str(_val("DisplayVersion", "") or "").strip() or "--"
                        publisher = str(_val("Publisher", "") or "").strip()
                        loc = str(_val("InstallLocation", "") or "").strip().strip('"').strip("'")
                        icon_raw = str(_val("DisplayIcon", "") or "").strip()
                        if not loc and icon_raw:
                            loc = _extract_icon_dir(icon_raw)
                        if not loc and uninstall_cmd:
                            loc = _extract_uninstall_dir(uninstall_cmd)
                        est_kb = _val("EstimatedSize", 0)
                        size_bytes = int(est_kb) * 1024 if isinstance(est_kb, int) and est_kb > 0 else 0

                        # Real execution telemetry only (never st_atime, which Defender/indexers touch).
                        ts = lookup_usage_ts(usage_map, name=name, command=icon_raw, install_dir=loc)
                        install_ts = _parse_install_date(str(_val("InstallDate", "") or ""))

                        prot = is_protected_application(name, publisher, loc)
                        norm_k = name.lower()
                        candidate = InstalledApp(
                            app_id=f"{scope}:{sub_name}",
                            name=name,
                            version=version,
                            publisher=publisher,
                            size_bytes=size_bytes,
                            install_location=loc,
                            uninstall_command=uninstall_cmd,
                            quiet_uninstall=quiet_cmd,
                            last_used_ts=ts,
                            protected_reason=prot,
                            scope=scope,
                            install_date_ts=install_ts,
                        )
                        existing = seen.get(norm_k)
                        if existing is None or (candidate.last_used_ts > existing.last_used_ts) or (
                            candidate.last_used_ts == existing.last_used_ts
                            and candidate.install_date_ts > existing.install_date_ts
                        ) or (
                            candidate.size_bytes > existing.size_bytes and existing.size_bytes == 0
                        ):
                            seen[norm_k] = candidate
                except OSError:
                    continue
        finally:
            root_key.Close()

    apps = list(seen.values())
    apps.sort(
        key=lambda a: (
            0 if a.available_version else 1,
            -(a.last_used_ts if a.last_used_ts > 0 else a.install_date_ts),
            a.name.lower(),
        )
    )
    if progress_cb:
        progress_cb(100, f"{len(apps)} aplicaciones detectadas")
    return apps


def is_winget_available() -> bool:
    return shutil.which("winget") is not None or (
        IS_WINDOWS
        and (Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps" / "winget.exe").exists()
    )


def _winget_exe() -> str:
    w = shutil.which("winget")
    if w:
        return w
    cand = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps" / "winget.exe"
    return str(cand) if cand.exists() else "winget"


def parse_winget_upgrade_output(text: str) -> list[dict[str, str]]:
    """Parse ``winget upgrade`` table output cleanly across EN/ES locales and spinner prefixes."""
    lines = [ln.replace("\r", "") for ln in (text or "").splitlines()]
    hdr_idx = -1
    for i, ln in enumerate(lines):
        # Ignore spinner fragments before header
        clean = ln.lstrip(" -\\|/")
        if ("Id" in clean and ("Version" in clean or "Versi" in clean)) and (
            "Available" in clean or "Disponible" in clean or "Dispon" in clean
        ):
            hdr_idx = i
            break
    if hdr_idx < 0:
        return []

    hdr = lines[hdr_idx]
    # Locate column offsets by standard headers
    col_specs: list[tuple[str, int]] = []
    for key, patterns in (
        ("name", ("Name", "Nombre", "Nome")),
        ("id", ("Id",)),
        ("version", ("Version", "Versión", "Version", "Versao", "Versão")),
        ("available", ("Available", "Disponible", "Disponível")),
        ("source", ("Source", "Origen", "Fonte")),
    ):
        for pat in patterns:
            pos = hdr.find(pat)
            if pos >= 0:
                col_specs.append((key, pos))
                break
    col_specs.sort(key=lambda x: x[1])
    if not any(k == "id" for k, _ in col_specs) or not any(k == "available" for k, _ in col_specs):
        return []

    results: list[dict[str, str]] = []
    for ln in lines[hdr_idx + 1 :]:
        s = ln.strip()
        if not s or set(s) <= {"-", "="}:
            continue
        low = s.lower()
        if low.startswith(("0 ", "no installed", "no se encontr")) or "upgrades available" in low or "actualizaciones disponibles" in low:
            if len(results) > 0:
                break
            continue
        if len(ln) < col_specs[-1][1]:
            continue
        row: dict[str, str] = {}
        for c_i, (k, start) in enumerate(col_specs):
            end = col_specs[c_i + 1][1] if c_i + 1 < len(col_specs) else len(ln)
            row[k] = ln[start:end].strip()
        if row.get("id") and row.get("available") and row["available"] != row.get("version", ""):
            results.append(row)
    return results


def _norm_app_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def check_app_updates_winget(
    apps: list[InstalledApp],
    progress_cb: Callable[[int, str], None] | None = None,
    timeout: int = 45,
) -> tuple[list[InstalledApp], int, str]:
    """Query ``winget upgrade`` and annotate InstalledApp objects with available_version + winget_id."""
    if not is_winget_available():
        return apps, 0, "winget no esta disponible en este equipo (solo listado del Registro)."
    if progress_cb:
        progress_cb(25, "Consultando nuevas versiones en winget...")

    try:
        res = subprocess.run(
            [
                _winget_exe(),
                "upgrade",
                "--accept-source-agreements",
                "--disable-interactivity",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        rows = parse_winget_upgrade_output((res.stdout or "") + "\n" + (res.stderr or ""))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return apps, 0, f"No se pudo consultar winget ({exc})."

    if progress_cb:
        progress_cb(80, f"Cruzando {len(rows)} actualizaciones con inventario...")

    by_norm = {_norm_app_key(a.name): a for a in apps if _norm_app_key(a.name)}
    matched = 0
    for row in rows:
        w_name = row.get("name", "")
        w_id = row.get("id", "")
        w_ver = row.get("version", "")
        w_avail = row.get("available", "")
        nk = _norm_app_key(w_name)
        target = by_norm.get(nk)
        if target is None and len(nk) >= 4:
            for k, app in by_norm.items():
                if nk in k or k in nk:
                    target = app
                    break
        if target is not None:
            target.winget_id = w_id
            target.available_version = w_avail
            matched += 1
        else:
            apps.append(
                InstalledApp(
                    app_id=f"winget:{w_id}",
                    name=w_name or w_id,
                    version=w_ver or "--",
                    publisher=w_id.split(".", 1)[0] if "." in w_id else "winget",
                    winget_id=w_id,
                    available_version=w_avail,
                    protected_reason=is_protected_application(w_name),
                    scope="winget",
                )
            )
            matched += 1

    apps.sort(
        key=lambda a: (
            0 if a.available_version else 1,
            -(a.last_used_ts if a.last_used_ts > 0 else a.install_date_ts),
            a.name.lower(),
        )
    )
    if progress_cb:
        progress_cb(100, f"{matched} actualizacion(es) disponible(s)")
    msg = (
        f"Se encontraron {matched} actualizacion(es) disponible(s) via winget."
        if matched
        else "Todas las aplicaciones compatibles estan al dia segun winget."
    )
    return apps, matched, msg


def upgrade_app_winget(
    app: InstalledApp,
    progress_cb: Callable[[int, str], None] | None = None,
    timeout: int = 240,
) -> tuple[bool, str]:
    """Upgrade a single application using ``winget upgrade --id`` silently."""
    if app.protected_reason:
        return False, f"Bloqueada por seguridad: {app.protected_reason}"
    if not is_winget_available():
        return False, "winget no esta disponible en este equipo."

    if progress_cb:
        progress_cb(20, f"Actualizando {app.name} -> {app.available_version or 'ultima'}...")
    cmd = [_winget_exe(), "upgrade"]
    if app.winget_id:
        cmd.extend(["--id", app.winget_id, "--exact"])
    else:
        cmd.extend(["--name", app.name, "--exact"])
    cmd.extend(["--silent", "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity"])

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = (res.stdout or "") + "\n" + (res.stderr or "")
        if res.returncode == 0 or "successfully installed" in out.lower() or "instalado correctamente" in out.lower():
            if progress_cb:
                progress_cb(100, f"{app.name} actualizado")
            return True, f"{app.name} actualizado correctamente ({app.available_version or 'ultima'})."
        snippet = next((ln.strip() for ln in reversed(out.splitlines()) if ln.strip()), "")[:160]
        return False, f"winget devolvio codigo {res.returncode}: {snippet}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Error actualizando {app.name}: {exc}"


# v0.6.3: "Actualizar todas" nunca toca entornos de desarrollo ni saltos de version mayor:
# cambian rutas, paquetes y compatibilidad de proyectos (leccion del incidente del 17/11).
_BULK_SKIP_KEYWORDS: tuple[str, ...] = (
    "anaconda", "miniconda", "python", "rtools", "r for windows", "node.js", "nodejs", "java", "jdk",
    "runtime", ".net", "dotnet", "asp.net", "visual c++", "wsl", "subsistema de windows para linux",
    "machine-wide installer", "php",
)


def _major_version(text: str) -> int | None:
    m = re.search(r"(\d+)", text or "")
    return int(m.group(1)) if m else None


def bulk_upgrade_skip_reason(app: InstalledApp) -> str:
    """Motivo para excluir una app de 'Actualizar todas' ('' = se puede actualizar en lote)."""
    if app.protected_reason:
        return app.protected_reason
    if not app.available_version:
        return "Sin nueva version"
    low = f"{app.name} {app.winget_id}".lower()
    for kw in _BULK_SKIP_KEYWORDS:
        if kw in low:
            return "Entorno o componente de desarrollo: actualizar a mano"
    cur, new = _major_version(app.version), _major_version(app.available_version)
    if cur is not None and new is not None and new > cur and cur < 1000:
        return f"Salto de version mayor ({cur} -> {new}): revisar antes"
    return ""


def upgrade_apps_winget(
    apps: list[InstalledApp],
    progress_cb: Callable[[int, str], None] | None = None,
    controller=None,
    upgrade_fn: Callable[..., tuple[bool, str]] | None = None,
) -> list[tuple[InstalledApp, bool, str]]:
    """Actualizar varias apps una por una (microprocesos): se puede cancelar entre una y otra."""
    from ..core.task_control import TaskCanceledError, stop_point

    fn = upgrade_fn or upgrade_app_winget
    results: list[tuple[InstalledApp, bool, str]] = []
    total = max(1, len(apps))
    for i, app in enumerate(apps):
        try:
            stop_point(controller)
        except TaskCanceledError:
            break
        except Exception:  # noqa: BLE001 - Guardar Pausa no aplica: se trata como cancelar
            break
        if progress_cb:
            progress_cb(int(5 + 90 * i / total), f"({i + 1}/{len(apps)}) Actualizando {app.name}...")
        ok, msg = fn(app)
        if ok:
            app.version = app.available_version or app.version
            app.available_version = ""
        results.append((app, ok, msg))
    if progress_cb:
        ok_n = sum(1 for _a, ok, _m in results if ok)
        progress_cb(100, f"{ok_n}/{len(apps)} actualizadas")
    return results


def uninstall_installed_app(
    app: InstalledApp,
    progress_cb: Callable[[int, str], None] | None = None,
) -> tuple[bool, str]:
    """Uninstall a user application safely via winget or its registered UninstallString."""
    if app.protected_reason:
        return False, f"Protegida: {app.protected_reason}"

    if progress_cb:
        progress_cb(20, f"Iniciando desinstalacion de {app.name}...")

    if app.winget_id and is_winget_available():
        try:
            res = subprocess.run(
                [_winget_exe(), "uninstall", "--id", app.winget_id, "--exact", "--disable-interactivity"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if res.returncode == 0:
                if progress_cb:
                    progress_cb(100, f"{app.name} desinstalado")
                return True, f"{app.name} desinstalado correctamente via winget."
        except (OSError, subprocess.TimeoutExpired):
            pass

    cmd_str = (app.quiet_uninstall or app.uninstall_command or "").strip()
    if not cmd_str:
        return False, f"No hay comando de desinstalacion registrado para {app.name}."

    # Execute MSI or registered uninstaller directly (with UAC prompt if HKLM requires elevation)
    if app.scope == "Sistema" and IS_WINDOWS and not is_user_admin():
        ok = run_elevated_command("cmd.exe", f"/c {cmd_str}")
        if ok:
            return True, f"Desinstalador de '{app.name}' ejecutado con permisos de Administrador."
        return False, f"No se pudo elevar permisos para desinstalar '{app.name}'."

    try:
        res = subprocess.run(
            cmd_str,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        if progress_cb:
            progress_cb(100, f"Desinstalador finalizado ({res.returncode})")
        if res.returncode == 0:
            return True, f"{app.name} desinstalado correctamente."
        if res.returncode == 1602 or res.returncode == 1223:
            return False, f"Desinstalacion de '{app.name}' cancelada por el usuario."
        return False, f"El desinstalador finalizo con codigo {res.returncode}."
    except subprocess.TimeoutExpired:
        return False, f"Tiempo de espera agotado esperando desinstalacion de '{app.name}'."
    except OSError as exc:
        return False, f"Error lanzando desinstalador: {exc}"


def find_app_leftovers(
    app: InstalledApp,
    search_bases: list[Path] | None = None,
) -> list[Path]:
    """Find safe AppData leftover folders belonging specifically to an uninstalled app."""
    tokens: list[str] = []
    for src in (app.name, app.publisher):
        clean = re.sub(r"[^a-z0-9\s]", " ", (src or "").lower()).strip()
        for word in clean.split():
            if len(word) >= 4 and word not in {"microsoft", "windows", "software", "edition", "update", "setup", "corp", "inc", "ltd"}:
                tokens.append(word)
    if not tokens:
        return []

    bases = search_bases
    if bases is None:
        bases = []
        for env_name in ("LOCALAPPDATA", "APPDATA"):
            val = os.environ.get(env_name)
            if val:
                bases.append(Path(val))

    found: list[Path] = []
    for base in bases:
        if not base.exists() or not base.is_dir():
            continue
        try:
            for entry in base.iterdir():
                if not entry.is_dir():
                    continue
                if is_internal_app_path(entry) or is_protected_path(entry):
                    continue
                dlow = re.sub(r"[^a-z0-9]", "", entry.name.lower())
                if any(tok in dlow for tok in tokens):
                    found.append(entry)
        except OSError:
            continue
    return found
