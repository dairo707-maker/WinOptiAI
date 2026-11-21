"""Orphan file & leftover application artifact hunter.

Detects unused loose files that are neither referenced by active processes (via
Windows Restart Manager) nor linked to currently installed software:
- Old installers (.msi, .exe, .msix, .iso) sitting in Downloads (> 30 days)
- Loose temporary/backup artifacts (.tmp, .bak, .old, .dmp, .part)
- Stale developer environments (.venv, node_modules, __pycache__) inactive > 60 days
- Leftover folders in AppData\\Local / AppData\\Roaming absent from Windows Uninstall registry
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import time
from typing import Callable

from ..core.safety_guard import QuarantineVault, is_protected_path
from ..core.usage_telemetry import file_last_used_ts
from ..core.win32_bridge import (
    IS_WINDOWS,
    attrs_skip_entry,
    get_locking_processes,
    is_cloud_only_file,
    is_reparse_or_system_file,
)


VENDOR_ALLOWLIST: frozenset[str] = frozenset(
    {
        "microsoft",
        "windows",
        "packages",
        "programs",
        "temp",
        "cache",
        "winoptiai",
        "google",
        "mozilla",
        "lenovo",
        "intel",
        "bitdefender",
        "onedrive",
        "claude",
        "antigravity",
        "vscode",
        "code",
        "uv",
        "pip",
        "npm",
        "npm-cache",
        "nuget",
        "python",
        "jetbrains",
        "nvidia",
        "amd",
        "d3dscache",
        "crashdumps",
        "iconcache",
        "fontconfig",
        "connecteddevicesplatform",
        "squirrel",
        "toast",
    }
)

LOOSE_JUNK_EXTENSIONS: frozenset[str] = frozenset({".tmp", ".bak", ".old", ".dmp", ".part", ".crdownload"})
INSTALLER_EXTENSIONS: frozenset[str] = frozenset({".msi", ".exe", ".msix", ".appxbundle", ".iso"})


@dataclass(slots=True)
class OrphanCandidate:
    """Represents a loose file or abandoned directory eligible for quarantine."""

    path: Path
    kind: str
    confidence: str  # "SEGURO" | "REVISAR"
    size_bytes: int
    last_modified: str
    in_use_by: str = ""
    is_dir: bool = False
    last_used_ts: float = 0.0


def _get_installed_program_tokens() -> set[str]:
    """Read installed software names from Windows Uninstall registry keys."""
    tokens: set[str] = set(VENDOR_ALLOWLIST)
    if not IS_WINDOWS:
        return tokens

    import winreg

    reg_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, subkey in reg_paths:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                count = winreg.QueryInfoKey(key)[0]
                for idx in range(count):
                    try:
                        name = winreg.EnumKey(key, idx)
                        with winreg.OpenKey(key, name) as item:
                            for val_name in ("DisplayName", "Publisher", "InstallLocation"):
                                try:
                                    val, _ = winreg.QueryValueEx(item, val_name)
                                    if isinstance(val, str):
                                        for part in val.lower().replace("-", " ").replace("_", " ").split():
                                            if len(part) >= 3:
                                                tokens.add(part.strip("\\/"))
                                except OSError:
                                    continue
                    except OSError:
                        continue
        except OSError:
            continue
    return tokens


def _dir_size(path: Path) -> int:
    total = 0
    stack: list[Path] = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    attrs = getattr(st, "st_file_attributes", None)
                    is_dir = entry.is_dir(follow_symlinks=False)
                    if attrs_skip_entry(attrs, is_dir):
                        continue
                    if is_dir:
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        total += int(st.st_size)
        except OSError:
            continue
    return total


def scan_orphan_artifacts(
    extra_roots: list[Path] | None = None,
    stale_days: int = 45,
    progress_cb: Callable[[int, str], None] | None = None,
) -> list[OrphanCandidate]:
    """Scan user directories and AppData for loose unused files and abandoned artifacts."""
    if progress_cb:
        progress_cb(12, "Escaneando archivos sueltos y entornos inactivos...")
    now = time.time()
    cutoff_stale = now - (stale_days * 86400)
    cutoff_installer = now - (30 * 86400)
    candidates: list[OrphanCandidate] = []

    user_home = Path.home()
    downloads = user_home / "Downloads"
    scan_roots = list(extra_roots or [])
    if downloads.exists() and downloads not in scan_roots:
        scan_roots.append(downloads)

    # 1. Loose temporary/backup files and stale installers in Downloads / custom roots
    for root in scan_roots:
        if not root.exists() or is_protected_path(root):
            continue
        for dirpath, dirs, files in os.walk(root):
            current = Path(dirpath)
            if is_protected_path(current):
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if not is_reparse_or_system_file(current / d)]

            # Detect stale abandoned dev environments (.venv, node_modules)
            for dname in list(dirs):
                if dname in {".venv", "venv", "node_modules"}:
                    dpath = current / dname
                    try:
                        dst = dpath.stat()
                        mtime = dst.st_mtime
                    except OSError:
                        continue
                    if mtime <= cutoff_stale:
                        size = _dir_size(dpath)
                        if size > 10 * 1024 * 1024:
                            candidates.append(
                                OrphanCandidate(
                                    path=dpath,
                                    kind="Entorno inactivo",
                                    confidence="REVISAR",
                                    size_bytes=size,
                                    last_modified=datetime.fromtimestamp(mtime).strftime("%Y-%m-%d"),
                                    is_dir=True,
                                    last_used_ts=file_last_used_ts(dst),
                                )
                            )
                    dirs.remove(dname)

            for fname in files:
                fpath = current / fname
                if is_cloud_only_file(fpath) or is_reparse_or_system_file(fpath):
                    continue
                ext = fpath.suffix.lower()
                try:
                    st = fpath.stat()
                except OSError:
                    continue

                if ext in LOOSE_JUNK_EXTENSIONS and st.st_mtime <= now - 86400:
                    lockers = get_locking_processes([fpath])
                    candidates.append(
                        OrphanCandidate(
                            path=fpath,
                            kind="Archivo suelto temporal",
                            confidence="SEGURO" if not lockers else "EN_USO",
                            size_bytes=st.st_size,
                            last_modified=datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
                            in_use_by=", ".join(str(x["app_name"]) for x in lockers),
                            last_used_ts=file_last_used_ts(st),
                        )
                    )
                elif current == downloads and ext in INSTALLER_EXTENSIONS and st.st_mtime <= cutoff_installer:
                    lockers = get_locking_processes([fpath])
                    candidates.append(
                        OrphanCandidate(
                            path=fpath,
                            kind="Instalador antiguo",
                            confidence="REVISAR" if not lockers else "EN_USO",
                            size_bytes=st.st_size,
                            last_modified=datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
                            in_use_by=", ".join(str(x["app_name"]) for x in lockers),
                            last_used_ts=file_last_used_ts(st),
                        )
                    )

    # 2. Leftover AppData folders not matching installed programs (only when scanning system user)
    if progress_cb:
        progress_cb(60, "Verificando residuos en AppData contra registro de Windows...")
    if extra_roots is None:
        installed_tokens = _get_installed_program_tokens()
        for appdata_env in ("LOCALAPPDATA", "APPDATA"):
            base = os.environ.get(appdata_env)
            if not base:
                continue
            base_path = Path(base)
            if not base_path.exists():
                continue
            for entry in base_path.iterdir():
                if not entry.is_dir() or is_reparse_or_system_file(entry):
                    continue
                norm = entry.name.lower().replace("-", " ").replace("_", " ")
                parts = [p for p in norm.split() if len(p) >= 3]
                if not parts:
                    continue
                if any(tok in installed_tokens for tok in parts):
                    continue
                try:
                    est = entry.stat()
                    mtime = est.st_mtime
                except OSError:
                    continue
                if mtime > cutoff_stale:
                    continue
                size = _dir_size(entry)
                if size < 5 * 1024 * 1024:
                    continue
                candidates.append(
                    OrphanCandidate(
                        path=entry,
                        kind="Residuo AppData sin programa",
                        confidence="REVISAR",
                        size_bytes=size,
                        last_modified=datetime.fromtimestamp(mtime).strftime("%Y-%m-%d"),
                        is_dir=True,
                        last_used_ts=file_last_used_ts(est),
                    )
                )

    candidates.sort(key=lambda c: c.size_bytes, reverse=True)
    return candidates


def quarantine_orphans(
    items: list[OrphanCandidate],
    vault: QuarantineVault,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, int]:
    """Move selected orphan items into the reversible Quarantine Vault in one batch."""
    eligible: list[tuple[Path, str]] = []
    skipped = 0
    for item in items:
        if item.confidence == "EN_USO":
            skipped += 1
            continue
        eligible.append((item.path, item.kind))
    res = vault.quarantine_many(eligible, progress_cb=progress_cb)
    return {
        "moved": res["moved"],
        "skipped": skipped + res["skipped"],
        "freed_bytes": res["freed_bytes"],
    }
