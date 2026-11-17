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
import time
from pathlib import Path
from typing import Callable

from blake3 import blake3

from ..core.safety_guard import QuarantineVault, is_protected_path, is_safe_to_touch_file
from ..core.task_control import TaskCanceledError, TaskController, stop_point
from .program_guard import find_mirrored_parents, is_program_dir_name, program_dir_reason
from ..core.win32_bridge import (
    attrs_skip_entry,
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
    # v0.5.9: motivo por el que el grupo NO debe tocarse (p. ej. "carpeta copiada"); "" = seguro
    protected_reason: str = ""


class DuplicateResults(list):
    """Lista de grupos + estadisticas de proteccion (v0.5.9)."""

    def __init__(self, groups=(), protected_dirs: int = 0, structural_groups: int = 0) -> None:
        super().__init__(groups)
        self.protected_dirs = protected_dirs
        self.structural_groups = structural_groups


class HashCache:
    """v0.5.9 (microprocesos): huellas BLAKE3 ya calculadas, por (ruta, tamano, fecha de modificacion).

    Se guardan cada ``commit_every`` archivos; si el analisis se cancela, se guarda la pausa o la
    app se cierra, lo calculado sirve para la siguiente vez y solo se procesan archivos nuevos o
    modificados. Vive en ``%LOCALAPPDATA%\\WinOptiAI\\hash_cache.sqlite`` (excluida de escaneos).
    """

    def __init__(self, path: Path | None = None, commit_every: int = 200) -> None:
        import sqlite3

        from ..core.safety_guard import default_app_data_dir

        self.path = path or (default_app_data_dir() / "hash_cache.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS h (path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, "
            "partial TEXT, full TEXT, seen INTEGER)"
        )
        self._pending = 0
        self._commit_every = commit_every
        self.hits = 0
        self.misses = 0

    def _row(self, path: Path, size: int, mtime_ns: int):
        cur = self._db.execute("SELECT size, mtime, partial, full FROM h WHERE path = ?", (os.path.normcase(str(path)),))
        row = cur.fetchone()
        if row and row[0] == size and row[1] == mtime_ns:
            return row
        return None

    def get(self, path: Path, size: int, mtime_ns: int, kind: str) -> str | None:
        row = self._row(path, size, mtime_ns)
        value = (row[2] if kind == "partial" else row[3]) if row else None
        if value:
            self.hits += 1
        else:
            self.misses += 1
        return value or None

    def put(self, path: Path, size: int, mtime_ns: int, kind: str, value: str) -> None:
        key = os.path.normcase(str(path))
        now = int(time.time())
        row = self._row(path, size, mtime_ns)
        partial = value if kind == "partial" else (row[2] if row else None)
        full = value if kind == "full" else (row[3] if row else None)
        self._db.execute(
            "INSERT OR REPLACE INTO h (path, size, mtime, partial, full, seen) VALUES (?, ?, ?, ?, ?, ?)",
            (key, size, mtime_ns, partial, full, now),
        )
        self._pending += 1
        if self._pending >= self._commit_every:
            self.commit()

    def commit(self) -> None:
        try:
            self._db.commit()
        except Exception:  # noqa: BLE001
            pass
        self._pending = 0

    def prune(self, max_age_days: int = 120) -> None:
        self._db.execute("DELETE FROM h WHERE seen < ?", (int(time.time()) - max_age_days * 86400,))
        self.commit()

    def close(self) -> None:
        self.commit()
        try:
            self._db.close()
        except Exception:  # noqa: BLE001
            pass


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _cached(cache: "HashCache | None", path: Path, size: int, kind: str, compute) -> str | None:
    if cache is None:
        return compute()
    mt = _mtime_ns(path)
    hit = cache.get(path, size, mt, kind)
    if hit:
        return hit
    value = compute()
    if value:
        cache.put(path, size, mt, kind, value)
    return value


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
    protect_programs: bool = True,
    cache: "HashCache | None" = None,
) -> list[DuplicateGroup]:
    """Buscar duplicados exactos. Con ``cache`` las huellas se guardan aunque el analisis se corte."""
    try:
        return _find_duplicates_impl(roots, min_size_bytes, progress_cb, controller, protect_programs, cache)
    finally:
        if cache is not None:
            cache.commit()  # v0.5.9: lo calculado se conserva tambien al cancelar o guardar pausa


def _find_duplicates_impl(
    roots: list[Path],
    min_size_bytes: int = 1024,
    progress_cb: Callable[[int, str], None] | None = None,
    controller: TaskController | None = None,
    protect_programs: bool = True,
    cache: "HashCache | None" = None,
) -> list[DuplicateGroup]:
    """Scan roots and return groups of true duplicate files (excluding existing hardlinks).

    v0.5.9: ``protect_programs`` omite programas/entornos/sistema y marca "carpetas copiadas".
    """
    size_buckets: dict[int, list[tuple[Path, int, int]]] = defaultdict(list)

    if progress_cb:
        progress_cb(8, "Indexando archivos y tamanos...")

    protected_dirs = 0
    for root in roots:
        if not root.exists() or is_protected_path(root):
            continue
        stack: list[Path] = [root]
        while stack:
            stop_point(controller, "Busqueda de duplicados cancelada por el usuario")
            current = stack.pop()
            if is_protected_path(current):
                continue
            try:
                with os.scandir(current) as it:
                    entries = list(it)
            except OSError:
                continue
            # v0.5.9: carpetas de programas, entornos e instalaciones completas nunca se recorren.
            if protect_programs and program_dir_reason(current, [e.name for e in entries], base=root):
                protected_dirs += 1
                continue
            for entry in entries:
                ep = Path(entry.path)
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                attrs = getattr(st, "st_file_attributes", None)
                is_dir = entry.is_dir(follow_symlinks=False)
                if attrs_skip_entry(attrs, is_dir):  # v0.5.4: carpetas OneDrive "unpinned"
                    continue
                if is_dir:
                    if protect_programs and is_program_dir_name(entry.name):
                        protected_dirs += 1
                        continue
                    if not entry.name.startswith(".git") and entry.name != "__pycache__":
                        stack.append(ep)
                elif entry.is_file(follow_symlinks=False) and st.st_size >= min_size_bytes:
                    size_buckets[st.st_size].append((ep, st.st_dev, st.st_ino))

    if progress_cb:
        progress_cb(40, "Calculando pre-hash 4KB de candidatos...")

    candidate_sizes = [(sz, items) for sz, items in size_buckets.items() if len(items) >= 2]
    partial_buckets: dict[tuple[int, str], list[tuple[Path, int, int]]] = defaultdict(list)
    total_cand = max(1, len(candidate_sizes))
    for idx, (size, raw_items) in enumerate(candidate_sizes, start=1):
        if idx % 10 == 0:
            stop_point(controller, "Busqueda de duplicados cancelada por el usuario")
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
            ph = _cached(cache, fpath, size, "partial", lambda fp=fpath, sz=size: _partial_hash(fp, sz))
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
        stop_point(controller, "Verificacion BLAKE3 cancelada por el usuario")
        for fpath, dev, ino in items:
            fh = _cached(cache, fpath, size, "full", lambda fp=fpath: _full_blake3(fp))
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
    structural = 0
    if protect_programs and groups:
        # v0.5.9: dos carpetas con la misma estructura (muchos archivos identicos) = copia completa.
        # Quitar archivos sueltos de una de ellas la romperia: esos grupos nunca se proponen.
        mirrored = find_mirrored_parents([g.paths for g in groups])
        if mirrored:
            for g in groups:
                parents = sorted({os.path.normcase(str(p.parent)) for p in g.paths})
                if any(frozenset((a, b)) in mirrored for i, a in enumerate(parents) for b in parents[i + 1 :]):
                    g.protected_reason = "Carpeta copiada (misma estructura): no se separan sus archivos"
                    structural += 1
    return DuplicateResults(groups, protected_dirs=protected_dirs, structural_groups=structural)


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
    controller: TaskController | None = None,
) -> dict[str, int]:
    """Batch-quarantine redundant duplicate copies across multiple groups in O(N) time."""
    entries: list[tuple[Path, str]] = []
    for _, _, remove_paths in plan:
        for rp in remove_paths:
            entries.append((rp, "Duplicado BLAKE3"))
    return vault.quarantine_many(entries, progress_cb=progress_cb, controller=controller)


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

    # v0.5.2: re-verificar contenido justo antes de sustituir. El hardlink borra de forma
    # definitiva la copia (no pasa por Cuarentena); si el archivo cambio desde el escaneo
    # se perderian datos unicos.
    if keep_resolved.stat().st_size != group.size_bytes or _full_blake3(keep_resolved) != group.digest:
        return {"linked": 0, "skipped": len(group.paths) - 1, "freed_bytes": 0}

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
            if p.stat().st_size != group.size_bytes or _full_blake3(p) != group.digest:
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
        if getattr(grp, "protected_reason", ""):
            continue  # v0.5.9: carpetas copiadas / programas -> nunca se proponen
        # v0.5.9: defensa adicional por si el grupo vino de una version previa o de otra fuente:
        # las copias dentro de programas/entornos se conservan siempre.
        # Siempre se conserva al menos una copia del usuario (aunque exista otra dentro de un programa).
        try:
            base = Path(os.path.commonpath([str(p.parent) for p in grp.paths]))
        except ValueError:  # rutas en unidades distintas
            base = None
        movable = [p for p in grp.paths if not program_dir_reason(p.parent, base=base)]
        if len(movable) < 2:
            continue
        keep = choose_primary_copy(movable, rule=rule)
        remove = [p for p in movable if p != keep]
        if remove:
            plan.append((grp, keep, remove))
    return plan
