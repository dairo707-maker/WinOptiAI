"""Safe Windows storage scanner: junk caches, BLAKE3 duplicates, and orphan hunter."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import time

from ..core.safety_guard import QuarantineVault, is_protected_path
from ..core.win32_bridge import get_locking_processes, is_cloud_only_file, is_reparse_or_system_file


@dataclass(slots=True)
class JunkTarget:
    """Categorized cache or temporary directory eligible for safe cleanup."""

    target_id: str
    label: str
    category: str
    path: Path
    allow_system_temp: bool
    min_age_days: int = 0
    file_count: int = 0
    reclaimable_bytes: int = 0
    locked_skipped: int = 0


def _build_default_targets() -> list[JunkTarget]:
    local_app = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    user_temp = Path(os.environ.get("TEMP", str(local_app / "Temp")))
    win_root = Path(os.environ.get("WINDIR", "C:\\Windows"))

    candidates = [
        JunkTarget("user_temp", "Temporales de usuario", "Sistema", user_temp, False, min_age_days=1),
        JunkTarget("win_temp", "Temporales de Windows", "Sistema", win_root / "Temp", True, min_age_days=2),
        JunkTarget("crash_dumps", "Volcados de fallos", "Sistema", local_app / "CrashDumps", False, min_age_days=7),
        JunkTarget("d3d_cache", "Cache de sombreadores DirectX", "GPU", local_app / "D3DSCache", False, min_age_days=3),
        JunkTarget("uv_cache", "Cache de paquetes uv", "IA y Dev", local_app / "uv" / "cache", False, min_age_days=7),
        JunkTarget("pip_cache", "Cache de paquetes pip", "IA y Dev", local_app / "pip" / "Cache", False, min_age_days=7),
        JunkTarget("npm_cache", "Cache de paquetes npm", "IA y Dev", local_app / "npm-cache", False, min_age_days=7),
        JunkTarget("nuget_cache", "Cache HTTP NuGet", "IA y Dev", local_app / "NuGet" / "v3-cache", False, min_age_days=7),
        JunkTarget(
            "chrome_cache",
            "Cache temporal de Chrome (sin sesiones)",
            "Navegador",
            local_app / "Google" / "Chrome" / "User Data" / "Default" / "Cache" / "Cache_Data",
            False,
            min_age_days=1,
        ),
        JunkTarget(
            "edge_cache",
            "Cache temporal de Edge (sin sesiones)",
            "Navegador",
            local_app / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache" / "Cache_Data",
            False,
            min_age_days=1,
        ),
    ]
    return [c for c in candidates if c.path.exists()]


def _iter_eligible_files(target: JunkTarget, now_ts: float) -> list[Path]:
    if not target.path.exists():
        return []
    if is_protected_path(target.path, allow_system_temp=target.allow_system_temp):
        return []

    cutoff = now_ts - (target.min_age_days * 86400)
    eligible: list[Path] = []
    for root, dirs, files in os.walk(target.path):
        root_path = Path(root)
        # Never traverse junctions/symlinks
        dirs[:] = [d for d in dirs if not is_reparse_or_system_file(root_path / d)]
        for name in files:
            fpath = root_path / name
            if is_cloud_only_file(fpath) or is_reparse_or_system_file(fpath):
                continue
            try:
                st = fpath.stat()
            except OSError:
                continue
            if st.st_mtime <= cutoff:
                eligible.append(fpath)
    return eligible


def scan_junk_targets(targets: list[JunkTarget] | None = None) -> list[JunkTarget]:
    """Scan all configured safe junk targets and compute reclaimable bytes."""
    resolved = targets if targets is not None else _build_default_targets()
    now_ts = time.time()
    for target in resolved:
        files = _iter_eligible_files(target, now_ts)
        total = 0
        for f in files:
            try:
                total += f.stat().st_size
            except OSError:
                continue
        target.file_count = len(files)
        target.reclaimable_bytes = total
        target.locked_skipped = 0
    return resolved


def clean_junk_target(
    target: JunkTarget,
    vault: QuarantineVault,
    use_quarantine: bool = False,
) -> dict[str, int]:
    """Clean eligible unlocked files inside target.

    System temp/cache files are checked against Windows Restart Manager before removal.
    When use_quarantine=True, files are moved to the reversible Quarantine Vault.
    """
    now_ts = time.time()
    files = _iter_eligible_files(target, now_ts)
    if not files:
        return {"removed": 0, "skipped_locked": 0, "freed_bytes": 0}

    # Batch check active locks with Restart Manager in chunks of 100
    locked_pids_exist = False
    for i in range(0, len(files), 100):
        chunk = files[i : i + 100]
        if get_locking_processes(chunk):
            locked_pids_exist = True
            break

    removed = 0
    skipped = 0
    freed = 0

    for fpath in files:
        if locked_pids_exist and get_locking_processes([fpath]):
            skipped += 1
            continue
        try:
            size = fpath.stat().st_size
        except OSError:
            skipped += 1
            continue

        if use_quarantine:
            ok, _, _ = vault.quarantine_path(
                fpath,
                category=f"Basura:{target.category}",
                allow_system_temp=target.allow_system_temp,
            )
            if ok:
                removed += 1
                freed += size
            else:
                skipped += 1
        else:
            try:
                fpath.unlink()
                removed += 1
                freed += size
            except OSError:
                skipped += 1

    target.locked_skipped = skipped
    return {"removed": removed, "skipped_locked": skipped, "freed_bytes": freed}
