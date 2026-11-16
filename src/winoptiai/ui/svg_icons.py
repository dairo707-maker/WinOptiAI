"""Centralized monochrome SVG icon loader for HiDPI crispness (zero emojis)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .. import get_base_dir


def _icons_dir() -> Path:
    return get_base_dir() / "assets" / "icons"


@lru_cache(maxsize=64)
def load_svg_icon(name: str, color: str = "#D8E0EA", size: int = 16) -> QIcon:
    """Render a named SVG icon from assets/icons/ tinted to the requested monochrome color."""
    svg_path = _icons_dir() / f"{name}.svg"
    if not svg_path.exists():
        return QIcon()

    svg_text = svg_path.read_text(encoding="utf-8").replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2.0)
    return QIcon(pixmap)


def load_svg_pixmap(name: str, color: str = "#D8E0EA", size: int = 16) -> QPixmap:
    """Return a HiDPI QPixmap rendered from an SVG asset."""
    return load_svg_icon(name, color=color, size=size).pixmap(size, size)
