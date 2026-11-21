"""Tests for WinOptiAI v0.6.1 UI polish: health gauges light palette, chart margins, typography, and tray."""

from __future__ import annotations

import os
from pathlib import Path
import time

from PySide6.QtGui import QFont, QFontMetrics, QPixmap
from PySide6.QtWidgets import QApplication, QWidget
import pytest

from winoptiai.core.metrics_history import AuditEvent, FREED_TEMP, FREED_DUPS, EVENT_CLEAN
from winoptiai.ui.fx import UndoToast
from winoptiai.ui.history_charts import (
    FreedSpaceChart,
    FreedSpacePanel,
    HistoryPanel,
    SystemGaugesWidget,
    TimeSeriesChart,
    _FreedLegend,
    css_qcolor,
)
from winoptiai.ui.main_window import MainWindow
from winoptiai.ui.system_tray import WinOptiTray
from winoptiai.ui.theme import MONO_FONT_FAMILY, UI_FONT_FAMILY, build_obsidian_qss, get_palette, register_embedded_fonts
from winoptiai.ui.widgets import SectionBenefitStrip, StatusTag


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    register_embedded_fonts(app)
    return app


def test_css_qcolor_and_light_mode_system_gauges(qapp: QApplication) -> None:
    col = css_qcolor("rgba(255, 255, 255, 240)")
    assert col.isValid()
    assert (col.red(), col.green(), col.blue(), col.alpha()) == (255, 255, 255, 240)

    gauges = SystemGaugesWidget(lambda: get_palette("light"))
    gauges.resize(230, 310)
    gauges.update_values(
        82, "warn", 46, "ok", 28, "ok", "ATENCION", "warn",
        details=("2.8 GB libres", "256 GB libres", "2.41 GHz"),
        fourth={"label": "TEMP. CPU", "pct": 64, "tone": "ok", "text": "64 C", "detail": "Normal"},
    )
    assert len(gauges._gauges) == 4
    assert [g["label"] for g in gauges._gauges] == ["RAM", "DISCO C:", "CPU", "TEMP. CPU"]

    pm = QPixmap(gauges.size())
    gauges.render(pm)
    img = pm.toImage()
    # Bottom center area should be crisp light paper/card background, never black (rgba fallback bug)
    c = img.pixelColor(gauges.width() // 2, gauges.height() - 8)
    assert c.red() > 200 and c.green() > 200 and c.blue() > 200
    gauges.close()


def test_charts_dynamic_left_margin_and_freed_legend_wrapping(qapp: QApplication) -> None:
    now = time.time()
    fm = QFontMetrics(QFont(MONO_FONT_FAMILY, 8))

    freed = FreedSpaceChart(lambda: get_palette("light"))
    freed.resize(520, 210)
    events = [
        AuditEvent(now - 7200, "user", "Limpieza Temporales", "12.68 GB", 12984.32, EVENT_CLEAN, FREED_TEMP),
        AuditEvent(now - 3600, "user", "Autolimpieza Duplicados", "25.50 GB", 26112.0, EVENT_CLEAN, FREED_DUPS),
    ]
    freed.set_data(events, now)
    left_f, right_f, top_f, axis_f, lab_h_f = freed._layout_metrics(fm)
    max_label_w = max(fm.horizontalAdvance(lab) for lab in ("38.18 GB", "43.91 GB"))
    assert left_f - 8.0 >= max_label_w
    assert top_f >= lab_h_f / 2.0 + 2.0
    assert axis_f >= fm.height() + 6
    assert right_f >= 12.0
    pm_f = QPixmap(freed.size())
    freed.render(pm_f)
    assert not pm_f.isNull()
    freed.close()

    ts_chart = TimeSeriesChart(lambda: get_palette("dark"))
    ts_chart.resize(460, 210)
    ts_chart.set_data([], [], now, 86400.0, 96.0)
    left_t, right_t, _top_t, _strip_t, axis_t, _lab_h_t = ts_chart._layout_metrics(fm)
    assert left_t - 8.0 >= fm.horizontalAdvance("128 GB")
    assert axis_t >= 18.0
    assert right_t >= 10.0
    pm_t = QPixmap(ts_chart.size())
    ts_chart.render(pm_t)
    assert not pm_t.isNull()
    ts_chart.close()

    legend = _FreedLegend(lambda: get_palette("light"))
    legend.set_totals({FREED_TEMP: 12984.32, FREED_DUPS: 14848.0})
    ui_fm = QFontMetrics(QFont(UI_FONT_FAMILY, 8))
    assert legend.minimumHeight() >= ui_fm.height() + 4
    assert legend.heightForWidth(240) > legend.heightForWidth(900)
    legend.close()


def test_typography_roles_qss_weights_and_tray_tooltip(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    for mode in ("dark", "light"):
        qss = build_obsidian_qss(mode)
        assert "font-weight: 600" not in qss
        assert "DemiBold" not in qss
        assert "QLabel#CardTitle" in qss
        assert "QLabel#BodyText" in qss
        assert "QLabel#Caption" in qss

    host = QWidget()
    tray = WinOptiTray(host, lambda: None, lambda: None, lambda _m: None, lambda: None)
    assert tray.toolTip() == "WinOptiAI"
    tray.hide()
    host.close()

    strip = SectionBenefitStrip("overview")
    assert strip.title_lbl.objectName() == "CardTitle"
    assert strip.improves_lbl.objectName() == "BodyText"
    assert strip.safety_lbl.objectName() == "BodyText"
    strip.close()

    tag = StatusTag("TRODAI SRE", "active")
    assert tag.sizePolicy().horizontalPolicy() == tag.sizePolicy().Policy.Fixed
    assert tag.sizePolicy().verticalPolicy() == tag.sizePolicy().Policy.Fixed
    tag.close()

    win = MainWindow()
    try:
        def _ancestor_names(widget: QWidget) -> set[str]:
            names: set[str] = set()
            cur = widget.parentWidget()
            while cur is not None:
                if cur.objectName():
                    names.add(cur.objectName())
                cur = cur.parentWidget()
            return names

        # v0.6.1: Theme + Language sit in TopBar; Mode badge + UAC elevation sit in Sidebar
        assert win.theme_btn.objectName() == "TopUtilityBtn"
        assert win.lang_combo.objectName() == "TopLangCombo"
        assert "TopBar" in _ancestor_names(win.theme_btn)
        assert "TopBar" in _ancestor_names(win.lang_combo)
        assert "Sidebar" in _ancestor_names(win.admin_tag)
        if hasattr(win, "uac_btn"):
            assert "Sidebar" in _ancestor_names(win.uac_btn)

        hp = win.overview_view.history_panel
        fp = win.overview_view.freed_panel
        assert isinstance(hp, HistoryPanel)
        assert isinstance(fp, FreedSpacePanel)
        assert hp.summary_lbl.objectName() == "BodyText"
        assert hp.legend_lbl.objectName() == "Caption"
        assert fp.totals_lbl.objectName() == "BodyText"
        assert win.update_banner_lbl.objectName() == "BodyText"
        assert win.storage_view.summary_lbl.objectName() == "BodyText"
        assert win.storage_view.selection_lbl.objectName() == "BodyText"
        assert win.apps_view.summary_lbl.objectName() == "BodyText"
        assert win.startup_view.summary_lbl.objectName() == "BodyText"
        assert win.thermal_view.hw_lbl.objectName() == "BodyText"
        toast = UndoToast(win)
        assert toast.label.objectName() == "BodyText"
        toast.close()
    finally:
        win._force_quit = True
        win.close()
        win.pool.waitForDone(5000)
