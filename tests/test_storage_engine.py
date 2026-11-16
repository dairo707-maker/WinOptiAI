"""Tests for 4-stage BLAKE3 duplicate finder, Quarantine Vault rollback, and orphan/junk scanners."""

from __future__ import annotations

import os
from pathlib import Path
import time

from winoptiai.core.safety_guard import QuarantineVault
from winoptiai.storage.duplicate_finder import (
    deduplicate_group_to_quarantine,
    deduplicate_group_via_hardlink,
    find_duplicates,
)
from winoptiai.storage.junk_scanner import JunkTarget, clean_junk_target, scan_junk_targets
from winoptiai.storage.orphan_hunter import scan_orphan_artifacts


def test_blake3_duplicate_finder_and_hardlink_ignore(tmp_path: Path) -> None:
    payload_a = b"A" * 12000
    payload_b = b"A" * 5000 + b"B" * 2000 + b"A" * 5000  # Same size, identical edges, diff middle

    f1 = tmp_path / "copy1.bin"
    f2 = tmp_path / "sub" / "copy2.bin"
    f2.parent.mkdir()
    diff = tmp_path / "different_middle.bin"

    f1.write_bytes(payload_a)
    f2.write_bytes(payload_a)
    diff.write_bytes(payload_b)

    groups = find_duplicates([tmp_path], min_size_bytes=1024)
    assert len(groups) == 1
    assert len(groups[0].paths) == 2
    assert groups[0].wasted_bytes == len(payload_a)

    # Hardlink deduplication frees physical duplicate and excludes group from future scans
    res = deduplicate_group_via_hardlink(groups[0], f1)
    assert res["linked"] == 1
    assert f1.stat().st_ino == f2.stat().st_ino
    assert find_duplicates([tmp_path], min_size_bytes=1024) == []


def test_quarantine_vault_roundtrip_rollback(tmp_path: Path) -> None:
    vault = QuarantineVault(root_dir=tmp_path / "vault_root")
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()

    dup1 = work_dir / "doc1.txt"
    dup2 = work_dir / "doc2.txt"
    content = ("WinOptiAI contenido de prueba " * 80).encode("utf-8")
    dup1.write_bytes(content)
    dup2.write_bytes(content)

    groups = find_duplicates([work_dir], min_size_bytes=512)
    assert len(groups) == 1

    res = deduplicate_group_to_quarantine(groups[0], dup1, vault)
    assert res["moved"] == 1
    assert dup1.exists()
    assert not dup2.exists()

    records = vault.list_items()
    assert len(records) == 1

    # Rollback restores exact file and SHA-256 integrity
    ok, _ = vault.restore_item(records[0].item_id)
    assert ok
    assert dup2.exists()
    assert dup2.read_bytes() == content
    assert vault.list_items() == []


def test_junk_scanner_and_orphan_hunter(tmp_path: Path) -> None:
    vault = QuarantineVault(root_dir=tmp_path / "vault")
    temp_dir = tmp_path / "fake_temp"
    temp_dir.mkdir()

    old_tmp = temp_dir / "old_cache.tmp"
    old_tmp.write_bytes(b"0" * 4096)
    old_mtime = time.time() - (5 * 86400)
    os.utime(old_tmp, (old_mtime, old_mtime))

    fresh_tmp = temp_dir / "fresh.tmp"
    fresh_tmp.write_bytes(b"1" * 2048)

    stale_orphan = temp_dir / "abandoned.tmp"
    stale_orphan.write_bytes(b"2" * 2048)
    stale_mtime = time.time() - (2 * 86400)
    os.utime(stale_orphan, (stale_mtime, stale_mtime))

    target = JunkTarget("test_tmp", "Temp Prueba", "Sistema", temp_dir, False, min_age_days=3)
    scanned = scan_junk_targets([target])
    assert scanned[0].file_count == 1
    assert scanned[0].reclaimable_bytes == 4096

    cleaned = clean_junk_target(scanned[0], vault, use_quarantine=True)
    assert cleaned["removed"] == 1
    assert not old_tmp.exists()
    assert fresh_tmp.exists()

    orphans = scan_orphan_artifacts(extra_roots=[temp_dir])
    assert any(o.path == stale_orphan for o in orphans)
    assert not any(o.path == fresh_tmp for o in orphans)


def test_batch_junk_cleanup_progress_and_rollback(tmp_path: Path) -> None:
    from winoptiai.storage.junk_scanner import clean_junk_targets

    vault = QuarantineVault(root_dir=tmp_path / "vault_batch")
    temp_dir = tmp_path / "mass_temp"
    sub = temp_dir / "nested"
    sub.mkdir(parents=True)

    old_mtime = time.time() - (3 * 86400)
    for idx in range(320):
        f = sub / f"tmp_{idx:03d}.tmp"
        f.write_bytes(b"X" * 256)
        os.utime(f, (old_mtime, old_mtime))

    target = JunkTarget("mass", "Masivo", "Sistema", temp_dir, False, min_age_days=1)
    scanned = scan_junk_targets([target])
    assert scanned[0].file_count == 320

    pcts: list[int] = []
    t0 = time.perf_counter()
    res = clean_junk_targets(
        scanned,
        vault,
        use_quarantine=True,
        progress_cb=lambda p, _m: pcts.append(p),
    )
    elapsed = time.perf_counter() - t0
    assert res["removed"] == 320
    assert elapsed < 3.0
    assert pcts and pcts[-1] == 100
    assert len(set(pcts)) >= 3

    # Only ONE compact batch record should be stored in Quarantine Vault manifest
    items = vault.list_items()
    assert len(items) == 1
    assert items[0].sha256.startswith("BATCH:320")
    assert not (sub / "tmp_000.tmp").exists()

    # Rollback restores all 320 files cleanly, then purge removes items in batch
    ok, _ = vault.restore_item(items[0].item_id)
    assert ok
    assert (sub / "tmp_000.tmp").exists()
    assert vault.list_items() == []


def test_bulk_over_400_temp_files_fast_and_weighted_progress(tmp_path: Path) -> None:
    from winoptiai.storage.junk_scanner import clean_junk_targets

    vault = QuarantineVault(root_dir=tmp_path / "vault_bulk")
    big_dir = tmp_path / "big_temp"
    small_dir = tmp_path / "small_temp"
    big_dir.mkdir()
    small_dir.mkdir()

    old_mtime = time.time() - (3 * 86400)
    for idx in range(520):
        f = big_dir / f"bulk_{idx:03d}.tmp"
        f.write_bytes(b"B" * 64)
        os.utime(f, (old_mtime, old_mtime))
    tiny = small_dir / "one.tmp"
    tiny.write_bytes(b"S" * 64)
    os.utime(tiny, (old_mtime, old_mtime))

    t1 = JunkTarget("big", "Grande", "Sistema", big_dir, False, min_age_days=1)
    t2 = JunkTarget("small", "Pequeno", "Sistema", small_dir, False, min_age_days=1)
    scanned = scan_junk_targets([t1, t2])
    assert scanned[0].file_count == 520

    pcts: list[int] = []
    t0 = time.perf_counter()
    res = clean_junk_targets(
        scanned,
        vault,
        use_quarantine=True,
        progress_cb=lambda p, _m: pcts.append(p),
    )
    elapsed = time.perf_counter() - t0
    assert res["removed"] == 521
    assert elapsed < 3.0
    assert pcts and pcts[-1] == 100
    assert any(10 < p < 95 for p in pcts)
