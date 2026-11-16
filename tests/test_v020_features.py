"""Tests for WinOptiAI v0.2.0 features: i18n, PDH telemetry, folder tree, duplicate rules, SemVer updater."""

from __future__ import annotations

import os
from pathlib import Path
import time

from winoptiai.core.i18n import SUPPORTED_LANGS, tr
from winoptiai.core.safety_guard import PreOpBackupManager
from winoptiai.core.sre_policy import SREPolicyEngine
from winoptiai.core.telemetry import PdhTelemetryReader
from winoptiai.core.updater import parse_semver
from winoptiai.storage.duplicate_finder import DuplicateGroup, select_duplicates_by_rule
from winoptiai.storage.tree_analyzer import analyze_storage_hierarchy
from winoptiai.thermal_bios.bios_auditor import run_hardware_bios_audit


def test_i18n_translations_complete() -> None:
    for lang in SUPPORTED_LANGS:
        assert tr("about_author", lang)
        assert tr("nav_storage", lang)
        assert tr("btn_ai_boost", lang)


def test_pdh_realtime_cpu_telemetry() -> None:
    reader = PdhTelemetryReader()
    time.sleep(0.25)
    snap = reader.sample()
    assert snap.cpu_freq_mhz > 0.0
    assert len(snap.per_core_pct) >= 1
    assert 0.0 <= snap.cpu_utility_pct <= 100.0


def test_hierarchical_storage_tree_and_formats(tmp_path: Path) -> None:
    videos = tmp_path / "Videos"
    docs = tmp_path / "Docs"
    videos.mkdir()
    docs.mkdir()
    (videos / "clip.mp4").write_bytes(b"V" * 10000)
    (docs / "notes.txt").write_bytes(b"T" * 1500)

    report = analyze_storage_hierarchy(tmp_path)
    assert report.root_node.size_bytes == 11500
    assert report.root_node.file_count == 2
    assert report.root_node.children[0].name == "Videos"
    assert report.formats[0].extension == ".mp4"
    assert report.formats[0].category == "Video"


def test_duplicate_auto_cleaner_rules(tmp_path: Path) -> None:
    dl = tmp_path / "Downloads"
    archive = tmp_path / "Archive"
    dl.mkdir()
    archive.mkdir()

    f_old = dl / "report_copy_long_name.pdf"
    f_new = archive / "r.pdf"
    f_old.write_bytes(b"X" * 2048)
    f_new.write_bytes(b"X" * 2048)

    old_ts = time.time() - 86400
    os.utime(f_old, (old_ts, old_ts))

    grp = DuplicateGroup(digest="abc", size_bytes=2048, paths=[f_old, f_new], wasted_bytes=2048)

    keep_old = select_duplicates_by_rule([grp], "keep_oldest")[0][1]
    assert keep_old == f_old

    keep_new = select_duplicates_by_rule([grp], "keep_newest")[0][1]
    assert keep_new == f_new

    keep_outside_dl = select_duplicates_by_rule([grp], "keep_outside_downloads")[0][1]
    assert keep_outside_dl == f_new


def test_universal_hardware_profiler_and_semver() -> None:
    assert parse_semver("v0.2.1") > parse_semver("0.2.0")
    assert parse_semver("1.0.0") > parse_semver("0.9.9")

    rep = run_hardware_bios_audit()
    assert rep.cpu_vendor in {"Intel", "AMD", "ARM64", "Generico"}
    assert rep.gpu_vendor in {"Intel", "NVIDIA", "AMD", "Generico"}
    assert rep.recommended_ram_threshold_gb >= 1.2
    assert all("action_id" in r and "action_label" in r and "reinicio" in r for r in rep.recommendations)


def test_preop_backups_and_completed_audits(tmp_path: Path) -> None:
    mgr = PreOpBackupManager(root_dir=tmp_path)
    snap_dir = mgr.create_operation_snapshot("test_op", [{"file": "demo.tmp", "size": 123}])
    assert (snap_dir / "snapshot.json").exists()
    pdir = mgr.backup_power_scheme("test_power")
    assert pdir is not None and (pdir / "active_scheme_backup.pow").exists()

    eng = SREPolicyEngine(app_dir=tmp_path)
    eng.mark_audit_completed("apply_cool_profile")
    assert "apply_cool_profile" in eng.config.completed_audit_actions
    eng.reset_completed_audits()
    assert eng.config.completed_audit_actions == []
