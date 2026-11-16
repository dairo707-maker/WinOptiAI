"""Safe Windows storage scanner: junk caches, BLAKE3 duplicates, and orphan hunter."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import time
from typing import Callable

from ..core.safety_guard import QuarantineVault, is_protected_path
from ..core.win32_bridge import (
    attrs_is_cloud_only,
    attrs_is_reparse_or_system,
    get_locking_processes,
)


@dataclass(slots=True)
class JunkTarget:
    """Categorized cache or temporary directory eligible for safe cleanup."""

    target_id: str
    label: str
    category: str
    path: Path
    allow_system_temp: bool
    min_age_days: int = 0
    requires_admin: bool = False
    file_count: int = 0
    reclaimable_bytes: int = 0
    locked_skipped: int = 0


def _build_default_targets() -> list[JunkTarget]:
    local_app = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    user_temp = Path(os.environ.get("TEMP", str(local_app / "Temp")))
    win_root = Path(os.environ.get("WINDIR", "C:\\Windows"))
    prog_data = Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData"))

    candidates = [
        JunkTarget("user_temp", "Temporales de usuario", "Sistema", user_temp, False, min_age_days=1),
        JunkTarget("win_temp", "Temporales residuales de Windows", "Sistema", win_root / "Temp", True, min_age_days=2, requires_admin=True),
        JunkTarget("win_minidump", "Volcados de error Minidump", "Registros Error", win_root / "Minidump", True, min_age_days=7, requires_admin=True),
        JunkTarget("wer_archive", "Informes residuales de errores (WER)", "Registros Error", prog_data / "Microsoft" / "Windows" / "WER" / "ReportArchive", True, min_age_days=7, requires_admin=True),
        JunkTarget("crash_dumps", "Volcados de fallos usuario", "Registros Error", local_app / "CrashDumps", False, min_age_days=7),
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


def _scan_eligible_with_sizes(target: JunkTarget, now_ts: float) -> list[tuple[Path, int]]:
    """Collect (Path, size_bytes) in a single scandir+stat syscall pass."""
    if not target.path.exists():
        return []
    if is_protected_path(target.path, allow_system_temp=target.allow_system_temp):
        return []

    cutoff = now_ts - (target.min_age_days * 86400)
    eligible: list[tuple[Path, int]] = []
    stack: list[Path] = [target.path]

    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    ep = Path(entry.path)
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    attrs = getattr(st, "st_file_attributes", None)
                    if attrs_is_reparse_or_system(attrs) or attrs_is_cloud_only(attrs):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(ep)
                    elif entry.is_file(follow_symlinks=False) and st.st_mtime <= cutoff:
                        eligible.append((ep, int(st.st_size)))
        except OSError:
            continue
    return eligible


def _iter_eligible_files(target: JunkTarget, now_ts: float) -> list[Path]:
    return [p for p, _ in _scan_eligible_with_sizes(target, now_ts)]


def _filter_unlocked_binary(
    items: list[tuple[Path, int]],
    chunk_size: int = 256,
) -> tuple[list[tuple[Path, int]], int]:
    """Use divide-and-conquer Restart Manager checks so 100k unlocked files run in milliseconds."""
    unlocked: list[tuple[Path, int]] = []
    locked_count = 0

    def _inspect(batch: list[tuple[Path, int]]) -> None:
        nonlocal locked_count
        if not batch:
            return
        if not get_locking_processes([p for p, _ in batch]):
            unlocked.extend(batch)
            return
        if len(batch) == 1:
            locked_count += 1
            return
        mid = len(batch) // 2
        _inspect(batch[:mid])
        _inspect(batch[mid:])

    for i in range(0, len(items), chunk_size):
        _inspect(items[i : i + chunk_size])
    return unlocked, locked_count


def scan_junk_targets(
    targets: list[JunkTarget] | None = None,
    progress_cb: Callable[[int, str], None] | None = None,
) -> list[JunkTarget]:
    """Scan all configured safe junk targets and compute reclaimable bytes."""
    resolved = targets if targets is not None else _build_default_targets()
    now_ts = time.time()
    total_targets = max(1, len(resolved))
    for idx, target in enumerate(resolved, start=1):
        if progress_cb:
            progress_cb(int((idx - 1) * 100 / total_targets), f"Analizando {target.label}...")
        files = _scan_eligible_with_sizes(target, now_ts)
        target.file_count = len(files)
        target.reclaimable_bytes = sum(sz for _, sz in files)
        target.locked_skipped = 0
    if progress_cb:
        progress_cb(100, "Temporales analizados")
    return resolved


def clean_junk_target(
    target: JunkTarget,
    vault: QuarantineVault,
    use_quarantine: bool = False,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, int]:
    """Clean eligible unlocked files inside target with O(N) performance and % updates.

    When use_quarantine=True, unlocked files are moved rapidly into a single reversible
    batch bundle in Quarantine Vault instead of O(N^2) per-file manifest rewrites.
    """
    now_ts = time.time()
    if progress_cb:
        progress_cb(8, f"Indexando {target.label}...")
    files = _scan_eligible_with_sizes(target, now_ts)
    if not files:
        if progress_cb:
            progress_cb(100, f"Sin temporales pendientes en {target.label}")
        return {"removed": 0, "skipped_locked": 0, "permission_denied": 0, "freed_bytes": 0}

    if progress_cb:
        progress_cb(14, f"Verificando bloqueos Win32 en {len(files)} archivos...")
    unlocked, rm_locked = _filter_unlocked_binary(files)

    if use_quarantine:
        res = vault.quarantine_batch_bundle(
            unlocked,
            base_dir=target.path,
            bundle_name=target.target_id,
            category=f"Basura:{target.category}",
            allow_system_temp=target.allow_system_temp,
            progress_cb=progress_cb,
        )
        skipped = rm_locked + res["skipped"]
        target.locked_skipped = skipped
        return {
            "removed": res["moved"],
            "skipped_locked": skipped,
            "permission_denied": res["permission_denied"],
            "freed_bytes": res["freed_bytes"],
        }

    removed = 0
    skipped = rm_locked
    permission_denied = 0
    freed = 0
    total = max(1, len(unlocked))
    for idx, (fpath, size) in enumerate(unlocked, start=1):
        if progress_cb and (idx == 1 or idx % 250 == 0 or idx == total):
            progress_cb(20 + int(idx * 75 / total), f"Limpiando {target.label} ({idx}/{total})...")
        try:
            fpath.unlink()
            removed += 1
            freed += size
        except PermissionError:
            permission_denied += 1
            skipped += 1
        except OSError:
            skipped += 1

    target.locked_skipped = skipped
    return {
        "removed": removed,
        "skipped_locked": skipped,
        "permission_denied": permission_denied,
        "freed_bytes": freed,
    }


def clean_junk_targets(
    targets: list[JunkTarget],
    vault: QuarantineVault,
    use_quarantine: bool = True,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, int]:
    """Clean multiple JunkTargets reporting smooth cumulative progress 5%..99%."""
    freed = removed = skipped = perm = 0
    total = max(1, len(targets))
    for idx, t in enumerate(targets):
        base_pct = int(idx * 95 / total)
        span_pct = max(5, int(95 / total))

        def _sub_cb(sub_pct: int, msg: str, b: int = base_pct, s: int = span_pct) -> None:
            if progress_cb:
                overall = min(98, max(5, b + int(sub_pct * s / 100)))
                progress_cb(overall, msg)

        if progress_cb:
            progress_cb(max(5, base_pct), f"Procesando {t.label} ({idx + 1}/{total})...")
        res = clean_junk_target(t, vault, use_quarantine=use_quarantine, progress_cb=_sub_cb)
        freed += res["freed_bytes"]
        removed += res["removed"]
        skipped += res["skipped_locked"]
        perm += res.get("permission_denied", 0)
    if progress_cb:
        progress_cb(100, "Limpieza completada")
    return {"freed": freed, "removed": removed, "skipped": skipped, "perm": perm}
