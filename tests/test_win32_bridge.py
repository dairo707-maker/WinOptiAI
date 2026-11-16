"""Tests for native Win32 API bridges (Restart Manager, OneDrive flags, EcoQoS, WorkingSet, Hardlink)."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

from winoptiai.core.safety_guard import is_protected_path, is_safe_to_touch_file
from winoptiai.core.win32_bridge import (
    create_ntfs_hardlink,
    get_locking_processes,
    is_cloud_only_file,
    set_process_ecoqos,
    trim_process_working_set,
)


def test_protected_paths_enforced() -> None:
    assert is_protected_path("C:\\Windows\\System32\\kernel32.dll")
    assert is_protected_path("C:\\Windows\\WinSxS")
    assert is_protected_path("C:\\Program Files\\WindowsApps")
    assert is_protected_path("C:\\Windows\\Temp\\sample.tmp", allow_system_temp=False)
    assert not is_protected_path("C:\\Windows\\Temp\\sample.tmp", allow_system_temp=True)


def test_restart_manager_detects_open_file_lock(tmp_path: Path) -> None:
    locked_file = tmp_path / "locked_by_child.dat"
    locked_file.write_bytes(b"active-session-data" * 100)

    # Spawn a child process holding an open write handle to the file until stdin closes
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import os, sys; "
                "f = open(sys.argv[1], 'r+b'); "
                "print(os.getpid(), flush=True); "
                "sys.stdin.readline()"
            ),
            str(locked_file),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        child_pid = int(proc.stdout.readline().strip())
        time.sleep(0.2)

        lockers = get_locking_processes([locked_file])
        pids = {int(item["pid"]) for item in lockers}
        assert child_pid in pids

        safe, reason = is_safe_to_touch_file(locked_file)
        assert not safe
        assert reason.startswith("EN_USO")
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_cloud_only_false_on_local_file(tmp_path: Path) -> None:
    local = tmp_path / "local.txt"
    local.write_text("local data", encoding="utf-8")
    assert not is_cloud_only_file(local)
    safe, reason = is_safe_to_touch_file(local)
    assert safe
    assert reason == "SEGURO"


def test_ecoqos_and_working_set_on_self() -> None:
    pid = os.getpid()
    assert trim_process_working_set(pid)
    assert set_process_ecoqos(pid, enable=True)
    assert set_process_ecoqos(pid, enable=False)


def test_ntfs_hardlink_creation(tmp_path: Path) -> None:
    src = tmp_path / "origin.bin"
    dst = tmp_path / "linked.bin"
    src.write_bytes(b"WINOPTIAI_HARDLINK_TEST" * 10)
    assert create_ntfs_hardlink(dst, src)
    assert dst.exists()
    assert src.stat().st_ino == dst.stat().st_ino
