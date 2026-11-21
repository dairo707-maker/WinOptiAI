"""Tests for WinOptiAI v0.6.2: interactive/resizable persisted columns across all tables & trees,
horizontal scrolling, HKCU UserAssist last-used precision, and AppsView auto-chained winget checks."""

from __future__ import annotations

import codecs
import os
from pathlib import Path
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFont, QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication, QHeaderView, QTableWidget, QTreeWidget  # noqa: E402

from winoptiai.apps.app_manager import InstalledApp  # noqa: E402
from winoptiai.core.usage_telemetry import (  # noqa: E402
    _EPOCH_DIFF_1601_1970,
    _record_usage_key,
    _record_userassist_entry,
    decode_userassist_name,
    format_app_last_used,
    lookup_usage_ts,
    parse_userassist_blob,
)
from winoptiai.ui.main_window import MainWindow  # noqa: E402
from winoptiai.ui.theme import MONO_FONT_FAMILY, build_obsidian_qss, register_embedded_fonts  # noqa: E402
from winoptiai.ui.views import apps_view as apps_view_mod  # noqa: E402
from winoptiai.ui.widgets import flush_column_width_saves  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    register_embedded_fonts(app)
    return app


def _pump(app: QApplication, n: int = 8) -> None:
    for _ in range(n):
        app.processEvents()


def _header_labels(view: QTableWidget | QTreeWidget) -> list[str]:
    if isinstance(view, QTableWidget):
        return [
            view.horizontalHeaderItem(i).text() if view.horizontalHeaderItem(i) else ""
            for i in range(view.columnCount())
        ]
    it = view.headerItem()
    return [it.text(i) if it else "" for i in range(view.columnCount())]


def _assert_interactive_view(view: QTableWidget | QTreeWidget, fm_hdr: QFontMetrics, name: str) -> None:
    hdr = view.horizontalHeader() if isinstance(view, QTableWidget) else view.header()
    assert hdr.stretchLastSection() is False, f"{name}: stretchLastSection debe estar desactivado"
    assert view.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded, f"{name}: falta scroll horizontal"
    labels = _header_labels(view)
    for col, lbl in enumerate(labels):
        assert hdr.sectionResizeMode(col) == QHeaderView.ResizeMode.Interactive, (
            f"{name} col {col} ({lbl}): debe ser Interactive"
        )
        assert hdr.sectionSize(col) >= fm_hdr.horizontalAdvance(lbl) + 12, (
            f"{name} col {col} ({lbl}): ancho {hdr.sectionSize(col)} recorta encabezado"
        )


def test_all_tables_and_trees_interactive_scrollable_and_persisted(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    qapp.setStyleSheet(build_obsidian_qss("dark"))

    hdr_font = QFont(MONO_FONT_FAMILY)
    hdr_font.setPixelSize(11)
    fm_hdr = QFontMetrics(hdr_font)

    win = MainWindow()
    try:
        win.telemetry_timer.stop()
        win._warmup_timer.stop()
        win.resize(980, 650)
        win.show()
        _pump(qapp, 10)

        static_views: list[tuple[str, QTableWidget | QTreeWidget]] = [
            ("overview.audit_table", win.overview_view.audit_table),
            ("storage.folder_tree", win.storage_view.folder_tree),
            ("storage.format_table", win.storage_view.format_table),
            ("storage.heavy_tree", win.storage_view.heavy_tree),
            ("processes.proc_table", win.processes_view.proc_table),
            ("processes.zombie_table", win.processes_view.zombie_table),
            ("thermal.rec_table", win.thermal_view.rec_table),
            ("apps.apps_table", win.apps_view.apps_table),
            ("startup.startup_table", win.startup_view.startup_table),
        ]
        for label, view in static_views:
            _assert_interactive_view(view, fm_hdr, label)

        for mode in ("junk", "duplicates", "orphans", "onedrive", "quarantine"):
            win.storage_view._switch_mode(mode)
            _pump(qapp, 4)
            _assert_interactive_view(win.storage_view.table, fm_hdr, f"storage.table[{mode}]")

        # Manual resize persists to config.json cleanly per table and per storage mode
        apps_hdr = win.apps_view.apps_table.horizontalHeader()
        apps_hdr.resizeSection(1, 412)
        apps_hdr.resizeSection(6, 285)
        flush_column_width_saves(win.apps_view.apps_table)

        win.storage_view._switch_mode("junk")
        win.storage_view.table.horizontalHeader().resizeSection(0, 240)
        flush_column_width_saves(win.storage_view.table)

        win.storage_view._switch_mode("duplicates")
        win.storage_view.table.horizontalHeader().resizeSection(4, 515)
        flush_column_width_saves(win.storage_view.table)

        # Double-click divider auto-fit expands a narrowed column to fit cell content
        win.apps_view.apps = [
            InstalledApp(
                app_id="u:long",
                name="Aplicacion Corporativa Ultra Extensa de Diagnostico y Reportes v2026",
                version="1.0.0",
                publisher="TRODAI Enterprise Corp",
                available_version="2.0.0",
            )
        ]
        win.apps_view._updates_checked = True
        win.apps_view._render_apps()
        _pump(qapp, 4)
        assert "Corporativa" in (win.apps_view.apps_table.item(0, 1).toolTip() or "")
        assert "2.0.0" in (win.apps_view.apps_table.item(0, 3).toolTip() or "")
        apps_hdr.resizeSection(1, 140)
        apps_hdr.sectionHandleDoubleClicked.emit(1)
        _pump(qapp, 4)
        assert apps_hdr.sectionSize(1) > 260
        apps_hdr.resizeSection(1, 412)
        flush_column_width_saves(win.apps_view.apps_table)
    finally:
        win._force_quit = True
        win.close()
        win.pool.waitForDone(5000)

    # Second session loads saved column widths automatically
    win2 = MainWindow()
    try:
        win2.telemetry_timer.stop()
        win2._warmup_timer.stop()
        assert win2.apps_view.apps_table.horizontalHeader().sectionSize(1) == 412
        assert win2.apps_view.apps_table.horizontalHeader().sectionSize(6) == 285
        win2.storage_view._switch_mode("junk")
        assert win2.storage_view.table.horizontalHeader().sectionSize(0) == 240
        win2.storage_view._switch_mode("duplicates")
        assert win2.storage_view.table.horizontalHeader().sectionSize(4) == 515
    finally:
        win2._force_quit = True
        win2.close()
        win2.pool.waitForDone(5000)


def test_userassist_decoding_usage_matching_and_honest_formatting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ProgramW6432", r"C:\Program Files")
    monkeypatch.setenv("ProgramFiles(x86)", r"C:\Program Files (x86)")

    enc_npp = codecs.encode(r"{6D809377-6AF0-444B-8957-A3773F02200E}\Notepad++\notepad++.exe", "rot_13")
    dec_npp = decode_userassist_name(enc_npp)
    assert dec_npp.lower() == r"c:\program files\notepad++\notepad++.exe"

    enc_arcmap = codecs.encode(r"{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}\ArcGIS\Desktop10.8\bin\ArcMap.exe", "rot_13")
    dec_arcmap = decode_userassist_name(enc_arcmap)
    assert dec_arcmap.lower() == r"c:\program files (x86)\arcgis\desktop10.8\bin\arcmap.exe"

    now = 1_795_200_000.0
    ts_expected = now - 5 * 86400
    ft = int(ts_expected * 10_000_000) + _EPOCH_DIFF_1601_1970
    blob = bytearray(72)
    blob[60:68] = ft.to_bytes(8, "little", signed=False)
    assert abs(parse_userassist_blob(bytes(blob)) - ts_expected) < 1.0
    assert parse_userassist_blob(b"\x00" * 32) == 0.0

    usage: dict[str, float] = {}
    _record_userassist_entry(usage, dec_npp, now - 10 * 86400)
    _record_userassist_entry(usage, "com.mdhero.app", now - 3600)
    _record_userassist_entry(usage, "com.t3tools.t3code", now - 86400)
    _record_userassist_entry(usage, r"C:\Windows\System32\WindowsNotepad\Notepad.exe", now - 1800)
    _record_userassist_entry(usage, dec_arcmap, now - 40 * 86400)
    _record_usage_key(usage, r"\Device\HarddiskVolume3\Program Files\CustomTool\tool.exe", now - 7200)
    _record_usage_key(usage, "python.exe", now)

    assert abs(lookup_usage_ts(usage, name="Notepad++ (64-bit x64)") - (now - 10 * 86400)) < 1.0
    assert abs(lookup_usage_ts(usage, name="MDHero") - (now - 3600)) < 1.0
    assert abs(lookup_usage_ts(usage, name="T3 Code (Beta) 0.1.7") - (now - 86400)) < 1.0
    assert abs(lookup_usage_ts(usage, name="ArcGIS Desktop 10.8.2", install_dir=r'"C:\Program Files (x86)\ArcGIS\Desktop10.8\"') - (now - 40 * 86400)) < 1.0
    assert abs(lookup_usage_ts(usage, name="Herramienta Propia", install_dir=r"C:\Program Files\CustomTool") - (now - 7200)) < 1.0
    # Generic runtime/vendor words must NEVER produce false positives across unrelated packages
    assert lookup_usage_ts(usage, name="Python Launcher") == 0.0
    assert lookup_usage_ts(usage, name="Epson Connect Printer Setup") == 0.0

    assert format_app_last_used(now - 600, now - 90 * 86400, now=now) == "Hoy"
    inst_lbl = format_app_last_used(0.0, 1_644_469_200.0, now=now)
    assert inst_lbl.startswith("Inst. 2022-02-")
    assert format_app_last_used(0.0, 0.0, now=now) == "Sin registro"


def test_apps_view_auto_chains_winget_and_avoids_fake_ok(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    qapp.setStyleSheet(build_obsidian_qss("light"))

    sample = [
        InstalledApp(
            app_id="u:npp",
            name="Notepad++ (64-bit x64)",
            version="8.8.8",
            publisher="Notepad++ Team",
            last_used_ts=time.time() - 3 * 86400,
        ),
        InstalledApp(
            app_id="u:clean",
            name="CleanApp",
            version="2.0.0",
            publisher="CleanCorp",
            last_used_ts=time.time() - 3600,
        ),
    ]

    monkeypatch.setattr(apps_view_mod, "list_installed_apps", lambda progress_cb=None: [InstalledApp(**{k: getattr(a, k) for k in InstalledApp.__dataclass_fields__}) for a in sample])

    def _fake_winget_ok(apps, progress_cb=None):
        apps[0].winget_id = "Notepad++.Notepad++"
        apps[0].available_version = "8.9.9.1"
        return apps, 1, "Se encontraron 1 actualizacion(es) disponible(s) via winget."

    monkeypatch.setattr(apps_view_mod, "check_app_updates_winget", _fake_winget_ok)

    win = MainWindow()
    try:
        win.telemetry_timer.stop()
        win._warmup_timer.stop()
        av = win.apps_view
        av.refresh_apps()
        deadline = time.monotonic() + 5.0
        while (not av._updates_checked or av._checking_updates) and time.monotonic() < deadline:
            _pump(qapp, 4)
            time.sleep(0.02)
        _pump(qapp, 6)

        assert av._updates_checked is True
        assert av.apps_table.item(0, 0).text() == "ACTUALIZAR"
        states = {av.apps_table.item(r, 1).text(): (av.apps_table.item(r, 0).text(), av.apps_table.item(r, 3).text()) for r in range(av.apps_table.rowCount())}
        assert states["Notepad++ (64-bit x64)"] == ("ACTUALIZAR", "8.9.9.1")
        assert states["CleanApp"] == ("AL DIA", "--")

        # When winget fails/unavailable, status must be SIN REVISAR (not fake AL DIA)
        monkeypatch.setattr(
            apps_view_mod,
            "check_app_updates_winget",
            lambda apps, progress_cb=None: (apps, 0, "winget no esta disponible en este equipo (solo listado del Registro)."),
        )
        av.refresh_apps()
        deadline = time.monotonic() + 5.0
        while (av._checking_updates or not av._updates_error) and time.monotonic() < deadline:
            _pump(qapp, 4)
            time.sleep(0.02)
        _pump(qapp, 6)

        assert av._updates_checked is False
        states2 = {av.apps_table.item(r, 1).text(): av.apps_table.item(r, 0).text() for r in range(av.apps_table.rowCount())}
        assert states2["CleanApp"] == "SIN REVISAR"
    finally:
        win._force_quit = True
        win.close()
        win.pool.waitForDone(5000)


def test_admin_relaunch_protects_elevated_child_and_never_tracks_it(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ctypes
    from types import SimpleNamespace

    from winoptiai.core import single_instance, win32_bridge
    from winoptiai.ui import main_window as mw_mod

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    seen_calls: list[tuple[str, str, str | None]] = []
    closed_handles: list[int] = []
    next_handle = 0x12340

    def _fake_shellexec(info_ptr) -> int:
        nonlocal next_handle
        info = ctypes.cast(info_ptr, ctypes.POINTER(win32_bridge._ShellExecuteInfoW)).contents
        seen_calls.append((str(info.lpFile), str(info.lpParameters), info.lpDirectory))
        next_handle += 4
        info.hProcess = next_handle
        return 1

    fake_k32 = SimpleNamespace(
        GetProcessId=lambda _h: 987654,
        WaitForSingleObject=lambda _h, _ms: 0,
        TerminateProcess=lambda _h, _code: 1,
        CloseHandle=lambda h: closed_handles.append(int(h.value or 0)) or 1,
    )

    with win32_bridge._TRACK_LOCK:
        saved_tracked = list(win32_bridge._TRACKED_CHILDREN)
        win32_bridge._TRACKED_CHILDREN.clear()
    saved_protected = set(win32_bridge._PROTECTED_CHILD_PIDS)

    try:
        monkeypatch.setattr(ctypes.windll.shell32, "ShellExecuteExW", _fake_shellexec)
        monkeypatch.setattr(win32_bridge, "_kernel32_proc", lambda: fake_k32)

        # 1. Self-elevation (track=False) must protect new PID, close handle, and NEVER add to _TRACKED_CHILDREN
        assert win32_bridge.run_elevated_command(
            r"C:\Apps\WinOptiAI.exe",
            "--elevated-relaunch",
            track=False,
            directory=r"C:\Apps",
        )
        assert seen_calls[-1][2] == r"C:\Apps"
        assert 987654 in win32_bridge._PROTECTED_CHILD_PIDS
        assert closed_handles
        with win32_bridge._TRACK_LOCK:
            assert win32_bridge._TRACKED_CHILDREN == []

        # 2. Normal elevated maintenance console (track=True) still tracks handle for shutdown cleanup
        assert win32_bridge.run_elevated_command("powershell.exe", "sfc /scannow")
        with win32_bridge._TRACK_LOCK:
            assert len(win32_bridge._TRACKED_CHILDREN) == 1
    finally:
        with win32_bridge._TRACK_LOCK:
            win32_bridge._TRACKED_CHILDREN.clear()
            win32_bridge._TRACKED_CHILDREN.extend(saved_tracked)
        win32_bridge._PROTECTED_CHILD_PIDS.clear()
        win32_bridge._PROTECTED_CHILD_PIDS.update(saved_protected)

    # 3. MainWindow._request_admin_relaunch passes track=False and working directory, then calls _quit_app
    captured_relaunch: list[tuple[tuple, dict]] = []
    quit_called: list[bool] = []
    monkeypatch.setattr(
        mw_mod.QMessageBox,
        "question",
        lambda *_a, **_kw: mw_mod.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        mw_mod,
        "run_elevated_command",
        lambda *args, **kwargs: captured_relaunch.append((args, kwargs)) or True,
    )

    win = MainWindow()
    try:
        win.telemetry_timer.stop()
        win._warmup_timer.stop()
        monkeypatch.setattr(win, "_quit_app", lambda: quit_called.append(True))
        win._request_admin_relaunch()

        assert len(captured_relaunch) == 1
        args, kwargs = captured_relaunch[0]
        assert mw_mod.ELEVATED_RELAUNCH_ARG in args[1]
        assert kwargs.get("track") is False
        assert kwargs.get("directory")
        assert quit_called == [True]
    finally:
        win._force_quit = True
        win.close()
        win.pool.waitForDone(5000)

    # 4. SingleInstanceLock rejects acquisition on ERROR_ACCESS_DENIED (5)
    class _DeniedK32:
        class _Fn:
            def __init__(self, fn):
                self._fn = fn
                self.restype = None
                self.argtypes = None

            def __call__(self, *a):
                return self._fn(*a)

        def __init__(self):
            self.CreateMutexW = self._Fn(lambda *_a: 0)
            self.WaitForSingleObject = self._Fn(lambda *_a: 0)

    monkeypatch.setattr(single_instance.ctypes, "WinDLL", lambda *_a, **_kw: _DeniedK32())
    monkeypatch.setattr(single_instance.ctypes, "get_last_error", lambda: single_instance.ERROR_ACCESS_DENIED)
    lock = single_instance.SingleInstanceLock("WinOptiAI-test-denied")
    assert lock.acquire() is False

