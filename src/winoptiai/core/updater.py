"""GitHub Releases self-updater with SemVer comparison and SHA-256 verification."""

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
    """Parse 'v0.2.0' or '0.2.0' into comparable integer tuple."""
    clean = version_str.strip().lstrip("vV").split("-")[0]
    parts: list[int] = []
    for p in clean.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts or [0])


def check_for_updates(current_version: str = __version__, timeout: int = 8) -> tuple[bool, ReleaseInfo | None, str]:
    """Query GitHub Releases API for newer versions."""
    req = urllib.request.Request(
        RELEASES_API_URL,
        headers={
            "User-Agent": f"WinOptiAI/{current_version}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, None, "Aun no hay releases publicados en GitHub."
        return False, None, f"Error HTTP {exc.code} consultando GitHub."
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
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
    return True, info, ("Nueva version disponible" if has_update else "Ya tienes la ultima version")


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
        req = urllib.request.Request(info.setup_url, headers={"User-Agent": f"WinOptiAI/{__version__}"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            setup_path.write_bytes(resp.read())

        if info.checksums_url:
            creq = urllib.request.Request(info.checksums_url, headers={"User-Agent": f"WinOptiAI/{__version__}"})
            with urllib.request.urlopen(creq, timeout=15) as cresp:
                sums_text = cresp.read().decode("utf-8", errors="replace")
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
