"""v0.6.5: pestanas en modo documento (Resumen y Arbol) sin franja blanca nativa en modo oscuro.

La franja la pinta el estilo nativo de Windows (windowsvista) solo con la plataforma real; bajo
QT_QPA_PLATFORM=offscreen no se reproduce, asi que la prueba de captura se omite ahi y la
prueba del QSS cubre el caso en cualquier entorno.
"""

from __future__ import annotations

import os
import re

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel, QTabWidget, QVBoxLayout, QWidget  # noqa: E402

from winoptiai.ui.theme import build_obsidian_qss, get_palette  # noqa: E402


def test_qss_disables_native_tab_base_and_paints_tabs():
    for mode in ("dark", "light"):
        qss = build_obsidian_qss(mode)
        assert "qproperty-drawBase: 0" in qss
        tab_rule = re.search(r"QTabBar::tab \{(.*?)\}", qss, flags=re.S).group(1)
        assert f"background-color: {get_palette(mode)['bg_glass']};" in tab_rule
        assert "transparent" not in tab_rule


def _native_platform() -> bool:
    app = QApplication.instance()
    platform = app.platformName() if app is not None else os.environ.get("QT_QPA_PLATFORM", "windows")
    return platform not in ("offscreen", "minimal")


@pytest.mark.parametrize(("mode", "bg", "dark_expected"), [("dark", "#0A0F1D", True), ("light", "#F8FAFC", False)])
def test_tab_bar_background_matches_theme(mode, bg, dark_expected):
    app = QApplication.instance() or QApplication([])
    if not _native_platform():
        pytest.skip("la base nativa de pestanas solo aparece con la plataforma real de Windows")
    host = QWidget()
    host.setObjectName("host")
    host.setStyleSheet(build_obsidian_qss(mode) + f"QWidget#host{{background:{bg};}}")
    lay = QVBoxLayout(host)
    tabs = QTabWidget()
    tabs.setDocumentMode(True)
    for t in ("Historial y Graficas", "Espacio liberado", "Registro"):
        tabs.addTab(QLabel("contenido"), t)
    lay.addWidget(tabs)
    host.resize(700, 120)
    host.show()
    app.processEvents()
    img = host.grab().toImage()
    bar_y = tabs.mapTo(host, tabs.tabBar().geometry().center()).y()
    color = img.pixelColor(660, bar_y)  # a la derecha de la ultima pestana, dentro de la barra
    host.close()
    if dark_expected:
        assert color.lightness() < 80, color.name()
    else:
        assert color.lightness() > 200, color.name()
