"""v0.6.5: icono real de cada aplicacion (16 px, opacidad ~85%) para la tabla de Aplicaciones.

Se pide a Windows (``QFileIconProvider`` = icono del shell, el mismo del Explorador) desde el
archivo de ``DisplayIcon`` o el .exe principal de la carpeta de instalacion. Nunca se lee un
archivo que solo este en la nube (OneDrive Files On-Demand) y todo queda en cache por ruta.
"""

from __future__ import annotations

from PySide6.QtCore import QFileInfo, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QFileIconProvider

from ..apps.app_manager import InstalledApp, guess_app_icon_path, is_local_disk_path
from ..core.win32_bridge import is_cloud_only_file

ICON_PX = 16
ICON_OPACITY = 0.85

_cache: dict[str, QIcon] = {}
_guessed: set[str] = set()  # apps ya buscadas (no reescanear la carpeta en cada repintado)
_provider: list[QFileIconProvider] = []


def _blank_icon() -> QIcon:
    key = "__blank__"
    if key not in _cache:
        pm = QPixmap(ICON_PX, ICON_PX)
        pm.fill(Qt.GlobalColor.transparent)
        _cache[key] = QIcon(pm)
    return _cache[key]


def _soften(icon: QIcon, dpr: float) -> QIcon:
    size = int(round(ICON_PX * dpr))
    src = icon.pixmap(QSize(size, size))
    if src.isNull():
        return QIcon()
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setOpacity(ICON_OPACITY)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawPixmap(0, 0, size, size, src)
    painter.end()
    out.setDevicePixelRatio(dpr)
    return QIcon(out)


def icon_for_path(path: str, dpr: float = 1.0) -> QIcon:
    """Icono suavizado del archivo; icono transparente si no hay o no es seguro leerlo."""
    if not path:
        return _blank_icon()
    key = f"{path.lower()}@{dpr:.2f}"
    cached = _cache.get(key)
    if cached is not None:
        return cached
    icon = QIcon()
    try:
        if is_local_disk_path(path) and not is_cloud_only_file(path):
            if not _provider:
                _provider.append(QFileIconProvider())
            icon = _soften(_provider[0].icon(QFileInfo(path)), dpr)
    except Exception:  # noqa: BLE001 - un icono nunca debe romper la tabla
        icon = QIcon()
    if icon.isNull():
        icon = _blank_icon()
    _cache[key] = icon
    return icon


def blank_icon() -> QIcon:
    return _blank_icon()


def cached_app_icon(app: InstalledApp, dpr: float = 1.0) -> QIcon | None:
    """Icono ya cargado (sin tocar disco) o None si falta cargarlo con ``app_icon``."""
    if not app.icon_path:
        return _blank_icon() if app.app_id in _guessed else None
    return _cache.get(f"{app.icon_path.lower()}@{dpr:.2f}")


def app_icon(app: InstalledApp, dpr: float = 1.0) -> QIcon:
    if not app.icon_path and app.app_id not in _guessed:
        _guessed.add(app.app_id)
        app.icon_path = guess_app_icon_path(app)
    return icon_for_path(app.icon_path, dpr)
