"""Safe Windows storage scanner: junk caches, BLAKE3 duplicates, and orphan hunter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import os
from pathlib import Path
import sys
import time
from typing import Callable

from ..core.safety_guard import QuarantineVault, is_protected_path
from ..core.task_control import (
    SessionManager,
    TaskCanceledError,
    TaskController,
    TaskPausedAndSaved,
    TaskSessionRecord,
    new_session_id,
)
from ..core.win32_bridge import (
    attrs_is_cloud_only,
    attrs_is_reparse_or_system,
    get_locking_processes,
)


BULK_SKIP_RM_THRESHOLD = 400


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
    _cached_eligible: list[tuple[Path, int]] = field(default_factory=list, repr=False)
    _scanned_at: float = field(default=0.0, repr=False)


def _build_default_targets() -> list[JunkTarget]:
    local_app = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    roaming_app = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    user_temp = Path(os.environ.get("TEMP", str(local_app / "Temp")))
    win_root = Path(os.environ.get("WINDIR", "C:\\Windows"))
    prog_data = Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData"))

    candidates = [
        JunkTarget("user_temp", "Temporales de usuario", "Sistema", user_temp, False, min_age_days=1),
        JunkTarget("win_temp", "Temporales residuales de Windows", "Sistema", win_root / "Temp", True, min_age_days=2, requires_admin=True),
        JunkTarget("win_update_dl", "Cache descargas Windows Update", "Sistema", win_root / "SoftwareDistribution" / "Download", True, min_age_days=7, requires_admin=True),
        JunkTarget("win_delivery_opt", "Cache Delivery Optimization", "Sistema", win_root / "SoftwareDistribution" / "DeliveryOptimization", True, min_age_days=7, requires_admin=True),
        JunkTarget("win_minidump", "Volcados de error Minidump", "Registros Error", win_root / "Minidump", True, min_age_days=7, requires_admin=True),
        JunkTarget("wer_archive", "Informes residuales de errores (WER)", "Registros Error", prog_data / "Microsoft" / "Windows" / "WER" / "ReportArchive", True, min_age_days=7, requires_admin=True),
        JunkTarget("crash_dumps", "Volcados de fallos usuario", "Registros Error", local_app / "CrashDumps", False, min_age_days=7),
        JunkTarget("d3d_cache", "Cache de sombreadores DirectX", "GPU", local_app / "D3DSCache", False, min_age_days=3),
        JunkTarget("uv_cache", "Cache de paquetes uv", "IA y Dev", local_app / "uv" / "cache", False, min_age_days=7),
        JunkTarget("pip_cache", "Cache de paquetes pip", "IA y Dev", local_app / "pip" / "Cache", False, min_age_days=7),
        JunkTarget("npm_cache", "Cache de paquetes npm", "IA y Dev", local_app / "npm-cache", False, min_age_days=7),
        JunkTarget("nuget_cache", "Cache HTTP NuGet", "IA y Dev", local_app / "NuGet" / "v3-cache", False, min_age_days=7),
        JunkTarget("vscode_cached", "Cache compilado VS Code", "IA y Dev", roaming_app / "Code" / "CachedData", False, min_age_days=14),
        JunkTarget("hf_locks", "Bloqueos temporales HuggingFace", "IA y Dev", Path.home() / ".cache" / "huggingface" / "hub" / ".locks", False, min_age_days=7),
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


def _live_meipass_dir() -> str | None:
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    try:
        return str(Path(meipass).resolve()).lower()
    except OSError:
        return str(meipass).lower()


def _scan_eligible_with_sizes(
    target: JunkTarget,
    now_ts: float,
    progress_cb: Callable[[int, str], None] | None = None,
    controller: TaskController | None = None,
) -> list[tuple[Path, int]]:
    """Collect (Path, size_bytes) in a single scandir+stat syscall pass with live count feedback."""
    if not target.path.exists():
        return []
    if is_protected_path(target.path, allow_system_temp=target.allow_system_temp):
        return []

    cutoff = now_ts - (target.min_age_days * 86400)
    eligible: list[tuple[Path, int]] = []
    stack: list[Path] = [target.path]
    mei_dir = _live_meipass_dir()
    visited = 0

    while stack:
        if controller is not None and controller.checkpoint() == "cancel":
            raise TaskCanceledError("Analisis de temporales cancelado por el usuario")
        cur = stack.pop()
        if mei_dir and str(cur).lower().startswith(mei_dir):
            continue
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
                        if mei_dir and entry.path.lower() == mei_dir:
                            continue
                        stack.append(ep)
                    elif entry.is_file(follow_symlinks=False):
                        visited += 1
                        if st.st_mtime <= cutoff:
                            eligible.append((ep, int(st.st_size)))
                        if visited % 1000 == 0:
                            if controller is not None and controller.checkpoint() == "cancel":
                                raise TaskCanceledError("Analisis cancelado por el usuario")
                            if progress_cb:
                                progress_cb(12, f"Indexando {target.label} ({len(eligible):,} elegibles)...")
        except OSError:
            continue
    return eligible


def _iter_eligible_files(target: JunkTarget, now_ts: float) -> list[Path]:
    return [p for p, _ in _scan_eligible_with_sizes(target, now_ts)]


def _filter_unlocked_binary(
    items: list[tuple[Path, int]],
    chunk_size: int = 256,
) -> tuple[list[tuple[Path, int]], int]:
    """Use divide-and-conquer Restart Manager checks for small file sets."""
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


def _prune_empty_dirs(root: Path) -> None:
    """Remove empty temp subdirectories without ever touching root itself."""
    if not root.exists():
        return
    mei_dir = _live_meipass_dir()
    for dirpath, _dirs, _files in os.walk(root, topdown=False):
        dp = Path(dirpath)
        if dp == root:
            continue
        if mei_dir and str(dp).lower().startswith(mei_dir):
            continue
        try:
            dp.rmdir()
        except OSError:
            continue


def scan_junk_targets(
    targets: list[JunkTarget] | None = None,
    progress_cb: Callable[[int, str], None] | None = None,
    controller: TaskController | None = None,
) -> list[JunkTarget]:
    """Scan all configured safe junk targets and compute reclaimable bytes."""
    resolved = targets if targets is not None else _build_default_targets()
    now_ts = time.time()
    total_targets = max(1, len(resolved))
    for idx, target in enumerate(resolved, start=1):
        if controller is not None and controller.checkpoint() == "cancel":
            raise TaskCanceledError("Analisis cancelado por el usuario")
        if progress_cb:
            pct = max(6, int((idx - 1) * 95 / total_targets))
            progress_cb(pct, f"Analizando {target.label}...")

        def _scan_sub(_pct: int, msg: str, base_p: int = max(6, int((idx - 1) * 95 / total_targets))) -> None:
            if progress_cb:
                progress_cb(min(94, base_p + 2), msg)

        files = _scan_eligible_with_sizes(target, now_ts, progress_cb=_scan_sub, controller=controller)
        target._cached_eligible = files
        target._scanned_at = now_ts
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
    controller: TaskController | None = None,
    explicit_files: list[tuple[Path, int]] | None = None,
) -> dict:
    """Clean eligible unlocked files inside target with O(N) performance and cooperative pause/cancel."""
    now_ts = time.time()
    if explicit_files is not None:
        files = [(p, sz) for p, sz in explicit_files if p.exists()]
    elif target._cached_eligible and (now_ts - target._scanned_at) < 600:
        files = [(p, sz) for p, sz in target._cached_eligible if p.exists()]
    else:
        if progress_cb:
            progress_cb(8, f"Indexando {target.label}...")
        files = _scan_eligible_with_sizes(target, now_ts, progress_cb=progress_cb, controller=controller)

    if not files:
        target._cached_eligible = []
        if progress_cb:
            progress_cb(100, f"Sin temporales pendientes en {target.label}")
        return {
            "removed": 0,
            "skipped_locked": 0,
            "permission_denied": 0,
            "freed_bytes": 0,
            "interrupted": "",
            "remaining_sources": [],
        }

    rm_locked = 0
    if len(files) <= BULK_SKIP_RM_THRESHOLD:
        if progress_cb:
            progress_cb(12, f"Verificando bloqueos Win32 en {len(files)} archivos...")
        unlocked, rm_locked = _filter_unlocked_binary(files)
    else:
        unlocked = files
        if progress_cb:
            progress_cb(14, f"Limpieza directa segura en {len(unlocked):,} archivos...")

    if use_quarantine:
        res = vault.quarantine_batch_bundle(
            unlocked,
            base_dir=target.path,
            bundle_name=target.target_id,
            category=f"Basura:{target.category}",
            allow_system_temp=target.allow_system_temp,
            progress_cb=progress_cb,
            controller=controller,
        )
        if not res.get("interrupted"):
            _prune_empty_dirs(target.path)
            target._cached_eligible = []
        skipped = rm_locked + res["skipped"]
        target.locked_skipped = skipped
        return {
            "removed": res["moved"],
            "skipped_locked": skipped,
            "permission_denied": res["permission_denied"],
            "freed_bytes": res["freed_bytes"],
            "interrupted": res.get("interrupted", ""),
            "remaining_sources": res.get("remaining_sources", []),
        }

    removed = 0
    skipped = rm_locked
    permission_denied = 0
    freed = 0
    interrupted = ""
    remaining_sources: list[tuple[Path, int]] = []
    total = max(1, len(unlocked))
    for idx, (fpath, size) in enumerate(unlocked, start=1):
        if controller is not None and (idx == 1 or idx % 50 == 0):
            st_chk = controller.checkpoint()
            if st_chk in ("cancel", "save_pause"):
                interrupted = st_chk
                remaining_sources = unlocked[idx - 1 :]
                break
        if progress_cb and (idx == 1 or idx % 250 == 0 or idx == total):
            progress_cb(15 + int(idx * 80 / total), f"Limpiando {target.label} ({idx}/{total})...")
        try:
            fpath.unlink()
            removed += 1
            freed += size
        except PermissionError:
            permission_denied += 1
            skipped += 1
        except OSError:
            skipped += 1

    if not interrupted:
        _prune_empty_dirs(target.path)
        target._cached_eligible = []
    target.locked_skipped = skipped
    return {
        "removed": removed,
        "skipped_locked": skipped,
        "permission_denied": permission_denied,
        "freed_bytes": freed,
        "interrupted": interrupted,
        "remaining_sources": remaining_sources,
    }


def clean_junk_targets(
    targets: list[JunkTarget],
    vault: QuarantineVault,
    use_quarantine: bool = True,
    progress_cb: Callable[[int, str], None] | None = None,
    controller: TaskController | None = None,
    session_mgr: SessionManager | None = None,
) -> dict[str, int]:
    """Clean multiple JunkTargets supporting Pause+Save Session and Cancel cleanly."""
    freed = removed = skipped = perm = 0
    weights = [max(1, t.file_count) for t in targets]
    total_weight = max(1, sum(weights))
    done_weight = 0
    last_pct = 6

    for t_idx, (t, w) in enumerate(zip(targets, weights)):
        base_pct = 6 + int(done_weight * 92 / total_weight)
        span_pct = max(4, int(w * 92 / total_weight))
        last_pct = max(last_pct, base_pct)

        def _sub_cb(sub_pct: int, msg: str, b: int = base_pct, s: int = span_pct) -> None:
            nonlocal last_pct
            overall = min(98, max(6, b + int(sub_pct * s / 100)))
            last_pct = overall
            if progress_cb:
                progress_cb(overall, msg)

        if progress_cb:
            progress_cb(max(6, base_pct), f"Limpiando {t.label} ({t.file_count:,} archivos)...")
        res = clean_junk_target(
            t,
            vault,
            use_quarantine=use_quarantine,
            progress_cb=_sub_cb,
            controller=controller,
        )
        done_weight += w
        freed += res["freed_bytes"]
        removed += res["removed"]
        skipped += res["skipped_locked"]
        perm += res.get("permission_denied", 0)

        intr = res.get("interrupted", "")
        if intr == "cancel":
            raise TaskCanceledError(
                f"Limpieza cancelada ({removed} archivos asegurados en Cuarentena)."
            )
        if intr == "save_pause":
            pending_paths: list[str] = [str(p) for p, _ in res.get("remaining_sources", [])]
            remaining_target_ids = [rem_t.target_id for rem_t in targets[t_idx + 1 :]]
            mgr = session_mgr or SessionManager()
            sid = new_session_id()
            mgr.save_session(
                TaskSessionRecord(
                    session_id=sid,
                    kind="junk_clean",
                    title=f"Limpieza temporales ({t.label})",
                    created_at=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                    percent=last_pct,
                    total_items=total_weight,
                    processed_items=removed,
                    freed_so_far=freed,
                    pending_paths=pending_paths,
                    meta={
                        "current_target_id": t.target_id,
                        "remaining_target_ids": remaining_target_ids,
                        "use_quarantine": use_quarantine,
                    },
                )
            )
            raise TaskPausedAndSaved(
                sid,
                last_pct,
                f"Sesion guardada al {last_pct}% ({removed} asegurados, {len(pending_paths)} pendientes).",
            )

    if progress_cb:
        progress_cb(100, "Limpieza completada")
    return {"freed": freed, "removed": removed, "skipped": skipped, "perm": perm}


def resume_junk_session(
    session: TaskSessionRecord,
    vault: QuarantineVault,
    session_mgr: SessionManager | None = None,
    progress_cb: Callable[[int, str], None] | None = None,
    controller: TaskController | None = None,
) -> dict[str, int]:
    """Resume a saved junk cleanup session from exact pending_paths + remaining targets."""
    mgr = session_mgr or SessionManager()
    all_targets = {t.target_id: t for t in _build_default_targets()}
    use_q = bool(session.meta.get("use_quarantine", True))
    cur_tid = str(session.meta.get("current_target_id") or "")
    rem_tids = [str(x) for x in session.meta.get("remaining_target_ids") or []]

    freed = removed = skipped = perm = 0
    if cur_tid in all_targets and session.pending_paths:
        cur_t = all_targets[cur_tid]
        explicit: list[tuple[Path, int]] = []
        for raw_p in session.pending_paths:
            p = Path(raw_p)
            try:
                sz = p.stat().st_size if p.exists() else 0
            except OSError:
                sz = 0
            explicit.append((p, int(sz)))
        res = clean_junk_target(
            cur_t,
            vault,
            use_quarantine=use_q,
            progress_cb=progress_cb,
            controller=controller,
            explicit_files=explicit,
        )
        freed += res["freed_bytes"]
        removed += res["removed"]
        skipped += res["skipped_locked"]
        perm += res.get("permission_denied", 0)
        if res.get("interrupted") == "cancel":
            mgr.remove_session(session.session_id)
            raise TaskCanceledError(f"Reanudacion cancelada ({removed} archivos asegurados).")
        if res.get("interrupted") == "save_pause":
            session.pending_paths = [str(p) for p, _ in res.get("remaining_sources", [])]
            session.freed_so_far += freed
            session.processed_items += removed
            mgr.save_session(session)
            raise TaskPausedAndSaved(session.session_id, session.percent, "Sesion guardada nuevamente.")

    rem_targets = [all_targets[tid] for tid in rem_tids if tid in all_targets]
    if rem_targets:
        res2 = clean_junk_targets(
            rem_targets,
            vault,
            use_quarantine=use_q,
            progress_cb=progress_cb,
            controller=controller,
            session_mgr=mgr,
        )
        freed += res2["freed"]
        removed += res2["removed"]
        skipped += res2["skipped"]
        perm += res2["perm"]

    mgr.remove_session(session.session_id)
    if progress_cb:
        progress_cb(100, "Sesion retomada y completada")
    return {"freed": freed, "removed": removed, "skipped": skipped, "perm": perm}
