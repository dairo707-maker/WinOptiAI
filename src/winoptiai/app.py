"""Application entry point with fluid startup, embedded fonts, persisted theme and crash guard."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .core.crash_guard import CrashGuard
from .core.sre_policy import SREPolicyEngine
from .ui.main_window import MainWindow
from .ui.svg_icons import load_svg_icon
from .ui.theme import build_obsidian_qss, register_embedded_fonts


def main() -> int:
    # v0.5.1: telemetria post-mortem local antes de crear cualquier objeto Qt.
    crash_guard = CrashGuard()
    crash_guard.install()
    crash_guard.begin_session()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("WinOptiAI")
    app.setQuitOnLastWindowClosed(False)
    crash_guard.install_qt_message_handler()
    app.aboutToQuit.connect(crash_guard.mark_clean_exit)

    policy = SREPolicyEngine()
    register_embedded_fonts(app)
    app.setStyleSheet(build_obsidian_qss(policy.config.theme_mode))
    app.setWindowIcon(load_svg_icon("brand", color="#E2E7ED", size=24))

    window = MainWindow(crash_guard=crash_guard)
    if "--minimized" not in sys.argv:
        window.show()

    code = app.exec()
    crash_guard.mark_clean_exit()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
