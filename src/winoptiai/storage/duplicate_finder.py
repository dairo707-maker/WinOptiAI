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
from ..core.win32_bridge import create_ntfs_hardlink, is_cloud_only_file, is_reparse_or_system_file


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
    progress_cb: Callable[[str], None] | None = None,
) -> list[DuplicateGroup]:
    """Scan roots and return groups of true duplicate files (excluding existing hardlinks)."""
    size_buckets: dict[int, list[tuple[Path, int, int]]] = defaultdict(list)

    for root in roots:
        if not root.exists() or is_protected_path(root):
            continue
        for dirpath, dirs, filenames in os.walk(root):
            current = Path(dirpath)
            if is_protected_path(current):
                dirs[:] = []
                continue
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".git")
                and d != "__pycache__"
                and not is_reparse_or_system_file(current / d)
            ]
            for name in filenames:
                fpath = current / name
                if is_cloud_only_file(fpath) or is_reparse_or_system_file(fpath):
                    continue
                try:
                    st = fpath.stat()
                except OSError:
                    continue
                if st.st_size < min_size_bytes:
                    continue
                size_buckets[st.st_size].append((fpath, st.st_dev, st.st_ino))

    if progress_cb:
        progress_cb("Agrupando candidatos por tamano...")

    partial_buckets: dict[tuple[int, str], list[tuple[Path, int, int]]] = defaultdict(list)
    for size, items in size_buckets.items():
        if len(items) < 2:
            continue
        # Filter out entries that already point to the exact same inode on the same device
        unique_inodes = {(dev, ino) for _, dev, ino in items if ino != 0}
        if ino_all_nonzero(items) and len(unique_inodes) < 2:
            continue
        for fpath, dev, ino in items:
            ph = _partial_hash(fpath, size)
            if ph is not None:
                partial_buckets[(size, ph)].append((fpath, dev, ino))

    if progress_cb:
        progress_cb("Verificando identidad criptografica BLAKE3...")

    full_buckets: dict[tuple[int, str], list[tuple[Path, int, int]]] = defaultdict(list)
    for (size, _), items in partial_buckets.items():
        if len(items) < 2:
            continue
        for fpath, dev, ino in items:
            fh = _full_blake3(fpath)
            if fh is not None:
                full_buckets[(size, fh)].append((fpath, dev, ino))

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
    moved = 0
    skipped = 0
    freed = 0
    keep_resolved = keep_path.resolve()

    for p in group.paths:
        if p.resolve() == keep_resolved:
            continue
        ok, _, _ = vault.quarantine_path(p, category="Duplicado BLAKE3")
        if ok:
            moved += 1
            freed += group.size_bytes
        else:
            skipped += 1
    return {"moved": moved, "skipped": skipped, "freed_bytes": freed}


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
