"""Tests for WinOptiAI v0.3.0: notifications, periodic advisor, progress %, and concurrent UI."""

from __future__ import annotations

from pathlib import Path

from winoptiai.core.notifications import NotificationCenter, PeriodicAdvisor
from winoptiai.core.updater import build_detached_update_script, detect_installed_dir
from winoptiai.storage.duplicate_finder import find_duplicates
from winoptiai.storage.junk_scanner import JunkTarget, scan_junk_targets
from winoptiai.storage.tree_analyzer import analyze_storage_hierarchy


def test_notification_center_crud(tmp_path: Path) -> None:
    nc = NotificationCenter(app_dir=tmp_path)
    assert nc.unread_count() == 0

    n1 = nc.add("COMPLETADO", "AI Boost", "Liberados 1200 MB", action_tab=0)
    n2 = nc.add("SUGERENCIA", "Temporales", "2.1 GB recuperables", action_tab=1)
    assert nc.unread_count() == 2
    assert len(nc.list_items()) == 2

    nc.mark_all_read()
    assert nc.unread_count() == 0

    assert nc.remove(n1.notif_id)
    assert len(nc.list_items()) == 1
    assert nc.list_items()[0].notif_id == n2.notif_id

    nc.clear_all()
    assert nc.list_items() == []


def test_periodic_advisor_low_noise_cooldown() -> None:
    adv = PeriodicAdvisor(cooldown_seconds=7200)
    sugs = adv.evaluate(
        free_ram_gb=1.2,
        ram_threshold_gb=1.8,
        temp_junk_gb=2.0,
        zombie_count=3,
        zombie_ram_mb=320.0,
        now=1000.0,
    )
    assert len(sugs) == 3

    # Must NOT spam within 2h cooldown
    sugs2 = adv.evaluate(
        free_ram_gb=1.1,
        ram_threshold_gb=1.8,
        temp_junk_gb=2.5,
        zombie_count=4,
        zombie_ram_mb=400.0,
        now=2000.0,
    )
    assert sugs2 == []

    # After cooldown expires, relevant changes notify again
    sugs3 = adv.evaluate(
        free_ram_gb=1.2,
        ram_threshold_gb=1.8,
        temp_junk_gb=0.2,
        zombie_count=0,
        zombie_ram_mb=0.0,
        now=9000.0,
    )
    assert len(sugs3) == 1
    assert sugs3[0]["action_tab"] == 0


def test_progress_callbacks_on_engines(tmp_path: Path) -> None:
    f1 = tmp_path / "a.bin"
    f2 = tmp_path / "b.bin"
    f1.write_bytes(b"WINOPTIAI_PROGRESS" * 200)
    f2.write_bytes(b"WINOPTIAI_PROGRESS" * 200)

    dup_pcts: list[int] = []
    find_duplicates([tmp_path], min_size_bytes=512, progress_cb=lambda p, _s: dup_pcts.append(p))
    assert len(dup_pcts) >= 2

    tree_pcts: list[int] = []
    analyze_storage_hierarchy(tmp_path, progress_cb=lambda p, _s: tree_pcts.append(p))
    assert len(tree_pcts) >= 1

    junk_pcts: list[int] = []
    scan_junk_targets(
        [JunkTarget("t", "Test", "Sistema", tmp_path, False, min_age_days=0)],
        progress_cb=lambda p, _s: junk_pcts.append(p),
    )
    assert junk_pcts[-1] == 100


def test_detached_updater_script_generation(tmp_path: Path) -> None:
    setup = tmp_path / "WinOptiAI-Setup.exe"
    inst = Path(r"D:\Custom\WinOptiAI")
    log = tmp_path / "install.log"
    script = build_detached_update_script(setup, inst, log)
    assert "taskkill /F /T /IM WinOptiAI.exe" in script
    assert "/SILENT /CURRENTUSER /CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS" in script
    assert str(inst) in script
    assert detect_installed_dir() is not None


def test_eta_formatter_human_units() -> None:
    from winoptiai.ui.workers import format_eta_seconds

    assert format_eta_seconds(14) == "~14s rest."
    assert format_eta_seconds(125) == "~2m 05s rest."
    assert format_eta_seconds(3720) == "~1h 02m rest."
