"""Smoke test for Obsidian/Alabaster Acrylic UI, theme/language toggle, sorting, and About dialog."""

from __future__ import annotations

import os
import time

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from winoptiai.ui.dialogs.about_updater_dialog import AboutUpdaterDialog
from winoptiai.ui.dialogs.notifications_drawer import NotificationsTasksDialog
from winoptiai.ui.main_window import MainWindow
from winoptiai.ui.theme import build_obsidian_qss, register_embedded_fonts


def test_ui_instantiation_themes_sorting_and_about() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])

    t0 = time.perf_counter()
    register_embedded_fonts(app)
    app.setStyleSheet(build_obsidian_qss("dark"))

    families = set(QFontDatabase.families())
    assert "Space Grotesk" in families
    assert "JetBrains Mono" in families
    assert "Instrument Sans" in families
    assert "IBM Plex Mono" in families

    win = MainWindow()
    try:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert win.stack.count() == 7  # v0.6.9: + Mantenimiento
        assert elapsed_ms < 4500.0

        # Verify sortable tables enabled across all 6 views
        assert win.overview_view.audit_table.isSortingEnabled()
        assert win.storage_view.table.isSortingEnabled()
        assert win.storage_view.format_table.isSortingEnabled()
        assert win.processes_view.proc_table.isSortingEnabled()
        assert win.thermal_view.rec_table.isSortingEnabled()
        assert win.apps_view.apps_table.isSortingEnabled()
        assert win.startup_view.startup_table.isSortingEnabled()

        # Switch tabs and storage modes cleanly
        for idx in range(7):
            win._switch_tab(idx)
            assert win.stack.currentIndex() == idx
        for mode in ("junk", "duplicates", "tree", "orphans", "quarantine"):
            win.storage_view._switch_mode(mode)

        # Toggle light theme and back to dark
        win._toggle_theme()
        assert win.policy.config.theme_mode in {"light", "dark"}
        win._toggle_theme()

        # Verify Explorer & Theme buttons are icon-only with tooltips
        assert win.storage_view.reveal_btn.text() == ""
        assert "Explorador" in win.storage_view.reveal_btn.toolTip()
        assert win.theme_btn.text() == ""
        assert win.theme_btn.toolTip()

        # Instantiate About & Notifications drawers
        dlg = AboutUpdaterDialog("es", win.policy.config.theme_mode, win._run_async, "Test PC", win)
        assert "WinOptiAI" in dlg.windowTitle()
        dlg.close()

        ndlg = NotificationsTasksDialog(
            win.notif_center,
            lambda: list(win._active_workers),
            win._switch_tab,
            win.policy.config.theme_mode,
            win,
        )
        assert "Notificaciones" in ndlg.windowTitle()
        ndlg.close()
    finally:
        win._force_quit = True
        win.close()
        win.pool.waitForDone(5000)
