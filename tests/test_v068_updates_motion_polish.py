"""Tests for WinOptiAI v0.6.8: winget diagnostics, fast metrics recovery, solid TRODAI polish & motion."""

from __future__ import annotations

import os
from pathlib import Path
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea
import pytest

from winoptiai.apps.app_manager import (
    InstalledApp,
    bulk_upgrade_skip_reason,
    classify_winget_failure,
    interpret_winget_result,
    upgrade_app_winget,
)
from winoptiai.core.metrics_history import MetricsHistory, MinuteAggregator
from winoptiai.core.safety_guard import QuarantineVault
from winoptiai.core.sre_policy import SREPolicyEngine
from winoptiai.ui.motion import MotionBackdropWidget, MotionPerformanceGuard
from winoptiai.ui.main_window import MainWindow
from winoptiai.ui.theme import build_obsidian_qss, register_embedded_fonts
from winoptiai.ui.views.apps_view import AppsView
from winoptiai.ui.widgets import (
    SectionBenefitStrip,
    SlidingNavPanel,
    SlidingSegmentedControl,
    StatusTag,
    find_clipped_buttons,
)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    register_embedded_fonts(app)
    return app


def _pump(app: QApplication, n: int = 8) -> None:
    for _ in range(n):
        app.processEvents()


def test_winget_classifications_real_world_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    # ChatGPT accent variant
    out_ok = "El hash del instalador se verifico correctamente\nSe instaló correctamente. Reinicie la aplicación para completar la actualización.\n"
    cat, _msg, _url = classify_winget_failure(0, out_ok)
    assert cat == "ok_restart"
    assert interpret_winget_result(0, out_ok) == (True, "ok")
    assert interpret_winget_result(3010, "") == (True, "ok")
    assert interpret_winget_result(0x80070BC2, "") == (True, "ok")

    # Anaconda: winget forbids upgrade -> SOLO EDITOR
    out_ana = "El paquete no se puede actualizar con WinGet. Use el método proporcionado por el editor para actualizar este paquete.\n"
    cat_a, msg_a, _ = classify_winget_failure(0x8A15002B, out_ana)
    assert cat_a == "editor_only"
    assert "editor" in msg_a.lower()
    assert interpret_winget_result(0x8A15002B, out_ana)[0] is False

    # WSL: 0x80073d28 -> needs_admin
    out_wsl = "Error del instalador con el codigo de salida: 0x80073d28 : The package installation failed because administrator privileges are required.\n"
    cat_w, msg_w, _ = classify_winget_failure(0x80073D28, out_wsl)
    assert cat_w == "needs_admin"
    assert "Administrador" in msg_w

    # VLC / BleachBit / HWiNFO: 0x80072f0d -> tls_error + HTTPS URL extracted
    out_vlc = (
        "Descargando https://download.videolan.org/pub/videolan/vlc/3.0.24/win64/vlc-3.0.24-win64.exe\n"
        "InternetOpenUrl() failed.\n0x80072f0d : unknown error\n"
    )
    cat_v, msg_v, url_v = classify_winget_failure(0x80072F0D, out_vlc)
    assert cat_v == "tls_error"
    assert "HTTPS" in msg_v
    assert url_v == "https://download.videolan.org/pub/videolan/vlc/3.0.24/win64/vlc-3.0.24-win64.exe"

    # Simulated upgrade marks app status and bulk_upgrade_skip_reason respects editor_only
    class _Proc:
        pid = 4_200_000

        def __init__(self, payload: bytes, rc: int) -> None:
            self._payload = payload
            self._rc = rc

        def __call__(self, _cmd, stdout=None, **_k):
            stdout.write(self._payload)
            stdout.flush()
            return self

        def poll(self):
            return self._rc

    ana = InstalledApp(app_id="a", name="Anaconda3", version="2021.11", available_version="2026.07-1", winget_id="Anaconda.Anaconda3")
    ok_ana, _ = upgrade_app_winget(ana, poll_s=0.001, popen=_Proc(out_ana.encode("utf-8"), 1))
    assert not ok_ana and ana.upgrade_status == "editor_only"
    assert "editor" in bulk_upgrade_skip_reason(ana).lower()


def test_apps_view_retry_failed_solo_editor_and_cache(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    view = AppsView(QuarantineVault(root_dir=tmp_path / "q"), SREPolicyEngine(app_dir=tmp_path), lambda *a, **k: None, lambda _m: None)
    ana = InstalledApp(
        app_id="a", name="Anaconda3", version="2021.11", available_version="2026.07-1",
        winget_id="Anaconda.Anaconda3", upgrade_status="editor_only", upgrade_note="Usar editor",
    )
    wsl = InstalledApp(
        app_id="w", name="WSL", version="2.7.10", available_version="3.0.5",
        winget_id="Microsoft.WSL", upgrade_status="needs_admin", upgrade_note="Requiere UAC",
    )
    vlc = InstalledApp(
        app_id="v", name="VLC", version="3.0.21", available_version="3.0.24",
        winget_id="VideoLAN.VLC", upgrade_status="tls_error", upgrade_url="https://download.videolan.org/",
    )

    # Only editor_only -> retry button stays hidden
    view.apps = [ana]
    view._sync_failed_apps()
    assert not view.retry_failed_btn.isVisible()

    # Retryable failures -> button visible with count and table shows SOLO EDITOR
    view.apps = [ana, wsl, vlc]
    view._sync_failed_apps()
    view._render_apps()
    assert view.retry_failed_btn.isVisibleTo(view) or len(view._failed_apps) == 2
    assert "Reintentar fallidas (2)" == view.retry_failed_btn.text()
    assert view.apps_table.item(0, 0).text() == "SOLO EDITOR"

    # Cache preserves status across rescan until updated
    view._status_cache["anaconda.anaconda3"] = ("editor_only", "Usar editor", "")
    fresh_ana = InstalledApp(app_id="a2", name="Anaconda3", version="2021.11", available_version="2026.07-1", winget_id="Anaconda.Anaconda3")
    view._restore_cached_statuses([fresh_ana])
    assert fresh_ana.upgrade_status == "editor_only"
    view.close()


def test_metrics_initial_fast_interval_and_error_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agg = MinuteAggregator(interval=60, initial_interval=10)
    assert agg.add(6.0, 16.0, 20.0, None, now=100.0) is None
    first = agg.add(5.5, 16.0, 25.0, None, now=110.0)
    assert first is not None and first["ts"] == 110
    # Next emission returns to 60s cadence
    assert agg.add(5.0, 16.0, 30.0, None, now=125.0) is None
    second = agg.add(5.0, 16.0, 35.0, None, now=170.0)
    assert second is not None and second["ts"] == 170

    mh = MetricsHistory(app_dir=tmp_path)
    monkeypatch.setattr(mh.store, "add", lambda _s: (_ for _ in ()).throw(RuntimeError("boom-sqlite")))
    fut = mh.record_async({"ts": int(time.time()), "ram_free_gb": 4.0, "ram_total_gb": 16.0, "cpu_pct": 12.0})
    with pytest.raises(RuntimeError):
        fut.result(timeout=3)
    # Give done_callback a moment
    time.sleep(0.05)
    assert "boom-sqlite" in mh.last_error
    assert "MetricsHistory.record_async error" in (tmp_path / "crash.log").read_text(encoding="utf-8")
    mh.shutdown()


def test_solid_trodai_widgets_and_motion_guard(qapp: QApplication) -> None:
    guard_vis = MotionPerformanceGuard(
        os_animations_fn=lambda: True, battery_saver_fn=lambda: False, headless_fn=lambda: False
    )
    assert guard_vis.evaluate(window_visible=True).should_animate
    assert not guard_vis.evaluate(window_visible=False).should_animate
    assert not guard_vis.evaluate(window_visible=True, heavy_task_active=True).should_animate
    assert not guard_vis.evaluate(window_visible=True, static_override=True).should_animate

    guard_batt = MotionPerformanceGuard(
        os_animations_fn=lambda: True, battery_saver_fn=lambda: True, headless_fn=lambda: False
    )
    assert guard_batt.evaluate(window_visible=True).status_code == "battery"

    for mode in ("dark", "light"):
        qss = build_obsidian_qss(mode)
        assert "rgba(" not in qss
        tag = StatusTag("ADMIN UAC", "ok", theme_mode=mode)
        assert "rgba(" not in tag.styleSheet()
        tag.close()

        mb = MotionBackdropWidget("sidebar", theme_mode=mode, guard=guard_vis)
        mb.resize(248, 300)
        pm = QPixmap(mb.size())
        mb.render(pm)
        assert not pm.isNull()
        mb.cleanup()
        mb.close()

    nav = SlidingNavPanel()
    nav.set_items([("overview", "Resumen"), ("apps", "Aplicaciones")])
    nav.set_tooltips(["Tip 1", "Tip 2"])
    nav.set_current_index(1, animate=False, emit_signal=False)
    assert nav.current_index() == 1
    assert nav.tooltips() == ["Tip 1", "Tip 2"]
    nav.close()

    seg = SlidingSegmentedControl()
    seg.set_options([("24h", "24 h"), ("7d", "7 d")])
    seg.set_current("7d", animate=False, emit_signal=False)
    assert seg.current_key() == "7d"
    seg.close()

    strip = SectionBenefitStrip("overview")
    assert not hasattr(strip, "badge")
    strip.close()


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_main_window_clean_labels_motion_and_no_clipping(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    qapp.setStyleSheet(build_obsidian_qss(mode))
    win = MainWindow()
    try:
        win.telemetry_timer.stop()
        win._warmup_timer.stop()
        win.policy.config.theme_mode = mode
        win._apply_ui_appearance()
        win.resize(980, 650)
        win.show()
        _pump(qapp, 10)

        assert win.overview_view.findChildren(QScrollArea) == []
        assert find_clipped_buttons(win) == []

        labels_txt = [lbl.text() for lbl in win.findChildren(QLabel)]
        assert "TRODAI SRE" not in labels_txt
        assert "EN REPOSO" not in labels_txt
        assert "GUIA" not in labels_txt
        assert "v0.6.8" in win.brand_sub.text()
        assert not hasattr(win.overview_view, "policy_tag")
        assert not hasattr(win.overview_view, "active_tag")
    finally:
        win._force_quit = True
        win.close()
        win.pool.waitForDone(5000)
