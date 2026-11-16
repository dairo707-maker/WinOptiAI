"""Tests for WinOptiAI v0.5.1: crash guard / dirty exit, deferred safe table refresh, Select All in storage."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from winoptiai.core.crash_guard import CrashGuard  # noqa: E402
from winoptiai.core.safety_guard import PreOpBackupManager, QuarantineVault  # noqa: E402
from winoptiai.core.sre_policy import SREPolicyEngine  # noqa: E402
from winoptiai.storage.junk_scanner import JunkTarget  # noqa: E402
from winoptiai.storage.orphan_hunter import OrphanCandidate  # noqa: E402
from winoptiai.thermal_bios.bios_auditor import HardwareAuditReport  # noqa: E402
from winoptiai.ui.views import thermal_bios_view  # noqa: E402
from winoptiai.ui.views.storage_view import SELECTABLE_TABLE_MODES, StorageView  # noqa: E402
from winoptiai.ui.views.thermal_bios_view import ThermalBiosView  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(n: int = 3) -> None:
    for _ in range(n):
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, 0)


# --------------------------------------------------------------------------- crash guard
def test_crash_guard_clean_then_dirty_exit_detection(tmp_path: Path) -> None:
    g1 = CrashGuard(app_dir=tmp_path, version="0.5.1")
    first = g1.begin_session()
    assert not first.dirty  # no previous marker
    lock = json.loads((tmp_path / "session_lock.json").read_text(encoding="utf-8"))
    assert lock["clean_exit"] is False and lock["pid"] == os.getpid() and lock["version"] == "0.5.1"

    g1.mark_clean_exit()
    assert json.loads((tmp_path / "session_lock.json").read_text(encoding="utf-8"))["clean_exit"] is True

    g2 = CrashGuard(app_dir=tmp_path, version="0.5.1")
    assert not g2.begin_session().dirty  # previous closed cleanly

    # Simulate abrupt termination: g2 never calls mark_clean_exit(); fake a dead PID
    data = json.loads((tmp_path / "session_lock.json").read_text(encoding="utf-8"))
    data["pid"] = 0
    (tmp_path / "session_lock.json").write_text(json.dumps(data), encoding="utf-8")

    g3 = CrashGuard(app_dir=tmp_path, version="0.5.1")
    rep = g3.begin_session()
    assert rep.dirty
    assert "no cerro" in rep.summary()
    assert "CIERRE INESPERADO" in (tmp_path / "crash.log").read_text(encoding="utf-8")
    diag = g3.build_diagnostic_text()
    assert "Diagnostico post-mortem" in diag and str(tmp_path / "crash.log") in diag


def test_crash_guard_corrupt_marker_counts_as_dirty(tmp_path: Path) -> None:
    (tmp_path / "session_lock.json").write_text("{corrupto", encoding="utf-8")
    assert CrashGuard(app_dir=tmp_path, version="0.5.1").begin_session().dirty


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_crash_guard_hooks_write_tracebacks_and_breadcrumbs(tmp_path: Path) -> None:
    guard = CrashGuard(app_dir=tmp_path, version="0.5.1")
    prev_sys, prev_thread = sys.excepthook, threading.excepthook
    guard.install()
    try:
        guard.breadcrumb("Vista 3")
        try:
            raise ValueError("fallo de prueba sys")
        except ValueError:
            sys.excepthook(*sys.exc_info())

        def _boom() -> None:
            raise RuntimeError("fallo de prueba hilo")

        t = threading.Thread(target=_boom, name="worker-test")
        t.start()
        t.join()
    finally:
        guard.uninstall()
    assert sys.excepthook is prev_sys and threading.excepthook is prev_thread

    text = (tmp_path / "crash.log").read_text(encoding="utf-8")
    assert "ValueError: fallo de prueba sys" in text
    assert "RuntimeError: fallo de prueba hilo" in text
    assert "threading:worker-test" in text
    assert "Vista 3" in text and "WinOptiAI v0.5.1" in text


def test_crash_guard_ignores_other_live_instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from winoptiai.core import crash_guard as cg

    (tmp_path / "session_lock.json").write_text(
        json.dumps({"pid": 999999, "version": "0.5.1", "started_at": "", "clean_exit": False}), encoding="utf-8"
    )
    monkeypatch.setattr(cg, "_pid_is_other_live_instance", lambda pid: True)
    assert not CrashGuard(app_dir=tmp_path, version="0.5.1").begin_session().dirty


def test_main_window_reports_dirty_exit_in_bell_and_audit(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from winoptiai.ui.main_window import MainWindow

    # Aislar notificaciones/audit/config del %LOCALAPPDATA% real del usuario
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))

    (tmp_path / "session_lock.json").write_text(
        json.dumps({"pid": 0, "version": "0.5.0", "started_at": "x", "clean_exit": False}), encoding="utf-8"
    )
    guard = CrashGuard(app_dir=tmp_path, version="0.5.1")
    guard.begin_session()
    win = MainWindow(crash_guard=guard)
    try:
        before = len(win.notif_center.list_items())
        win._report_previous_dirty_exit()
        items = win.notif_center.list_items()
        assert len(items) == before + 1
        assert any(i.kind == "ERROR" and "Cierre inesperado" in i.title for i in items)
        assert any(r.get("actor") == "crash_guard" for r in win.policy.read_recent_audit(50))
        win._quit_app()
        assert json.loads((tmp_path / "session_lock.json").read_text(encoding="utf-8"))["clean_exit"] is True
    finally:
        win._force_quit = True
        win.close()
        win.pool.waitForDone(15000)
        _pump()


# --------------------------------------------------------------------------- thermal deferred refresh
def _fake_report() -> HardwareAuditReport:
    from types import SimpleNamespace

    rep = SimpleNamespace()  # only .recommendations is consumed by _render_recommendations
    rep.recommendations = [
        {"area": "Disco", "estado": "AVISO", "detalle": "CHKDSK", "action_id": "run_chkdsk_scan", "action_label": "CHKDSK"},
        {"area": "Energia", "estado": "OK", "detalle": "Perfil", "action_id": "open_power_settings", "action_label": "Abrir"},
    ]
    return rep


def test_thermal_recommendation_click_never_rebuilds_table_synchronously(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = SREPolicyEngine(app_dir=tmp_path)
    backup = PreOpBackupManager(root_dir=tmp_path)
    monkeypatch.setattr(backup, "backup_power_scheme", lambda label="x": tmp_path)
    monkeypatch.setattr(thermal_bios_view, "execute_audit_action", lambda aid: (True, f"ok {aid}"))

    calls: list[str] = []

    def fake_run_async(fn, callback, label="", notify_on_complete=True, on_error=None, **_kw):
        calls.append(label)
        callback(fn())  # synchronous worst case: completion inside the click stack

    view = ThermalBiosView(policy, backup, fake_run_async, lambda _m: None, lambda _a, _b: None)
    view.last_report = _fake_report()
    view._render_recommendations(view.last_report)
    assert view.rec_table.rowCount() == 2

    row_clicked = next(
        r for r in range(view.rec_table.rowCount()) if view.rec_table.item(r, 3).text() == "CHKDSK"
    )
    btn = view.rec_table.cellWidget(row_clicked, 4)
    assert isinstance(btn, QPushButton)

    render_calls: list[int] = []
    original_render = view._render_recommendations
    monkeypatch.setattr(
        view, "_render_recommendations", lambda rep: (render_calls.append(1), original_render(rep))
    )

    btn.click()  # emits clicked -> _run_recommendation -> (sync) completion
    assert calls == ["Auditoria: Disco"]
    assert render_calls == []  # table NOT rebuilt while the clicked signal is on the stack
    assert view.rec_table.rowCount() == 2
    assert view.rec_table.cellWidget(row_clicked, 4) is btn  # emitter still alive & attached

    _pump()
    assert render_calls == [1]
    assert view.rec_table.rowCount() == 1
    assert "run_chkdsk_scan" in policy.config.completed_audit_actions
    assert view._running_actions == set()


def test_thermal_rapid_double_click_ignored_while_running(qapp: QApplication, tmp_path: Path, monkeypatch) -> None:
    policy = SREPolicyEngine(app_dir=tmp_path)
    backup = PreOpBackupManager(root_dir=tmp_path)
    pending: list = []

    def fake_run_async(fn, callback, label="", notify_on_complete=True, on_error=None, **_kw):
        pending.append((fn, callback))

    view = ThermalBiosView(policy, backup, fake_run_async, lambda _m: None, lambda _a, _b: None)
    view.last_report = _fake_report()
    view._render_recommendations(view.last_report)
    rec = _fake_report().recommendations[1]
    view._run_recommendation(rec)
    view._run_recommendation(rec)
    assert len(pending) == 1 and "open_power_settings" in view._running_actions


def test_thermal_blocks_dism_when_servicing_already_running(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = SREPolicyEngine(app_dir=tmp_path)
    backup = PreOpBackupManager(root_dir=tmp_path)
    launched: list[str] = []
    msgs: list[str] = []
    monkeypatch.setattr(thermal_bios_view, "detect_active_servicing_processes", lambda: ["dism.exe"])
    view = ThermalBiosView(
        policy, backup, lambda fn, cb, label="", **_k: launched.append(label), msgs.append, lambda _a, _b: None
    )
    view._run_recommendation({"area": "Integridad OS", "action_id": "run_sfc_dism"})
    view._run_recommendation({"area": "WinSxS", "action_id": "run_winsxs_cleanup"})
    assert launched == []
    assert all("dism.exe" in m for m in msgs) and len(msgs) == 2

    monkeypatch.setattr(thermal_bios_view, "detect_active_servicing_processes", lambda: [])
    view._run_recommendation({"area": "Integridad OS", "action_id": "run_sfc_dism"})
    assert launched == ["Auditoria: Integridad OS"]


def test_detect_active_servicing_processes_returns_list() -> None:
    from winoptiai.thermal_bios.bios_auditor import detect_active_servicing_processes

    res = detect_active_servicing_processes()
    assert isinstance(res, list) and all(n.endswith(".exe") for n in res)


# --------------------------------------------------------------------------- storage select all
def _storage_view(tmp_path: Path) -> StorageView:
    policy = SREPolicyEngine(app_dir=tmp_path)
    vault = QuarantineVault(root_dir=tmp_path)
    backup = PreOpBackupManager(root_dir=tmp_path)
    return StorageView(vault, backup, policy, lambda *a, **k: None, lambda _m: None)


def _populate(view: StorageView, mode: str, tmp_path: Path) -> int:
    view._switch_mode(mode)
    if mode == "junk":
        view.junk_targets = [
            JunkTarget(
                target_id=f"t{i}", label=f"t{i}", category="Temp", path=tmp_path / f"t{i}",
                allow_system_temp=False, file_count=i + 1, reclaimable_bytes=(i + 1) * 1000,
            )
            for i in range(4)
        ]
        view._render_junk()
    elif mode == "orphans":
        view.orphans = [
            OrphanCandidate(
                path=tmp_path / f"o{i}.tmp", kind="tmp", confidence="SEGURO", size_bytes=500,
                last_modified="2026-01-01",
            )
            for i in range(3)
        ]
        view._render_orphans()
    elif mode == "duplicates":
        from winoptiai.storage.duplicate_finder import DuplicateGroup

        view.dup_groups = [
            DuplicateGroup(
                digest=f"h{i}", size_bytes=100, paths=[tmp_path / f"a{i}", tmp_path / f"b{i}"], wasted_bytes=100
            )
            for i in range(3)
        ]
        view._render_duplicates()
    elif mode == "onedrive":
        from winoptiai.storage.onedrive_optimizer import OneDriveCandidate

        view.onedrive_items = [
            OneDriveCandidate(
                item_id=f"d{i}", scope="LOCAL_HYDRATED", name=f"d{i}", location=str(tmp_path / f"d{i}"),
                size_bytes=2048, last_modified="2026-01-01", reason="Pesado",
            )
            for i in range(2)
        ]
        view._render_onedrive()
    return view.table.rowCount()


@pytest.mark.parametrize("mode", ["junk", "duplicates", "orphans", "onedrive", "quarantine"])
def test_select_all_toggle_each_mode(qapp: QApplication, tmp_path: Path, mode: str) -> None:
    view = _storage_view(tmp_path)
    if mode == "quarantine":
        src = tmp_path / "src"
        src.mkdir()
        for i in range(2):
            f = src / f"q{i}.txt"
            f.write_text("x" * 10, encoding="utf-8")
            ok, reason, _rec = view.vault.quarantine_path(f, category="Basura:Prueba", skip_lock_check=True)
            assert ok, reason
    total = _populate(view, mode, tmp_path)
    if mode == "quarantine":
        view._render_quarantine()
        total = view.table.rowCount()
    assert mode in SELECTABLE_TABLE_MODES
    assert total > 0
    chk = view.select_all_chk
    assert not chk.isHidden() and chk.isEnabled()
    assert chk.checkState() == Qt.CheckState.Unchecked

    chk.click()
    assert len(view._selected_row_set()) == total
    assert chk.checkState() == Qt.CheckState.Checked
    assert f"{total} de {total}" in view.selection_lbl.text()

    # Manual partial selection -> tristate
    view.table.clearSelection()
    view.table.selectRow(0)
    if total > 1:
        assert chk.checkState() == Qt.CheckState.PartiallyChecked
    chk.click()  # partial -> select all
    assert len(view._selected_row_set()) == total
    chk.click()  # all -> clear
    assert view._selected_row_set() == set()
    assert chk.checkState() == Qt.CheckState.Unchecked


def test_select_all_bytes_and_indices_route_through_model(qapp: QApplication, tmp_path: Path) -> None:
    view = _storage_view(tmp_path)
    _populate(view, "junk", tmp_path)
    view.select_all_chk.click()
    assert sorted(view._selected_model_indices()) == [0, 1, 2, 3]
    assert view._selected_bytes(view._selected_row_set()) == sum(t.reclaimable_bytes for t in view.junk_targets)


def test_select_all_hidden_in_tree_mode_and_resets_on_mode_switch(qapp: QApplication, tmp_path: Path) -> None:
    view = _storage_view(tmp_path)
    _populate(view, "orphans", tmp_path)
    view.select_all_chk.click()
    assert view.select_all_chk.checkState() == Qt.CheckState.Checked

    view._switch_mode("tree")
    assert view.select_all_chk.isHidden()

    view._switch_mode("junk")  # empty junk list
    assert not view.select_all_chk.isHidden()
    assert view.select_all_chk.checkState() == Qt.CheckState.Unchecked
    assert not view.select_all_chk.isEnabled()
