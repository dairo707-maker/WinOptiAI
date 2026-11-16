"""GitHub Releases self-updater with SemVer comparison, native curl fallback, and SHA-256 check."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.error
import urllib.request

from .. import __version__


GITHUB_OWNER = "dairo707-maker"
GITHUB_REPO = "WinOptiAI"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
REPO_WEB_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"


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
    """Parse 'v0.2.1' or '0.2.1' into comparable integer tuple."""
    clean = version_str.strip().lstrip("vV").split("-")[0]
    parts: list[int] = []
    for p in clean.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts or [0])


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
        curl_exe = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "curl.exe"
        if not curl_exe.exists():
            raise
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


def download_and_launch_update(info: ReleaseInfo) -> tuple[bool, str]:
    """Download WinOptiAI-Setup.exe, verify SHA-256 against SHA256SUMS.txt, and launch updater."""
    if not info.setup_url:
        return False, "El release no contiene WinOptiAI-Setup.exe adjunto."

    dl_dir = Path(tempfile.gettempdir()) / "WinOptiAI-Update"
    dl_dir.mkdir(parents=True, exist_ok=True)
    setup_path = dl_dir / "WinOptiAI-Setup.exe"

    try:
        setup_path.write_bytes(_http_get_bytes(info.setup_url, timeout=90))

        if info.checksums_url:
            sums_text = _http_get_bytes(info.checksums_url, timeout=20).decode("utf-8", errors="replace")
            expected = _parse_expected_sha256(sums_text, "WinOptiAI-Setup.exe")
            if expected:
                actual = hashlib.sha256(setup_path.read_bytes()).hexdigest().lower()
                if actual != expected:
                    setup_path.unlink(missing_ok=True)
                    return False, "Error de integridad SHA-256 en el instalador descargado."

        if os.name == "nt":
            subprocess.Popen(
                [str(setup_path), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
                cwd=str(dl_dir),
            )
            return True, "Actualizador verificado e iniciado. La aplicacion se reiniciara."
        return False, "Actualizacion solo soportada en Windows."
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return False, f"Fallo al descargar la actualizacion: {exc}"
