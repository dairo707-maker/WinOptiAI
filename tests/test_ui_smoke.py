"""Smoke test for Obsidian Acrylic UI startup, embedded fonts, SVG icons, and 4 views."""

from __future__ import annotations

import os
import time

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from winoptiai.ui.main_window import MainWindow
from winoptiai.ui.theme import build_obsidian_qss, register_embedded_fonts


def test_ui_instantiation_and_embedded_fonts() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])

    t0 = time.perf_counter()
    register_embedded_fonts(app)
    app.setStyleSheet(build_obsidian_qss())

    families = set(QFontDatabase.families())
    assert "Instrument Sans" in families
    assert "IBM Plex Mono" in families

    win = MainWindow()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert win.stack.count() == 4
    assert elapsed_ms < 2500.0

    # Verify switching through all 4 views raises no errors
    for idx in range(4):
        win._switch_tab(idx)
        assert win.stack.currentIndex() == idx

    win._force_quit = True
    win.close()
    win.pool.waitForDone(5000)
