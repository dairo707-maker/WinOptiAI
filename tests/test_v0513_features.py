"""Tests for WinOptiAI v0.5.13: automatic update notification, deduplication, tray & preloaded About."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from winoptiai.core.sre_policy import SREPolicyConfig, SREPolicyEngine  # noqa: E402
from winoptiai.core.updater import ReleaseInfo  # noqa: E402
from winoptiai.ui.dialogs.about_updater_dialog import AboutUpdaterDialog  # noqa: E402
from winoptiai.ui.main_window import MainWindow  # noqa: E402
from winoptiai.ui.theme import build_obsidian_qss, register_embedded_fonts  # noqa: E402
from winoptiai.ui.widgets import find_clipped_buttons  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    register_embedded_fonts(app)
    return app


def test_sre_config_auto_update_defaults_and_persistence(tmp_path: Path) -> None:
    eng = SREPolicyEngine(app_dir=tmp_path)
    assert eng.config.auto_check_updates is True
    assert eng.config.last_notified_version == ""

    eng.config.last_notified_version = "0.6.0"
    eng.save_config()
    reloaded = SREPolicyEngine(app_dir=tmp_path)
    assert isinstance(reloaded.config, SREPolicyConfig)
    assert reloaded.config.last_notified_version == "0.6.0"


def test_background_update_notification_dedupes_and_syncs_badges(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    qapp.setStyleSheet(build_obsidian_qss("dark"))
    win = MainWindow()
    try:
        assert not win.tray.update_action.isVisible()

        fake_release = ReleaseInfo(
            tag="v0.9.9",
            version="0.9.9",
            notes="Correcciones y mejoras de prueba.",
            html_url="https://github.com/dairo707-maker/WinOptiAI/releases/tag/v0.9.9",
            setup_url="https://github.com/dairo707-maker/WinOptiAI/releases/download/v0.9.9/WinOptiAI-Setup.exe",
            checksums_url=None,
            update_available=True,
        )

        # First detection notifies once, updates sidebar button + tray menu
        notified_first = win._handle_update_check_result(True, fake_release)
        assert notified_first is True
        assert win.policy.config.last_notified_version == "0.9.9"
        assert "v0.9.9" in win.about_btn.text()
        assert win.tray.update_action.isVisible()
        assert "v0.9.9" in win.tray.update_action.text()
        unread_after_first = win.notif_center.unread_count()
        assert unread_after_first >= 1

        # Second detection for same version must NOT push a duplicate notification
        notified_second = win._handle_update_check_result(True, fake_release)
        assert notified_second is False
        assert win.notif_center.unread_count() == unread_after_first
        assert find_clipped_buttons(win) == []

        # Opening AboutUpdaterDialog with preloaded release renders notes + Install button immediately
        dlg = AboutUpdaterDialog(
            lang="es",
            theme_mode="dark",
            run_async=lambda *_a, **_kw: None,
            hardware_summary="Test Hardware",
            preloaded_release=win._available_update,
            parent=win,
        )
        try:
            dlg.show()
            for _ in range(4):
                qapp.processEvents()
            assert dlg.install_btn.isVisible()
            assert find_clipped_buttons(dlg) == []
            assert "v0.9.9" in dlg.notes_box.toPlainText()
            assert "v0.9.9" in dlg.status_lbl.text()
        finally:
            dlg.close()
    finally:
        win._force_quit = True
        win.close()
        win.pool.waitForDone(5000)
