"""GitHub Releases self-updater with streaming % progress, SHA-256 check, and detached Shell bridge."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Callable
import urllib.error
import urllib.request

from .. import __version__


GITHUB_OWNER = "dairo707-maker"
GITHUB_REPO = "WinOptiAI"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
REPO_WEB_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
APP_UNINSTALL_GUID = r"{8F9D4A1C-3E2B-49A7-9C5D-7F120A98B31E}_is1"


@dataclass(slots=True)
class ReleaseInfo:
    """Metadata of the latest GitHub Release."""

    tag: str
    version: str
    notes: str
    html_url: str
    setup_url: str | None
    checksums_url: str | None
    update_available: bool


def parse_semver(version_str: str) -> tuple[int, ...]:
    """Parse 'v0.3.1' or '0.3.1' into comparable integer tuple."""
    clean = version_str.strip().lstrip("vV").split("-")[0]
    parts: list[int] = []
    for p in clean.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts or [0])


def _curl_get_bytes(url: str, timeout: int, accept: str | None = None) -> bytes:
    curl_exe = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "curl.exe"
    if not curl_exe.exists():
        raise urllib.error.URLError("curl.exe not found")
    cmd = [
        str(curl_exe),
        "-fsSL",
        "--max-time",
        str(timeout),
        "-A",
        f"WinOptiAI/{__version__}",
    ]
    if accept:
        cmd.extend(["-H", f"Accept: {accept}"])
    cmd.append(url)
    res = subprocess.run(
        cmd,
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if res.returncode != 0:
        err = res.stderr.decode("utf-8", errors="replace").strip()
        raise urllib.error.URLError(err or f"curl exit {res.returncode}")
    return res.stdout


def _http_get_bytes(url: str, timeout: int = 15, accept: str | None = None) -> bytes:
    """Fetch URL bytes via urllib, with native Windows curl.exe fallback for TLS resilience."""
    headers = {"User-Agent": f"WinOptiAI/{__version__}"}
    if accept:
        headers["Accept"] = accept
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, OSError):
        if os.name != "nt":
            raise
        return _curl_get_bytes(url, timeout=timeout, accept=accept)


def _download_file_with_progress(
    url: str,
    dest: Path,
    progress_cb: Callable[[int, str], None] | None = None,
    timeout: int = 90,
) -> None:
    """Stream download to disk reporting 5%..88% progress, with curl.exe fallback."""
    headers = {"User-Agent": f"WinOptiAI/{__version__}"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            with dest.open("wb") as fh:
                while chunk := resp.read(65536):
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        if total > 0:
                            pct = 5 + int((downloaded / total) * 83)
                            mb_done = downloaded / (1024 * 1024)
                            mb_tot = total / (1024 * 1024)
                            progress_cb(pct, f"Descargando {mb_done:.1f} / {mb_tot:.1f} MB ({pct}%)")
                        else:
                            mb_done = downloaded / (1024 * 1024)
                            progress_cb(45, f"Descargando {mb_done:.1f} MB...")
        return
    except (urllib.error.URLError, OSError):
        if os.name != "nt":
            raise
        if progress_cb:
            progress_cb(25, "Descargando instalador via Windows TLS (curl)...")
        data = _curl_get_bytes(url, timeout=timeout)
        dest.write_bytes(data)
        if progress_cb:
            mb_tot = len(data) / (1024 * 1024)
            progress_cb(88, f"Descargado {mb_tot:.1f} MB (100%)")


def check_for_updates(current_version: str = __version__, timeout: int = 10) -> tuple[bool, ReleaseInfo | None, str]:
    """Query GitHub Releases API for newer versions."""
    try:
        raw = _http_get_bytes(
            RELEASES_API_URL,
            timeout=timeout,
            accept="application/vnd.github+json",
        )
        data = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, None, "No hay releases publicados en GitHub todavia."
        return False, None, f"Error HTTP {exc.code} consultando GitHub."
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return False, None, f"No se pudo conectar con GitHub: {exc}"

    tag = str(data.get("tag_name") or "")
    remote_ver = tag.lstrip("vV")
    assets = data.get("assets") or []
    setup_url = None
    checksums_url = None
    for asset in assets:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if name.lower() == "winoptiai-setup.exe":
            setup_url = url
        elif name.lower() == "sha256sums.txt":
            checksums_url = url

    has_update = parse_semver(remote_ver) > parse_semver(current_version)
    info = ReleaseInfo(
        tag=tag,
        version=remote_ver,
        notes=str(data.get("body") or "Sin notas de version.").strip(),
        html_url=str(data.get("html_url") or f"{REPO_WEB_URL}/releases"),
        setup_url=setup_url,
        checksums_url=checksums_url,
        update_available=has_update,
    )
    msg = (
        f"Nueva actualizacion disponible: {tag}"
        if has_update
        else f"No hay actualizacion disponible: ya tienes la version mas reciente (v{current_version})."
    )
    return True, info, msg


def _parse_expected_sha256(checksums_text: str, filename: str) -> str | None:
    for line in checksums_text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[-1].lower() == filename.lower():
            return parts[0].lower()
    return None


def detect_installed_dir() -> Path:
    """Resolve the active WinOptiAI installation folder from registry, frozen exe, or default."""
    if os.name == "nt":
        import winreg

        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for sub in (
                rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_UNINSTALL_GUID}",
                rf"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{APP_UNINSTALL_GUID}",
            ):
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        loc, _ = winreg.QueryValueEx(k, "InstallLocation")
                        if isinstance(loc, str) and loc.strip():
                            return Path(loc.strip())
                except OSError:
                    continue
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Programs" / "WinOptiAI"


def build_detached_update_script(
    setup_path: Path,
    install_dir: Path,
    log_path: Path,
) -> str:
    """Build an independent .cmd bridge script that clears PyInstaller _MEI env vars, installs, and relaunches."""
    exe_path = install_dir / "WinOptiAI.exe"
    bridge_log = log_path.with_name("bridge.log")
    return (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        'set "_MEIPASS="\r\n'
        'set "_MEIPASS2="\r\n'
        'set "_PYI_ARCHIVE_FILE="\r\n'
        'set "_PYI_APPLICATION_HOME_DIR="\r\n'
        'set "_PYI_PARENT_PROCESS_LEVEL="\r\n'
        'set "_PYI_SPLASH_IPC="\r\n'
        f'echo [%DATE% %TIME%] Bridge started > "{bridge_log}"\r\n'
        "ping -n 3 127.0.0.1 >nul\r\n"
        f'taskkill /F /T /IM WinOptiAI.exe >> "{bridge_log}" 2>&1\r\n'
        "ping -n 2 127.0.0.1 >nul\r\n"
        f'"{setup_path}" /SP- /SILENT /CURRENTUSER /CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS '
        f'/DIR="{install_dir}" /LOG="{log_path}"\r\n'
        "set RC=%ERRORLEVEL%\r\n"
        f'echo [%DATE% %TIME%] Setup exit=%RC% >> "{bridge_log}"\r\n'
        "if NOT %RC%==0 (\r\n"
        '    powershell -NoProfile -Command "Add-Type -AssemblyName PresentationFramework; '
        f"[System.Windows.MessageBox]::Show('Error al instalar actualizacion (codigo ' + $env:RC + '). Revise: {bridge_log}', 'WinOptiAI Updater', 'OK', 'Error')\" >nul 2>&1\r\n"
        "    exit /b %RC%\r\n"
        ")\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"
        f'if exist "{exe_path}" (\r\n'
        f'    start "" /D "{install_dir}" "{exe_path}"\r\n'
        ")\r\n"
    )


def _launch_detached_cmd(cmd_script: Path, work_dir: Path) -> bool:
    """Launch bridge script completely detached from parent PyInstaller Job Object via ShellExecuteW."""
    if os.name != "nt":
        return False
    pyi_keys = (
        "_MEIPASS",
        "_MEIPASS2",
        "_PYI_ARCHIVE_FILE",
        "_PYI_APPLICATION_HOME_DIR",
        "_PYI_PARENT_PROCESS_LEVEL",
        "_PYI_SPLASH_IPC",
    )
    saved = {k: os.environ.pop(k) for k in pyi_keys if k in os.environ}
    try:
        # v0.5.9: el puente del actualizador debe sobrevivir al cierre total de procesos de la app.
        from .win32_bridge import shell_open_protected

        if shell_open_protected("cmd.exe", f'/c "{cmd_script}"', str(work_dir), 0):
            return True
        rc = ctypes.windll.shell32.ShellExecuteW(
            None,
            "open",
            "cmd.exe",
            f'/c "{cmd_script}"',
            str(work_dir),
            0,
        )
        return int(rc) > 32
    finally:
        os.environ.update(saved)


def download_and_launch_update(
    info: ReleaseInfo,
    progress_cb: Callable[[int, str], None] | None = None,
) -> tuple[bool, str]:
    """Download WinOptiAI-Setup.exe with % progress, verify SHA-256, and spawn detached updater."""
    if not info.setup_url:
        return False, "El release no contiene WinOptiAI-Setup.exe adjunto."

    dl_dir = Path(tempfile.gettempdir()) / "WinOptiAI-Update"
    dl_dir.mkdir(parents=True, exist_ok=True)
    setup_path = dl_dir / "WinOptiAI-Setup.exe"
    log_path = dl_dir / "install.log"
    bridge_cmd = dl_dir / "apply_update.cmd"

    try:
        if progress_cb:
            progress_cb(3, "Conectando con GitHub Releases...")
        _download_file_with_progress(info.setup_url, setup_path, progress_cb=progress_cb, timeout=120)

        if info.checksums_url:
            if progress_cb:
                progress_cb(91, "Verificando firma SHA-256...")
            sums_text = _http_get_bytes(info.checksums_url, timeout=20).decode("utf-8", errors="replace")
            expected = _parse_expected_sha256(sums_text, "WinOptiAI-Setup.exe")
            if expected:
                actual = hashlib.sha256(setup_path.read_bytes()).hexdigest().lower()
                if actual != expected:
                    setup_path.unlink(missing_ok=True)
                    return False, "Error de integridad SHA-256 en el instalador descargado."

        if os.name != "nt":
            return False, "Actualizacion solo soportada en Windows."

        if progress_cb:
            progress_cb(96, "Iniciando proceso puente de instalacion independiente...")
        install_dir = detect_installed_dir()
        bridge_cmd.write_text(
            build_detached_update_script(setup_path, install_dir, log_path),
            encoding="utf-8",
        )
        if not _launch_detached_cmd(bridge_cmd, dl_dir):
            return False, "No se pudo iniciar el proceso puente de actualizacion."

        if progress_cb:
            progress_cb(100, "Instalador lanzado en proceso separado. Reiniciando...")
        return True, "Actualizador independiente iniciado. WinOptiAI se cerrara y reabrira actualizado."
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return False, f"Fallo al descargar la actualizacion: {exc}"
