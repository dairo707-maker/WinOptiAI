"""WinOptiAI v0.5.14: tooltips explicativos 0px, franja desplegable por seccion y Manual de Uso en Acerca de."""

from __future__ import annotations

import os
from pathlib import Path
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from winoptiai.core.help_catalog import (  # noqa: E402
    MANUAL_SECTIONS,
    SECTION_BENEFITS,
    TOOLTIPS,
)
from winoptiai.ui.dialogs.about_updater_dialog import AboutUpdaterDialog  # noqa: E402
from winoptiai.ui.main_window import MainWindow  # noqa: E402
from winoptiai.ui.theme import build_obsidian_qss, register_embedded_fonts  # noqa: E402
from winoptiai.ui.widgets import SectionBenefitStrip, find_clipped_buttons  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    register_embedded_fonts(app)
    return app


def _pump(app: QApplication, n: int = 6) -> None:
    for _ in range(n):
        app.processEvents()


def test_help_catalog_completeness_and_no_emojis() -> None:
    emoji_re = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")

    assert len(TOOLTIPS) >= 35
    for key, text in TOOLTIPS.items():
        assert text.strip(), f"Tooltip vacio para {key}"
        assert not emoji_re.search(text), f"Emoji prohibido en tooltip {key}"

    expected_sections = {
        "overview",
        "storage_junk",
        "storage_duplicates",
        "storage_tree",
        "storage_orphans",
        "storage_quarantine",
        "storage_onedrive",
        "processes",
        "thermal",
    }
    assert expected_sections.issubset(set(SECTION_BENEFITS.keys()))
    for key, benefit in SECTION_BENEFITS.items():
        assert benefit["title"].strip()
        assert benefit["improves"].strip()
        assert benefit["safety"].strip()
        joined = f"{benefit['title']} {benefit['improves']} {benefit['safety']}"
        assert not emoji_re.search(joined), f"Emoji prohibido en SECTION_BENEFITS[{key}]"

    assert len(MANUAL_SECTIONS) == 7
    for sec in MANUAL_SECTIONS:
        assert sec["id"].strip()
        assert sec["title"].strip()
        assert len(sec["body"].strip()) > 80
        assert not emoji_re.search(f"{sec['title']} {sec['body']}"), f"Emoji prohibido en manual {sec['id']}"


def test_qtooltip_qss_zero_radius_both_themes() -> None:
    for theme in ("dark", "light"):
        qss = build_obsidian_qss(theme)
        assert "QToolTip" in qss
        idx = qss.index("QToolTip")
        block = qss[idx : idx + 350]
        assert "border-radius: 0px;" in block


def test_section_benefit_strip_collapsed_and_dynamic(qapp: QApplication) -> None:
    qapp.setStyleSheet(build_obsidian_qss("dark"))
    strip = SectionBenefitStrip("storage_junk")
    strip.show()
    _pump(qapp)

    assert not strip._expanded
    assert not strip.body_widget.isVisible()
    assert strip.toggle_btn.text() == "Ver que mejora"

    strip.toggle_btn.click()
    _pump(qapp)
    assert strip._expanded
    assert strip.body_widget.isVisible()
    assert strip.toggle_btn.text() == "Ocultar"

    for mode in ("junk", "duplicates", "tree", "orphans", "quarantine", "onedrive"):
        key = f"storage_{mode}"
        strip.set_section(key)
        assert SECTION_BENEFITS[key]["title"] in strip.title_lbl.text()
        assert SECTION_BENEFITS[key]["improves"] in strip.improves_lbl.text()

    strip.close()


def test_about_dialog_tabs_manual_navigation_and_no_clipping(qapp: QApplication) -> None:
    for theme in ("dark", "light"):
        qapp.setStyleSheet(build_obsidian_qss(theme))
        dlg = AboutUpdaterDialog(
            lang="es",
            theme_mode=theme,
            run_async=lambda *a, **kw: None,
            hardware_summary="Test CPU / 16 GB RAM",
            on_open_diagnostics=lambda: None,
            on_open_tour=lambda: None,
        )
        dlg.show()
        _pump(qapp)

        assert dlg.tabs.count() == 2
        assert "Acerca de" in dlg.tabs.tabText(0)
        assert "Manual" in dlg.tabs.tabText(1)
        assert dlg.check_btn.toolTip().strip()
        assert dlg.install_btn.toolTip().strip()
        assert find_clipped_buttons(dlg) == []

        # Switch to Manual tab and click every chapter button
        dlg.tabs.setCurrentIndex(1)
        _pump(qapp)
        assert len(dlg.manual_buttons) == len(MANUAL_SECTIONS)
        for sec in MANUAL_SECTIONS:
            dlg.manual_buttons[sec["id"]].click()
            _pump(qapp)
            assert dlg.manual_title_lbl.text() == sec["title"]
            assert sec["body"][:40] in dlg.manual_box.toPlainText()
        assert find_clipped_buttons(dlg) == []
        dlg.close()


def test_main_window_tooltips_and_benefit_strips_wired(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    qapp.setStyleSheet(build_obsidian_qss("dark"))
    win = MainWindow()
    win.resize(980, 650)
    win.show()
    _pump(qapp)

    try:
        # Sidebar & TopBar tooltips
        for btn in win.nav_buttons:
            assert btn.toolTip().strip()
        widgets_to_check = [
            win.lang_combo,
            win.tour_btn,
            win.about_btn,
            win.task_pill_btn,
            win.pause_top_btn,
            win.save_pause_top_btn,
            win.cancel_top_btn,
            win.resume_session_btn,
            win.bell_btn,
        ]
        if hasattr(win, "uac_btn"):
            widgets_to_check.append(win.uac_btn)
        for w in widgets_to_check:
            assert w.toolTip().strip(), f"Falta tooltip en {w.objectName() or type(w).__name__}"

        # Overview
        assert win.overview_view.boost_btn.toolTip().strip()
        assert not win.overview_view.benefit_strip._expanded

        # Storage (all 6 modes update dynamic benefit strip + tooltips)
        win._switch_tab(1)
        _pump(qapp)
        assert win.storage_view.primary_btn.toolTip().strip()
        assert win.storage_view.secondary_btn.toolTip().strip()
        assert win.storage_view.select_all_chk.toolTip().strip()
        assert win.storage_view.reveal_btn.toolTip().strip()
        for mode in ("junk", "duplicates", "tree", "orphans", "quarantine", "onedrive"):
            win.storage_view._switch_mode(mode)
            _pump(qapp)
            assert win.storage_view.mode_buttons[mode].toolTip().strip()
            assert SECTION_BENEFITS[f"storage_{mode}"]["title"] in win.storage_view.benefit_strip.title_lbl.text()
            assert find_clipped_buttons(win) == []

        # Processes
        win._switch_tab(2)
        _pump(qapp)
        assert win.processes_view.boost_btn.toolTip().strip()
        assert win.processes_view.kill_zombie_btn.toolTip().strip()
        assert not win.processes_view.benefit_strip._expanded
        assert find_clipped_buttons(win) == []

        # Thermal & BIOS
        win._switch_tab(3)
        _pump(qapp)
        assert win.thermal_view.audit_btn.toolTip().strip()
        assert win.thermal_view.reset_pwr_btn.toolTip().strip()
        for pbtn in win.thermal_view.profile_buttons.values():
            assert pbtn.toolTip().strip()
        assert not win.thermal_view.benefit_strip._expanded
        assert find_clipped_buttons(win) == []
    finally:
        win.close()
        _pump(qapp)
