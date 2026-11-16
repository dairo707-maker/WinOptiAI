"""WinOptiAI: Gestor nativo de almacenamiento, optimizacion de procesos para IA y control termico en Windows 11."""

from __future__ import annotations

from pathlib import Path
import sys


def get_base_dir() -> Path:
    """Return the runtime root directory (supports source tree and PyInstaller one-file bundle)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent.parent


def get_version() -> str:
    """Read semantic version from the bundled VERSION file."""
    version_file = get_base_dir() / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return "0.1.0"


__version__ = get_version()
