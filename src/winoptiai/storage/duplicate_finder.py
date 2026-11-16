"""High-speed 4-stage duplicate file finder using BLAKE3 and NTFS hardlinks.

Stages:
1. Safety & OneDrive guard (skips cloud-only placeholders, junctions, protected OS dirs)
2. Exact byte-size grouping (eliminates unique sizes without disk reads)
3. Fast 4KB head+tail pre-hash (eliminates mismatched large files)
4. Full cryptographic BLAKE3 digest + NTFS FileIndex (st_ino) check for existing hardlinks
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Callable

from blake3 import blake3

from ..core.safety_guard import QuarantineVault, is_protected_path, is_safe_to_touch_file
from ..core.task_control import TaskCanceledError, TaskController
from ..core.win32_bridge import (
    attrs_is_cloud_only,
    attrs_is_reparse_or_system,
    create_ntfs_hardlink,
)


PARTIAL_CHUNK_BYTES = 4096
FULL_CHUNK_BYTES = 1024 * 1024


@dataclass(slots=True)
class DuplicateGroup:
    """Group of byte-identical files sharing the same BLAKE3 digest."""

    digest: str
    size_bytes: int
    paths: list[Path]
    wasted_bytes: int


def _partial_hash(path: Path, size_bytes: int) -> str | None:
    hasher = blake3()
    try:
        with path.open("rb") as fh:
            hasher.update(fh.read(PARTIAL_CHUNK_BYTES))
            if size_bytes > PARTIAL_CHUNK_BYTES * 2:
                fh.seek(-PARTIAL_CHUNK_BYTES, os.SEEK_END)
                hasher.update(fh.read(PARTIAL_CHUNK_BYTES))
            elif size_bytes > PARTIAL_CHUNK_BYTES:
                hasher.update(fh.read())
        return hasher.hexdigest()
    except OSError:
        return None


def _full_blake3(path: Path) -> str | None:
    hasher = blake3()
    try:
        with path.open("rb") as fh:
            while chunk := fh.read(FULL_CHUNK_BYTES):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError:
        return None


def find_duplicates(
    roots: list[Path],
    min_size_bytes: int = 1024,
    progress_cb: Callable[[int, str], None] | None = None,
    controller: TaskController | None = None,
) -> list[DuplicateGroup]:
    """Scan roots and return groups of true duplicate files (excluding existing hardlinks)."""
    size_buckets: dict[int, list[tuple[Path, int, int]]] = defaultdict(list)

    if progress_cb:
        progress_cb(8, "Indexando archivos y tamanos...")

    for root in roots:
        if not root.exists() or is_protected_path(root):
            continue
        stack: list[Path] = [root]
        while stack:
            if controller is not None and controller.checkpoint() == "cancel":
                raise TaskCanceledError("Busqueda de duplicados cancelada por el usuario")
            current = stack.pop()
            if is_protected_path(current):
                continue
            try:
                with os.scandir(current) as it:
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
                            if not entry.name.startswith(".git") and entry.name != "__pycache__":
                                stack.append(ep)
                        elif entry.is_file(follow_symlinks=False) and st.st_size >= min_size_bytes:
                            size_buckets[st.st_size].append((ep, st.st_dev, st.st_ino))
            except OSError:
                continue

    if progress_cb:
        progress_cb(40, "Calculando pre-hash 4KB de candidatos...")

    candidate_sizes = [(sz, items) for sz, items in size_buckets.items() if len(items) >= 2]
    partial_buckets: dict[tuple[int, str], list[tuple[Path, int, int]]] = defaultdict(list)
    total_cand = max(1, len(candidate_sizes))
    for idx, (size, raw_items) in enumerate(candidate_sizes, start=1):
        if controller is not None and idx % 10 == 0 and controller.checkpoint() == "cancel":
            raise TaskCanceledError("Busqueda de duplicados cancelada por el usuario")
        # DirEntry.stat() returns st_ino=0 on Windows; fetch true (dev, ino) only for candidate sizes
        items: list[tuple[Path, int, int]] = []
        for fpath, dev, ino in raw_items:
            if ino == 0:
                try:
                    fst = fpath.stat()
                    dev, ino = fst.st_dev, fst.st_ino
                except OSError:
                    continue
            items.append((fpath, dev, ino))

        unique_inodes = {(dev, ino) for _, dev, ino in items if ino != 0}
        if ino_all_nonzero(items) and len(unique_inodes) < 2:
            continue
        for fpath, dev, ino in items:
            ph = _partial_hash(fpath, size)
            if ph is not None:
                partial_buckets[(size, ph)].append((fpath, dev, ino))
        if progress_cb and idx % 20 == 0:
            progress_cb(40 + int(idx * 30 / total_cand), "Pre-hash 4KB en curso...")

    if progress_cb:
        progress_cb(72, "Verificando firmas BLAKE3 completas...")

    partial_cand = [(k, items) for k, items in partial_buckets.items() if len(items) >= 2]
    full_buckets: dict[tuple[int, str], list[tuple[Path, int, int]]] = defaultdict(list)
    total_part = max(1, len(partial_cand))
    for idx, ((size, _), items) in enumerate(partial_cand, start=1):
        if controller is not None and controller.checkpoint() == "cancel":
            raise TaskCanceledError("Verificacion BLAKE3 cancelada por el usuario")
        for fpath, dev, ino in items:
            fh = _full_blake3(fpath)
            if fh is not None:
                full_buckets[(size, fh)].append((fpath, dev, ino))
        if progress_cb:
            progress_cb(72 + int(idx * 25 / total_part), "Verificando BLAKE3...")

    groups: list[DuplicateGroup] = []
    for (size, digest), items in full_buckets.items():
        # Deduplicate keeping distinct inodes (existing hardlinks share physical blocks)
        seen_inodes: set[tuple[int, int]] = set()
        distinct_paths: list[Path] = []
        for fpath, dev, ino in sorted(items, key=lambda x: str(x[0]).lower()):
            key = (dev, ino)
            if ino != 0 and key in seen_inodes:
                continue
            seen_inodes.add(key)
            distinct_paths.append(fpath)

        if len(distinct_paths) >= 2:
            wasted = size * (len(distinct_paths) - 1)
            groups.append(
                DuplicateGroup(
                    digest=digest,
                    size_bytes=size,
                    paths=distinct_paths,
                    wasted_bytes=wasted,
                )
            )

    groups.sort(key=lambda g: g.wasted_bytes, reverse=True)
    return groups


def ino_all_nonzero(items: list[tuple[Path, int, int]]) -> bool:
    return all(ino != 0 for _, _, ino in items)


def deduplicate_group_to_quarantine(
    group: DuplicateGroup,
    keep_path: Path,
    vault: QuarantineVault,
) -> dict[str, int]:
    """Keep one primary copy and move redundant copies to the Quarantine Vault."""
    keep_resolved = keep_path.resolve()
    entries = [(p, "Duplicado BLAKE3") for p in group.paths if p.resolve() != keep_resolved]
    res = vault.quarantine_many(entries)
    return {"moved": res["moved"], "skipped": res["skipped"], "freed_bytes": res["freed_bytes"]}


def quarantine_duplicates_plan(
    plan: list[tuple[DuplicateGroup, Path, list[Path]]],
    vault: QuarantineVault,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, int]:
    """Batch-quarantine redundant duplicate copies across multiple groups in O(N) time."""
    entries: list[tuple[Path, str]] = []
    for _, _, remove_paths in plan:
        for rp in remove_paths:
            entries.append((rp, "Duplicado BLAKE3"))
    return vault.quarantine_many(entries, progress_cb=progress_cb)


def deduplicate_group_via_hardlink(
    group: DuplicateGroup,
    keep_path: Path,
) -> dict[str, int]:
    """Replace redundant copies on the same NTFS volume with hardlinks to keep_path.

    Preserves both paths seamlessly while freeing duplicate physical disk sectors.
    """
    linked = 0
    skipped = 0
    freed = 0
    keep_resolved = keep_path.resolve()
    keep_dev = keep_resolved.stat().st_dev

    for p in group.paths:
        if p.resolve() == keep_resolved:
            continue
        safe, _ = is_safe_to_touch_file(p)
        if not safe:
            skipped += 1
            continue
        try:
            if p.stat().st_dev != keep_dev:
                skipped += 1
                continue
            backup = p.with_name(f".{p.name}.winoptiai_hlbak")
            p.rename(backup)
            if create_ntfs_hardlink(p, keep_resolved):
                backup.unlink()
                linked += 1
                freed += group.size_bytes
            else:
                backup.rename(p)
                skipped += 1
        except OSError:
            skipped += 1
    return {"linked": linked, "skipped": skipped, "freed_bytes": freed}


def choose_primary_copy(paths: list[Path], rule: str = "keep_oldest") -> Path:
    """Select which copy to preserve inside a duplicate group according to an auto-clean rule."""
    if len(paths) <= 1:
        return paths[0]

    def _mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return float("inf")

    if rule == "keep_newest":
        return max(paths, key=_mtime)
    if rule == "keep_shortest_path":
        return min(paths, key=lambda p: (len(str(p)), str(p).lower()))
    if rule == "keep_outside_downloads":
        return min(
            paths,
            key=lambda p: (1 if "downloads" in str(p).lower() else 0, len(str(p)), _mtime(p)),
        )
    # Default: keep_oldest
    return min(paths, key=lambda p: (_mtime(p), len(str(p))))


def select_duplicates_by_rule(
    groups: list[DuplicateGroup],
    rule: str = "keep_oldest",
) -> list[tuple[DuplicateGroup, Path, list[Path]]]:
    """Return [(group, keep_path, remove_paths)] computed for smart auto-cleaning."""
    plan: list[tuple[DuplicateGroup, Path, list[Path]]] = []
    for grp in groups:
        keep = choose_primary_copy(grp.paths, rule=rule)
        remove = [p for p in grp.paths if p != keep]
        if remove:
            plan.append((grp, keep, remove))
    return plan
