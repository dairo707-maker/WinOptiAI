"""Tests for WinOptiAI v0.6.0 (by TRODAI): brand identity, scroll-free Overview + gauges/semaphores,
modern opaque Treemap, 'ULTIMO USO' columns, App Manager, Smart Startup Optimizer, and hardened update alerts."""

from __future__ import annotations

import os
from pathlib import Path
import re
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFontDatabase, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

from winoptiai import get_base_dir  # noqa: E402
from winoptiai.apps.app_manager import (  # noqa: E402
    InstalledApp,
    find_app_leftovers,
    is_protected_application,
    parse_winget_upgrade_output,
)
from winoptiai.apps.startup_manager import (  # noqa: E402
    StartupItem,
    classify_startup_item,
    set_startup_item_enabled,
)
from winoptiai.core.metrics_history import MetricsHistory  # noqa: E402
from winoptiai.core.safety_guard import PreOpBackupManager  # noqa: E402
from winoptiai.core.telemetry import LiveSystemTelemetry  # noqa: E402
from winoptiai.core.updater import ReleaseInfo  # noqa: E402
from winoptiai.core.usage_telemetry import (  # noqa: E402
    filetime_bytes_to_epoch,
    format_last_used,
    parse_iso_timestamp,
)
from winoptiai.storage.tree_analyzer import FolderNode  # noqa: E402
from winoptiai.ui.main_window import MainWindow  # noqa: E402
from winoptiai.ui.theme import (  # noqa: E402
    DARK_PALETTE,
    LIGHT_PALETTE,
    MONO_FONT_FAMILY,
    UI_FONT_FAMILY,
    build_obsidian_qss,
    get_palette,
    register_embedded_fonts,
)
from winoptiai.ui.treemap import TreemapWidget, treemap_category_colors  # noqa: E402
from winoptiai.ui.widgets import find_clipped_buttons  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    register_embedded_fonts(app)
    return app


def _pump(app: QApplication, n: int = 8) -> None:
    for _ in range(n):
        app.processEvents()


def test_trodai_corporate_brand_svgs_fonts_and_palette(qapp: QApplication) -> None:
    assert UI_FONT_FAMILY == "Space Grotesk"
    assert MONO_FONT_FAMILY == "JetBrains Mono"
    families = set(QFontDatabase.families())
    assert "Space Grotesk" in families
    assert "JetBrains Mono" in families

    assert DARK_PALETTE["accent"] == "#0EA5E9"
    assert DARK_PALETTE["accent_alt"] == "#3B82F6"
    assert LIGHT_PALETTE["text_primary"] == "#0A0F1D"
    assert LIGHT_PALETTE["accent"] == "#2563EB"

    icons = get_base_dir() / "assets" / "icons"
    curve_re = re.compile(r"\b[CSQTA]\b|<(circle|ellipse)\b")
    for svg_name in ("brand.svg", "trodai_favicon.svg", "apps.svg", "startup.svg"):
        txt = (icons / svg_name).read_text(encoding="utf-8")
        assert not curve_re.search(txt), f"Curva/circulo prohibido en {svg_name}"
        assert 'stroke="currentColor"' in txt


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_overview_no_scroll_single_row_kpis_gauges_and_semaphores(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    qapp.setStyleSheet(build_obsidian_qss(mode))
    win = MainWindow()
    try:
        win.policy.config.theme_mode = mode
        win._apply_ui_appearance()
        win.resize(980, 650)
        win.show()
        _pump(qapp, 12)

        win.telemetry_timer.stop()
        win._warmup_timer.stop()
        ov = win.overview_view
        assert ov.findChildren(QScrollArea) == []
        assert not ov.benefit_strip.isVisible()

        # 4 KPI cards sit in a single horizontal row (top y matches within 2px)
        ys = [c.y() for c in (ov.ram_cell, ov.disk_cell, ov.cpu_cell, ov.sre_cell)]
        assert max(ys) - min(ys) <= 2

        ov.update_telemetry(
            ram={"free_gb": 6.4, "used_gb": 9.6, "total_gb": 16.0, "used_pct": 60.0},
            live=LiveSystemTelemetry(42.0, 2400.0, 35.0, [40.0, 44.0], 62.0, None, "pdh"),
            disk_free_gb=120.0,
            disk_total_gb=475.0,
            sre_active=True,
            threshold_gb=1.8,
            thermal_label="Equilibrado",
        )
        _pump(qapp)

        assert ov.history_panel.chart.height() >= 150
        pm = QPixmap(ov.gauges_widget.size())
        ov.gauges_widget.render(pm)
        assert not pm.isNull()
        assert "OPTIMO" == ov.gauges_widget._health_label
        assert find_clipped_buttons(win) == []
    finally:
        win._force_quit = True
        win.close()
        win.pool.waitForDone(5000)


def test_modern_opaque_treemap_and_clickable_breadcrumbs(qapp: QApplication) -> None:
    sub_b = FolderNode("SubB", Path(r"C:\Root\Alpha\SubB"), size_bytes=300, file_count=3, last_used_ts=time.time(), dominant_category="Video")
    alpha = FolderNode("Alpha", Path(r"C:\Root\Alpha"), size_bytes=800, file_count=8, children=[sub_b], last_used_ts=time.time(), dominant_category="Video")
    beta = FolderNode("Beta", Path(r"C:\Root\Beta"), size_bytes=500, file_count=5, last_used_ts=time.time() - 86400 * 40, dominant_category="Modelos IA / Binarios")
    root = FolderNode("Root", Path(r"C:\Root"), size_bytes=1500, file_count=15, children=[alpha, beta], last_used_ts=time.time(), dominant_category="Video")

    for mode in ("dark", "light"):
        fill, border = treemap_category_colors("Video", dark=(mode == "dark"))
        assert fill.alpha() >= 220
        assert border.alpha() >= 180

        tm = TreemapWidget(lambda m=mode: get_palette(m))
        tm.resize(640, 360)
        tm.set_root(root)
        assert len(tm.stack_nodes()) == 1
        tm.enter(alpha)
        assert len(tm.stack_nodes()) == 2
        assert tm.current is alpha

        pm = QPixmap(tm.size())
        tm.render(pm)
        assert not pm.isNull()

        tm.jump_to_depth(0)
        assert tm.current is root
        tm.close()


def test_usage_telemetry_formatting_and_columns_across_views(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 1_795_000_000.0
    assert format_last_used(0.0, now=now) == "Sin registro"
    assert format_last_used(now - 1800, now=now) == "Hoy"
    assert format_last_used(now - 86400, now=now) == "Ayer"
    assert format_last_used(now - 6 * 86400, now=now) == "Hace 6 d"
    assert re.match(r"\d{4}-\d{2}-\d{2}$", format_last_used(now - 45 * 86400, now=now))
    assert parse_iso_timestamp("2026-10-12T15:30:00Z") > 0.0
    assert filetime_bytes_to_epoch(b"\x00" * 8) == 0.0

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    win = MainWindow()
    try:
        for mode in ("junk", "duplicates", "orphans", "onedrive", "quarantine"):
            win.storage_view._switch_mode(mode)
            headers = [win.storage_view.table.horizontalHeaderItem(c).text() for c in range(win.storage_view.table.columnCount())]
            assert "ULTIMO USO" in headers
        assert win.storage_view.folder_tree.headerItem().text(4) == "ULTIMO USO"
        assert "ULTIMO USO" in [
            win.storage_view.format_table.horizontalHeaderItem(c).text()
            for c in range(win.storage_view.format_table.columnCount())
        ]
        assert win.storage_view.heavy_tree.headerItem().text(3) == "ULTIMO USO"

        proc_headers = [
            win.processes_view.proc_table.horizontalHeaderItem(c).text()
            for c in range(win.processes_view.proc_table.columnCount())
        ]
        assert "ULTIMO USO" in proc_headers

        apps_headers = [
            win.apps_view.apps_table.horizontalHeaderItem(c).text()
            for c in range(win.apps_view.apps_table.columnCount())
        ]
        assert "ULTIMO USO" in apps_headers

        st_headers = [
            win.startup_view.startup_table.horizontalHeaderItem(c).text()
            for c in range(win.startup_view.startup_table.columnCount())
        ]
        assert "ULTIMO USO" in st_headers
    finally:
        win._force_quit = True
        win.close()
        win.pool.waitForDone(5000)


def test_app_manager_winget_parser_protection_and_leftovers(tmp_path: Path) -> None:
    sample_output = (
        "   - \r\n"
        "Nombre                        Id                           Version    Disponible Origen\n"
        "------------------------------------------------------------------------------------------\n"
        "Git                           Git.Git                      2.45.0     2.47.1     winget\n"
        "Visual Studio Code            Microsoft.VisualStudioCode   1.90.0     1.95.2     winget\n"
        "2 actualizaciones disponibles.\n"
    )
    parsed = parse_winget_upgrade_output(sample_output)
    assert len(parsed) == 2
    assert parsed[0]["id"] == "Git.Git"
    assert parsed[0]["available"] == "2.47.1"
    assert parsed[1]["id"] == "Microsoft.VisualStudioCode"

    assert is_protected_application("WinOptiAI") != ""
    assert is_protected_application("Microsoft Visual C++ 2022 Redistributable") != ""
    assert is_protected_application("7-Zip 24.08") == ""

    app_dir = tmp_path / "AcmeTool"
    app_dir.mkdir()
    winopti_dir = tmp_path / "WinOptiAI"
    winopti_dir.mkdir()
    app = InstalledApp(app_id="u:acme", name="AcmeTool", version="1.0", publisher="Acme")
    leftovers = find_app_leftovers(app, search_bases=[tmp_path])
    assert leftovers == [app_dir]


def test_startup_manager_smart_semaphore_and_backup_toggle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 1_795_000_000.0
    rec_sec, tone_sec, _, prot_sec = classify_startup_item(
        "SecurityHealth", r"C:\Windows\System32\SecurityHealthSystray.exe", 0.0, 20.0, now=now
    )
    assert (rec_sec, tone_sec, prot_sec) == ("MANTENER", "ok", True)

    rec_dis, tone_dis, _, prot_dis = classify_startup_item(
        "Spotify", r"C:\Users\u\AppData\Roaming\Spotify\Spotify.exe", now - 45 * 86400, 140.0, now=now
    )
    assert (rec_dis, tone_dis, prot_dis) == ("DESACTIVAR", "risk", False)

    rec_pause, tone_pause, _, _ = classify_startup_item(
        "NotionHelper", r"C:\Users\u\AppData\Local\Notion\Notion.exe", now - 12 * 86400, 160.0, now=now
    )
    assert (rec_pause, tone_pause) == ("PAUSAR", "warn")

    # Blocking protected startup items before hitting registry
    bm = PreOpBackupManager(root_dir=tmp_path / "backups")
    prot_item = StartupItem(
        item_id="HKCU_RUN:Bitdefender",
        name="Bitdefender",
        command="bdagent.exe",
        location_kind="HKCU_RUN",
        scope="Usuario",
        entry_name="Bitdefender",
        enabled=True,
        protected=True,
    )
    ok_prot, msg_prot = set_startup_item_enabled(prot_item, False, backup_mgr=bm)
    assert not ok_prot and "protegida" in msg_prot

    # Verify reversible HKCU toggle works when mocked via winreg.CreateKeyEx / SetValueEx
    import winreg

    written: dict[str, tuple[int, bytes]] = {}

    class _DummyKey:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(winreg, "CreateKeyEx", lambda *_a, **_kw: _DummyKey())
    monkeypatch.setattr(
        winreg,
        "SetValueEx",
        lambda _k, name, _res, typ, val: written.__setitem__(name, (typ, val)),
    )

    user_item = StartupItem(
        item_id="HKCU_RUN:Spotify",
        name="Spotify",
        command="Spotify.exe",
        location_kind="HKCU_RUN",
        scope="Usuario",
        entry_name="Spotify",
        enabled=True,
        protected=False,
    )
    ok_off, _ = set_startup_item_enabled(user_item, False, backup_mgr=bm)
    assert ok_off and not user_item.enabled
    assert written["Spotify"][1][0] % 2 == 1  # odd byte = disabled in Windows Task Manager

    ok_on, _ = set_startup_item_enabled(user_item, True, backup_mgr=bm)
    assert ok_on and user_item.enabled
    assert written["Spotify"][1][0] % 2 == 0  # even byte = enabled


def test_hardened_update_notifications_retry_banner_and_clickable_toast(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    qapp.setStyleSheet(build_obsidian_qss("dark"))
    win = MainWindow()
    try:
        win.resize(980, 650)
        win.show()
        _pump(qapp, 8)

        # Network failure schedules backoff retry timer instead of dropping check for 12h
        assert not win._handle_update_check_result(False, None)
        assert win.update_retry_timer.isActive()
        assert win._update_retry_count == 1
        win.update_retry_timer.stop()

        # Successful detection reveals TRODAI in-app banner & syncs tray clickable toast intent
        rel = ReleaseInfo(
            tag="v0.9.9",
            version="0.9.9",
            notes="TRODAI Release Test",
            html_url="https://github.com/dairo707-maker/WinOptiAI/releases/tag/v0.9.9",
            setup_url="https://github.com/dairo707-maker/WinOptiAI/releases/download/v0.9.9/WinOptiAI-Setup.exe",
            checksums_url=None,
            update_available=True,
        )
        assert win._handle_update_check_result(True, rel)
        assert win.update_banner.isVisible()
        assert "v0.9.9" in win.update_banner_lbl.text()
        assert find_clipped_buttons(win) == []

        # Clicking balloon notification routes to About/Updater when _last_toast_kind == 'update'
        opened_updates: list[int] = []
        win.tray._on_open_updates = lambda: opened_updates.append(1)
        win.tray.show_toast("WinOptiAI", "Nueva v0.9.9", kind="update")
        win.tray._on_message_clicked()
        assert opened_updates == [1]

        # Dismissing banner hides it cleanly
        win.update_banner_close_btn.click()
        _pump(qapp)
        assert not win.update_banner.isVisible()
    finally:
        win._force_quit = True
        win.close()
        win.pool.waitForDone(5000)
