"""Hierarchical folder size analyzer and file-type/extension breakdown.

Respects OneDrive Cloud-Only attributes and system path guardrails while building:
- FolderNode tree sorted descending by true disk footprint
- FormatBreakdown rows grouped by semantic category and file extension
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Callable

from ..core.safety_guard import is_protected_path
from ..core.task_control import TaskCanceledError, TaskController
from ..core.win32_bridge import attrs_is_cloud_only, attrs_is_reparse_or_system


EXTENSION_CATEGORIES: dict[str, str] = {
    ".mp4": "Video",
    ".mkv": "Video",
    ".avi": "Video",
    ".mov": "Video",
    ".webm": "Video",
    ".gguf": "Modelos IA / Binarios",
    ".safetensors": "Modelos IA / Binarios",
    ".onnx": "Modelos IA / Binarios",
    ".bin": "Modelos IA / Binarios",
    ".pt": "Modelos IA / Binarios",
    ".pth": "Modelos IA / Binarios",
    ".zip": "Archivos Comprimidos",
    ".rar": "Archivos Comprimidos",
    ".7z": "Archivos Comprimidos",
    ".tar": "Archivos Comprimidos",
    ".gz": "Archivos Comprimidos",
    ".exe": "Instaladores y Ejecutables",
    ".msi": "Instaladores y Ejecutables",
    ".iso": "Instaladores y Ejecutables",
    ".msix": "Instaladores y Ejecutables",
    ".pdf": "Documentos",
    ".docx": "Documentos",
    ".xlsx": "Documentos",
    ".pptx": "Documentos",
    ".csv": "Datos y Codigo",
    ".json": "Datos y Codigo",
    ".parquet": "Datos y Codigo",
    ".sqlite": "Datos y Codigo",
    ".db": "Datos y Codigo",
    ".png": "Imagenes",
    ".jpg": "Imagenes",
    ".jpeg": "Imagenes",
    ".webp": "Imagenes",
    ".psd": "Imagenes",
    ".wav": "Audio",
    ".mp3": "Audio",
    ".flac": "Audio",
}


@dataclass(slots=True)
class FolderNode:
    """Tree node representing a folder's recursive byte usage."""

    name: str
    path: Path
    size_bytes: int = 0
    file_count: int = 0
    children: list[FolderNode] = field(default_factory=list)


@dataclass(slots=True)
class FormatGroup:
    """Aggregated storage usage for a file extension and semantic category."""

    extension: str
    category: str
    file_count: int
    total_bytes: int
    heaviest_file: Path | None
    heaviest_bytes: int


@dataclass(slots=True)
class StorageHierarchyReport:
    """Combined folder hierarchy and file-format breakdown."""

    root_node: FolderNode
    formats: list[FormatGroup]
    heaviest_files: list[tuple[Path, str, int]]


def _categorize_ext(ext: str) -> str:
    return EXTENSION_CATEGORIES.get(ext.lower(), "Otros")


def analyze_storage_hierarchy(
    root: Path,
    max_depth: int = 4,
    top_formats: int = 40,
    progress_cb: Callable[[int, str], None] | None = None,
    controller: TaskController | None = None,
) -> StorageHierarchyReport:
    """Analyze folder hierarchy and file-type distribution safely."""
    resolved = root.resolve()
    ext_totals: dict[str, int] = defaultdict(int)
    ext_counts: dict[str, int] = defaultdict(int)
    ext_heaviest: dict[str, tuple[Path, int]] = {}
    all_heavy: list[tuple[Path, str, int]] = []
    top_entries: list[str] = []
    try:
        top_entries = [e.name for e in os.scandir(resolved)]
    except OSError:
        pass
    total_top = max(1, len(top_entries))
    done_top = 0

    def _walk_dir(current: Path, depth: int) -> FolderNode:
        nonlocal done_top
        if controller is not None and controller.checkpoint() == "cancel":
            raise TaskCanceledError("Analisis de arbol cancelado por el usuario")
        node = FolderNode(name=current.name or str(current), path=current)
        if not current.exists() or is_protected_path(current):
            return node

        try:
            entries = list(os.scandir(current))
        except OSError:
            return node

        for entry in entries:
            if depth == 0:
                done_top += 1
                if progress_cb:
                    progress_cb(min(92, int(done_top * 90 / total_top)), f"Analizando {entry.name}...")
            ep = Path(entry.path)
            try:
                st = entry.stat(follow_symlinks=False)
                attrs = getattr(st, "st_file_attributes", None)
                if attrs_is_cloud_only(attrs) or attrs_is_reparse_or_system(attrs):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if is_protected_path(ep):
                        continue
                    child = _walk_dir(ep, depth + 1)
                    node.size_bytes += child.size_bytes
                    node.file_count += child.file_count
                    if depth < max_depth and child.size_bytes > 0:
                        node.children.append(child)
                elif entry.is_file(follow_symlinks=False):
                    sz = int(st.st_size)
                    node.size_bytes += sz
                    node.file_count += 1

                    ext = ep.suffix.lower() or "(sin ext)"
                    ext_totals[ext] += sz
                    ext_counts[ext] += 1
                    prev = ext_heaviest.get(ext)
                    if prev is None or sz > prev[1]:
                        ext_heaviest[ext] = (ep, sz)
                    if sz >= 5 * 1024 * 1024:
                        all_heavy.append((ep, ext, sz))
            except OSError:
                continue

        node.children.sort(key=lambda c: c.size_bytes, reverse=True)
        return node

    root_node = _walk_dir(resolved, 0)

    formats: list[FormatGroup] = []
    for ext, total in ext_totals.items():
        heavy_path, heavy_sz = ext_heaviest.get(ext, (None, 0))
        formats.append(
            FormatGroup(
                extension=ext,
                category=_categorize_ext(ext),
                file_count=ext_counts[ext],
                total_bytes=total,
                heaviest_file=heavy_path,
                heaviest_bytes=heavy_sz,
            )
        )
    formats.sort(key=lambda f: f.total_bytes, reverse=True)
    all_heavy.sort(key=lambda x: x[2], reverse=True)

    return StorageHierarchyReport(
        root_node=root_node,
        formats=formats[:top_formats],
        heaviest_files=all_heavy[:100],
    )
