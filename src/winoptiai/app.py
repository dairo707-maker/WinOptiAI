"""Application entry point with fluid startup and single-instance awareness."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow
from .ui.svg_icons import load_svg_icon
from .ui.theme import build_obsidian_qss, register_embedded_fonts


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("WinOptiAI")
    app.setQuitOnLastWindowClosed(False)

    register_embedded_fonts(app)
    app.setStyleSheet(build_obsidian_qss())
    app.setWindowIcon(load_svg_icon("brand", color="#E2E7ED", size=24))

    window = MainWindow()
    if "--minimized" not in sys.argv:
        window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
