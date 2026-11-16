"""Tests for WinOptiAI v0.5.0: pause/cancel/resumable sessions, retention, SMART/BIOS audit, AI Boost protection."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
import json
from pathlib import Path
import threading
import time

import pytest

from winoptiai.ai_optimizer.process_manager import (
    AI_FOREGROUND_AGENTS,
    list_top_processes,
    run_ai_boost,
)
from winoptiai.core.notifications import NotificationCenter
from winoptiai.core.safety_guard import (
    EXPLICIT_TEMP_ALLOWLIST,
    QuarantineRecord,
    QuarantineVault,
    atomic_write_text,
)
from winoptiai.core.sre_policy import SREPolicyConfig, SREPolicyEngine
from winoptiai.core.task_control import (
    SessionManager,
    TaskCanceledError,
    TaskController,
    TaskPausedAndSaved,
)
from winoptiai.core.win32_bridge import get_foreground_pid
from winoptiai.storage import junk_scanner
from winoptiai.storage.duplicate_finder import find_duplicates
from winoptiai.storage.junk_scanner import (
    JunkTarget,
    clean_junk_targets,
    resume_junk_session,
)
from winoptiai.thermal_bios.bios_auditor import run_hardware_bios_audit
from winoptiai.thermal_bios.thermal_controller import apply_thermal_profile


def test_task_controller_pause_resume_and_cancel_duplicates(tmp_path: Path) -> None:
    ctrl = TaskController()
    ctrl.pause()
    assert ctrl.is_paused

    observed: list[str] = []

    def _worker() -> None:
        observed.append(ctrl.checkpoint())

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    time.sleep(0.08)
    assert observed == []  # Blocked cleanly while paused

    ctrl.resume()
    t.join(timeout=2.0)
    assert observed == ["ok"]

    # Create sample files and cancel mid-walk in find_duplicates
    sample_dir = tmp_path / "dups"
    sample_dir.mkdir()
    for i in range(12):
        (sample_dir / f"f{i}.bin").write_bytes(b"samecontent" * 300)

    cancel_ctrl = TaskController()
    cancel_ctrl.cancel()
    with pytest.raises(TaskCanceledError):
        find_duplicates([sample_dir], controller=cancel_ctrl)


def test_pause_save_and_resume_junk_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    junk_dir = tmp_path / "junk_batch"
    junk_dir.mkdir()
    file_count = 80
    for idx in range(file_count):
        (junk_dir / f"tmp_{idx:03d}.log").write_bytes(b"x" * 2048)

    test_target = JunkTarget(
        target_id="test_junk_batch",
        label="Temporales de prueba",
        category="Sistema",
        path=junk_dir,
        allow_system_temp=False,
        min_age_days=0,
    )
    monkeypatch.setattr(junk_scanner, "_build_default_targets", lambda: [test_target])

    vault = QuarantineVault(root_dir=tmp_path / "vault")
    mgr = SessionManager(app_dir=tmp_path / "appdata")
    ctrl = TaskController()

    triggered = False

    def _progress_hook(_pct: int, msg: str) -> None:
        nonlocal triggered
        # Trigger pause+save once batch move begins so checkpoint idx=50 fires cleanly mid-batch
        if not triggered and "Moviendo a respaldo seguro" in msg:
            triggered = True
            ctrl.pause_and_save()

    with pytest.raises(TaskPausedAndSaved) as exc_info:
        clean_junk_targets(
            [test_target],
            vault,
            use_quarantine=True,
            progress_cb=_progress_hook,
            controller=ctrl,
            session_mgr=mgr,
        )

    assert exc_info.value.session_id
    saved_sessions = mgr.list_sessions()
    assert len(saved_sessions) == 1
    saved = saved_sessions[0]
    assert saved.kind == "junk_clean"
    assert len(saved.pending_paths) > 0
    assert saved.processed_items > 0

    # Resume with fresh controller to finish remaining pending files
    res = resume_junk_session(saved, vault, session_mgr=mgr, controller=TaskController())
    assert res["removed"] == len(saved.pending_paths)
    assert res["freed"] > 0
    assert mgr.list_sessions() == []
    remaining_files = list(junk_dir.glob("*.log"))
    assert remaining_files == []


def test_quarantine_30d_retention_and_atomic_io(tmp_path: Path) -> None:
    vault = QuarantineVault(root_dir=tmp_path / "vault")
    old_bundle = vault.items_dir / "old_junk"
    old_bundle.mkdir()
    (old_bundle / "a.tmp").write_text("old", encoding="utf-8")

    fresh_bundle = vault.items_dir / "fresh_junk"
    fresh_bundle.mkdir()
    (fresh_bundle / "b.tmp").write_text("fresh", encoding="utf-8")

    dup_file = vault.items_dir / "dup.dat"
    dup_file.write_text("dup", encoding="utf-8")

    old_ts = (datetime.now().astimezone() - timedelta(days=45)).isoformat()
    fresh_ts = (datetime.now().astimezone() - timedelta(days=2)).isoformat()
    very_old_ts = (datetime.now().astimezone() - timedelta(days=90)).isoformat()

    records = [
        asdict(QuarantineRecord("old1", "C:\\temp\\a.tmp", str(old_bundle), "Basura:Sistema", 1024, "BATCH:1", old_ts, True)),
        asdict(QuarantineRecord("new1", "C:\\temp\\b.tmp", str(fresh_bundle), "Basura:Sistema", 2048, "BATCH:1", fresh_ts, True)),
        asdict(QuarantineRecord("dup1", "C:\\data\\dup.dat", str(dup_file), "Duplicados BLAKE3", 4096, "DEAD", very_old_ts, False)),
    ]
    vault._save_manifest(records)

    res = vault.purge_expired_items(max_age_days=30, only_junk_categories=True)
    assert res["purged"] == 1
    assert res["freed_bytes"] == 1024
    remaining_ids = {r.item_id for r in vault.list_items()}
    assert remaining_ids == {"new1", "dup1"}

    # Shared atomic_write_text & JSON stores
    cfg_path = tmp_path / "atomic_test.json"
    atomic_write_text(cfg_path, json.dumps({"ok": True}))
    assert json.loads(cfg_path.read_text(encoding="utf-8"))["ok"] is True

    nc = NotificationCenter(app_dir=tmp_path / "nc")
    nc.add("INFO", "Prueba", "Mensaje atomico")
    assert len(nc.list_items()) == 1

    eng = SREPolicyEngine(app_dir=tmp_path / "sre")
    eng.save_config(SREPolicyConfig(ram_threshold_gb=2.5))
    assert eng.load_config().ram_threshold_gb == 2.5

    assert "c:\\windows\\softwaredistribution\\download" in EXPLICIT_TEMP_ALLOWLIST
    assert "c:\\windows\\softwaredistribution\\deliveryoptimization" in EXPLICIT_TEMP_ALLOWLIST


def test_ai_boost_foreground_protection_and_cpu_cache() -> None:
    procs_first = list_top_processes(limit=8)
    time.sleep(0.05)
    procs_second = list_top_processes(limit=8)
    assert len(procs_second) >= 3
    assert all(p.cpu_pct >= 0.0 for p in procs_second)

    fg_pid = get_foreground_pid()
    assert fg_pid is None or isinstance(fg_pid, int)
    assert {"code.exe", "antigravity.exe", "python.exe"}.issubset(AI_FOREGROUND_AGENTS)

    res = run_ai_boost(trim_heavy_apps=False, apply_ecoqos=False)
    assert res["trimmed_processes"] == 0
    assert res["ecoqos_applied"] == 0
    assert "freed_mb" in res


def test_hardware_audit_smart_security_and_thermal_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    report = run_hardware_bios_audit()
    assert isinstance(report.smart_summary, str) and len(report.smart_summary) > 0
    assert isinstance(report.disk_events_count, int) and report.disk_events_count >= 0
    assert isinstance(report.security_posture, str) and len(report.security_posture) > 0
    assert isinstance(report.recommendations, list) and len(report.recommendations) >= 1

    # Mock powercfg calls to verify read-back reporting without mutating active user profile
    calls: list[list[str]] = []

    def _fake_powercfg(args: list[str]) -> tuple[bool, str]:
        calls.append(args)
        if args and args[0] == "/q":
            return True, "Indice actual de configuracion de energia CA: 0x00000028"
        return True, "OK"

    import winoptiai.thermal_bios.thermal_controller as tc

    monkeypatch.setattr(tc, "_run_powercfg", _fake_powercfg)
    ok, msg = apply_thermal_profile("balanced")
    assert ok
    assert "verificado" in msg
    assert any(c and c[0] == "/q" for c in calls)


def test_installer_iss_has_elevated_process_guard() -> None:
    iss = (Path(__file__).resolve().parents[1] / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert "PrepareToInstall" in iss
    assert 'tasklist /FI "IMAGENAME eq WinOptiAI.exe"' in iss
