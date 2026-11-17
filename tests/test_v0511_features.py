"""Tests for WinOptiAI v0.5.11: high-contrast tray & mode checks, guided tour, quick check, installer branding."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from winoptiai.core.onboarding_check import QuickCheckReport, run_new_pc_quick_check  # noqa: E402
from winoptiai.core.safety_guard import QuarantineVault  # noqa: E402
from winoptiai.core.sre_policy import SREPolicyConfig, SREPolicyEngine  # noqa: E402
from winoptiai.ui.dialogs.tour_dialog import QuickTourDialog  # noqa: E402
from winoptiai.ui.system_tray import WinOptiTray, build_high_contrast_tray_icon  # noqa: E402
from winoptiai.ui.theme import build_obsidian_qss, register_embedded_fonts  # noqa: E402
from winoptiai.ui.widgets import find_clipped_buttons  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    register_embedded_fonts(app)
    return app


def test_tray_high_contrast_icon_and_active_mode_checks(qapp: QApplication) -> None:
    light_ico = build_high_contrast_tray_icon(light_taskbar=True)
    dark_ico = build_high_contrast_tray_icon(light_taskbar=False)
    assert not light_ico.isNull()
    assert not dark_ico.isNull()
    assert len(light_ico.availableSizes()) >= 4

    host = QWidget()
    sre_calls: list[bool] = []
    theme_calls = 0

    def _on_theme() -> None:
        nonlocal theme_calls
        theme_calls += 1

    tray = WinOptiTray(
        host,
        on_show=lambda: None,
        on_boost=lambda: None,
        on_thermal=lambda _k: None,
        on_quit=lambda: None,
        on_toggle_sre=lambda flag: sre_calls.append(flag),
        on_toggle_theme=_on_theme,
        initial_thermal="cool",
        initial_sre=True,
        initial_theme="light",
    )
    assert tray._thermal_actions["cool"].isChecked()
    assert not tray._thermal_actions["balanced"].isChecked()
    assert "Frio" in tray.therm_menu.title()
    assert tray.sre_action.isChecked()
    assert tray.theme_action.isChecked()

    tray.sync_state(
        thermal_key="ai_local",
        sre_enabled=False,
        theme_mode="dark",
        task_summary="Escaneo de temporales (42%)",
    )
    assert tray._thermal_actions["ai_local"].isChecked()
    assert "IA Maxima" in tray.therm_menu.title()
    assert not tray.sre_action.isChecked()
    assert not tray.theme_action.isChecked()
    assert "42%" in tray.status_action.text()
    assert "SRE OFF" in tray.toolTip()

    tray.sre_action.toggle()
    tray.theme_action.trigger()
    assert sre_calls == [True]
    assert theme_calls == 1


def test_new_pc_quick_check_and_sre_calibration(tmp_path: Path) -> None:
    eng = SREPolicyEngine(app_dir=tmp_path / "app")
    assert eng.config.onboarding_completed is False
    vault = QuarantineVault(root_dir=tmp_path / "app")

    prog_events: list[int] = []
    report = run_new_pc_quick_check(
        policy=eng,
        vault=vault,
        progress_cb=lambda pct, _msg: prog_events.append(pct),
    )
    assert isinstance(report, QuickCheckReport)
    assert len(report.items) == 5
    cats = [it.category for it in report.items]
    assert "Memoria y Guardia SRE" in cats
    assert "BIOS/OEM, Seguridad y Reinicio" in cats
    assert eng.config.last_quick_check_at != ""
    assert 100 in prog_events

    # Config serialization preserves onboarding flag
    eng.config.onboarding_completed = True
    eng.save_config()
    reloaded = SREPolicyEngine(app_dir=tmp_path / "app")
    assert isinstance(reloaded.config, SREPolicyConfig)
    assert reloaded.config.onboarding_completed is True


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_guided_tour_navigation_and_zero_clipped_buttons(
    qapp: QApplication, tmp_path: Path, mode: str
) -> None:
    eng = SREPolicyEngine(app_dir=tmp_path / f"tour_{mode}")
    eng.config.theme_mode = mode
    eng.save_config()
    vault = QuarantineVault(root_dir=tmp_path / f"tour_{mode}")
    qapp.setStyleSheet(build_obsidian_qss(mode))

    tabs_visited: list[int] = []

    def _sync_run(fn, callback, *_a, **_kw) -> None:
        callback(fn())

    dlg = QuickTourDialog(
        policy=eng,
        vault=vault,
        run_async=_sync_run,
        on_switch_tab=lambda idx: tabs_visited.append(idx),
    )
    try:
        dlg.resize(640, 480)
        dlg.show()
        for _ in range(6):
            qapp.processEvents()
        assert find_clipped_buttons(dlg) == []

        # Walk through all 5 steps (Step 5 runs _sync_run -> renders 5 quick check cards)
        for _ in range(4):
            dlg._go_next()
            for _ in range(6):
                qapp.processEvents()
            assert find_clipped_buttons(dlg) == []

        assert tabs_visited == [0, 1, 2, 3, 0]
        assert dlg._last_report is not None
        assert len(dlg._last_report.items) == 5

        dlg._finish_tour()
        assert eng.config.onboarding_completed is True
    finally:
        dlg.close()


def test_installer_branding_assets_and_iss_refs() -> None:
    import sys

    root = Path(__file__).resolve().parents[1]
    scripts_dir = str(root / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import build_exe

    ico = build_exe.generate_app_icon()
    large_bmp, small_bmp = build_exe.generate_installer_wizard_images()
    assert ico.exists() and ico.stat().st_size > 1000
    assert large_bmp.exists()
    assert small_bmp.exists()

    with Image.open(large_bmp) as im_l:
        assert im_l.size == (164, 314)
    with Image.open(small_bmp) as im_s:
        assert im_s.size == (55, 58)

    iss = (root / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert "SetupIconFile=..\\assets\\icons\\winoptiai.ico" in iss
    assert "WizardImageFile=..\\assets\\icons\\wizard_large.bmp" in iss
    assert "WizardSmallImageFile=..\\assets\\icons\\wizard_small.bmp" in iss


def test_tour_dialog_deleted_before_async_check_finishes_does_not_raise(
    qapp: QApplication, tmp_path: Path
) -> None:
    """Regression test for GitHub Issue #1 (RuntimeError on deleted QPushButton)."""
    from PySide6.QtCore import Qt
    from shiboken6 import isValid as qt_is_valid

    eng = SREPolicyEngine(app_dir=tmp_path / "issue1")
    vault = QuarantineVault(root_dir=tmp_path / "issue1")
    captured: dict[str, object] = {}
    completed_reports: list[object] = []

    def _deferred_run(fn, callback, *_args, **kwargs) -> None:
        captured["fn"] = fn
        captured["callback"] = callback
        captured["progress"] = kwargs.get("progress_ui_cb")
        captured["on_error"] = kwargs.get("on_error")

    dlg = QuickTourDialog(
        policy=eng,
        vault=vault,
        run_async=_deferred_run,
        on_switch_tab=lambda _i: None,
        on_completed=lambda rep: completed_reports.append(rep),
    )
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    dlg.show()
    for _ in range(4):
        dlg._go_next()
    for _ in range(4):
        qapp.processEvents()

    assert "callback" in captured
    # Close dialog while quick check is still pending -> triggers C++ WA_DeleteOnClose
    dlg.close()
    for _ in range(10):
        qapp.processEvents()
    assert not qt_is_valid(dlg)

    fake_report = QuickCheckReport(
        checked_at="2026-11-17 15:00:00",
        device_line="Test PC",
        recommended_threshold_gb=1.8,
        items=[],
    )
    # Late progress, completion, and error callbacks MUST NOT raise RuntimeError
    captured["progress"](50, "Mitad")  # type: ignore[misc]
    captured["callback"](fake_report)  # type: ignore[misc]
    captured["on_error"]("simulated error")  # type: ignore[misc]
    assert completed_reports == [fake_report]
    assert eng.config.onboarding_completed is True
