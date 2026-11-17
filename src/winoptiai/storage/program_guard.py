"""Proteccion de programas y estructuras para Duplicados (v0.5.9).

Incidente 17/11/2026: "Autolimpiar" sobre todo el disco movio a Cuarentena decenas de miles de
copias identicas que NO sobraban: bibliotecas de Python (uv, Anaconda, Python 3.13), DLL de Qt,
drivers de audio, datos de Teams/Zoom/navegadores... Cada programa necesita su propia copia aunque
sea igual byte a byte. Reglas:

1. Nunca recorrer carpetas de sistema, programas, entornos de desarrollo ni configuracion
   (``AppData``, ``Program Files``, ``C:\\Drivers``, ``site-packages``, ``.venv``, ``node_modules``,
   carpetas ocultas ``.algo`` del perfil...).
2. Una carpeta con marcas de instalacion (``pyvenv.cfg``, ``conda-meta``, o un ``.exe`` junto a
   ``.dll``) se considera un programa completo y se omite entera.
3. "Carpetas copiadas": si dos carpetas comparten muchos archivos identicos (misma estructura),
   quitar archivos sueltos de una rompe esa copia. Esos grupos se marcan y nunca se proponen.
"""

from __future__ import annotations

from collections import defaultdict
import os
from pathlib import Path

PROGRAM_DIR_NAMES: frozenset[str] = frozenset(
    {
        "appdata", "program files", "program files (x86)", "programdata", "windows", "drivers",
        "$recycle.bin", "system volume information", "recovery", "msocache", "intel", "amd", "nvidia",
        "site-packages", "dist-packages", "node_modules", "bower_components", "vendor",
        "__pycache__", ".venv", "venv", "virtualenv", ".tox", ".nox",
        "anaconda3", "miniconda3", "miniforge3", "mambaforge", "conda", "pkgs", "envs",
        "scoop", "chocolatey", "winget", "steamapps", "epic games", "riot games",
    }
)

# Archivos que delatan una instalacion completa (se omite la carpeta entera).
INSTALL_MARKERS: frozenset[str] = frozenset({"pyvenv.cfg", "conda-meta", "python.exe", "unins000.exe", "uninstall.exe"})

EXE_EXTS = (".exe",)
LIB_EXTS = (".dll", ".pyd", ".so", ".node", ".sys")


def is_program_dir_name(name: str) -> bool:
    low = name.lower()
    # "_MEIxxxx": carpetas temporales de programas empaquetados con PyInstaller en ejecucion
    return low in PROGRAM_DIR_NAMES or (low.startswith(".") and len(low) > 1) or low.startswith("_mei")


def _segments_below(path: Path, base: Path | None) -> list[str]:
    parts = [p.lower() for p in path.parts]
    if base is None:
        return parts[1:]  # parts[0] es la unidad
    base_parts = [p.lower() for p in Path(base).parts]
    if parts[: len(base_parts)] == base_parts:
        return parts[len(base_parts):]
    return parts[1:]


def program_dir_reason(path: Path, entry_names: list[str] | None = None, base: Path | None = None) -> str:
    """Motivo por el que una carpeta es de programa/sistema ("" si es contenido del usuario).

    Con ``base`` (la carpeta que eligio el usuario) solo se evaluan las subcarpetas por debajo de
    ella: al analizar ``C:\\`` o el perfil se omiten ``AppData``, ``Program Files``...; si el usuario
    elige a proposito una carpeta concreta, se analiza, pero los programas dentro siguen protegidos.
    """
    for seg in _segments_below(path, base):
        if seg in PROGRAM_DIR_NAMES or seg.startswith("_mei"):
            return f"carpeta de programa/sistema ({seg})"
        if seg.startswith(".") and len(seg) > 1:
            return f"carpeta de configuracion ({seg})"
    if entry_names is not None:
        names = {n.lower() for n in entry_names}
        hit = names & INSTALL_MARKERS
        if hit:
            return f"instalacion ({sorted(hit)[0]})"
        has_exe = any(n.endswith(EXE_EXTS) for n in names)
        has_lib = any(n.endswith(LIB_EXTS) for n in names)
        if has_exe and has_lib:
            return "programa instalado (ejecutable con bibliotecas)"
    return ""


def find_mirrored_parents(
    groups_paths: list[list[Path]], min_shared: int = 3, min_ratio: float = 0.5
) -> set[frozenset[str]]:
    """Pares de carpetas que comparten muchos archivos identicos (copias de una misma estructura)."""
    pair_count: dict[frozenset[str], int] = defaultdict(int)
    for paths in groups_paths:
        parents = sorted({os.path.normcase(str(p.parent)) for p in paths})
        if len(parents) < 2 or len(parents) > 12:
            continue
        for i in range(len(parents)):
            for j in range(i + 1, len(parents)):
                pair_count[frozenset((parents[i], parents[j]))] += 1
    sizes: dict[str, int] = {}

    def _files_in(d: str) -> int:
        if d not in sizes:
            try:
                sizes[d] = sum(1 for e in os.scandir(d) if e.is_file(follow_symlinks=False))
            except OSError:
                sizes[d] = 0
        return sizes[d]

    mirrored: set[frozenset[str]] = set()
    for pair, shared in pair_count.items():
        if shared < min_shared:
            continue
        a, b = tuple(pair)
        smaller = max(1, min(_files_in(a), _files_in(b)))
        if shared / smaller >= min_ratio:
            mirrored.add(pair)
    return mirrored
