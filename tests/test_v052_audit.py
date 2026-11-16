"""Regression tests for WinOptiAI v0.5.2 audit: recursive __lt__ crash, cross-mode renders, races."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from winoptiai.core.safety_guard import PreOpBackupManager, QuarantineVault  # noqa: E402
from winoptiai.core.sre_policy import SREPolicyEngine  # noqa: E402
from winoptiai.storage.duplicate_finder import (  # noqa: E402
    DuplicateGroup,
    deduplicate_group_via_hardlink,
    find_duplicates,
)
from winoptiai.storage.orphan_hunter import OrphanCandidate  # noqa: E402
from winoptiai.ui import workers  # noqa: E402
from winoptiai.ui.views import storage_view as sv  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "src"


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _run_isolated(code: str) -> subprocess.CompletedProcess:
    """Run Qt code in a child process so a native crash cannot kill the pytest session."""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(SRC))
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)], capture_output=True, text=True, timeout=60, env=env
    )


def test_tree_sort_by_text_column_does_not_overflow_stack() -> None:
    # Reproduce el crash real (crash.log 17:37): ordenar el arbol por CARPETA (sin UserRole).
    res = _run_isolated(
        """
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QTreeWidget
        from winoptiai.ui.widgets import NumericTreeItem
        app = QApplication([])
        t = QTreeWidget(); t.setColumnCount(2); t.setSortingEnabled(True)
        for name in ["b", "A", "c"]:
            it = NumericTreeItem([name, "x"]); it.setData(1, Qt.ItemDataRole.UserRole, 1.0)
            t.addTopLevelItem(it)
        t.sortItems(0, Qt.SortOrder.AscendingOrder)
        print([t.topLevelItem(i).text(0) for i in range(3)])
        t.sortItems(1, Qt.SortOrder.DescendingOrder)
        print("OK")
        """
    )
    assert res.returncode == 0, res.stderr[-800:]
    assert "['A', 'b', 'c']" in res.stdout and "OK" in res.stdout


def test_table_sort_mixed_items_does_not_overflow_stack() -> None:
    res = _run_isolated(
        """
        from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem
        from winoptiai.ui.widgets import NumericTableItem
        app = QApplication([])
        tb = QTableWidget(3, 1)
        tb.setItem(0, 0, NumericTableItem("10", 10))
        tb.setItem(1, 0, QTableWidgetItem("zeta"))
        tb.setItem(2, 0, NumericTableItem("2", 2))
        tb.sortItems(0)
        print("OK")
        """
    )
    assert res.returncode == 0, res.stderr[-800:]
    assert "OK" in res.stdout


def _view(tmp_path: Path, run_async=None) -> sv.StorageView:
    return sv.StorageView(
        QuarantineVault(root_dir=tmp_path),
        PreOpBackupManager(root_dir=tmp_path),
        SREPolicyEngine(app_dir=tmp_path),
        run_async or (lambda *a, **k: None),
        lambda _m: None,
    )


def test_scan_finishing_in_other_mode_does_not_overwrite_table(qapp: QApplication, tmp_path: Path) -> None:
    view = _view(tmp_path)
    view._switch_mode("orphans")
    view.orphans = [
        OrphanCandidate(path=tmp_path / "o.tmp", kind="tmp", confidence="SEGURO", size_bytes=1, last_modified="x")
    ]
    view._render_orphans()
    assert view.table.rowCount() == 1

    groups = [
        DuplicateGroup(digest=f"h{i}", size_bytes=5, paths=[tmp_path / f"a{i}", tmp_path / f"b{i}"], wasted_bytes=5)
        for i in range(4)
    ]
    view._on_dups_scanned(groups)  # duplicates scan completes while user is in Huerfanos
    assert view.table.rowCount() == 1
    assert view.table.item(0, 3).text() == str(tmp_path / "o.tmp")
    assert view.dup_groups == groups  # data kept for when the user returns

    view._switch_mode("duplicates")
    assert view.table.rowCount() == 4


def test_rescan_after_action_only_for_originating_mode(qapp: QApplication, tmp_path: Path, monkeypatch) -> None:
    view = _view(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(view, "_on_primary_action", lambda: calls.append(view.mode))
    view._switch_mode("duplicates")
    view.junk_targets = [object()]  # type: ignore[list-item]
    view._rescan_after_action("junk")
    assert calls == [] and view.junk_targets == []  # no folder dialog popping in Duplicados
    view._switch_mode("junk")
    view._rescan_after_action("junk")
    assert calls == ["junk"]


def test_duplicate_scan_root_is_captured_at_launch(qapp: QApplication, tmp_path: Path, monkeypatch) -> None:
    launched: list = []
    view = _view(tmp_path, run_async=lambda fn, cb, *a, **k: launched.append(fn))
    folder_a, folder_b = tmp_path / "A", tmp_path / "B"
    folder_a.mkdir()
    folder_b.mkdir()
    seen: list[Path] = []
    monkeypatch.setattr(sv, "find_duplicates", lambda roots, **_k: seen.extend(roots) or [])
    monkeypatch.setattr(sv.QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(folder_a)))

    view._switch_mode("duplicates")
    view._on_primary_action()
    view.scan_root = folder_b  # user picks another folder (e.g. tree) before the worker starts
    launched[0]()
    assert seen == [folder_a]


def test_progress_signals_are_throttled(qapp: QApplication) -> None:
    def _busy(progress_cb=None) -> int:
        for i in range(20000):
            progress_cb(10 + (i % 3), "archivo")
        return 1

    task = workers.AsyncTask("t", _busy)
    count = {"n": 0}
    task.signals.progress.connect(lambda *_a: count.__setitem__("n", count["n"] + 1), Qt.ConnectionType.DirectConnection)
    task.run()
    assert count["n"] < 200  # antes: ~20000 eventos encolados en el hilo GUI
    assert task.percent == 100


def test_preview_reads_only_head_and_skips_cloud_only(qapp: QApplication, tmp_path: Path, monkeypatch) -> None:
    view = _view(tmp_path)
    big = tmp_path / "big.log"
    big.write_text("A" * 200_000, encoding="utf-8")
    copy = tmp_path / "copy.log"
    copy.write_text("A" * 200_000, encoding="utf-8")
    view._switch_mode("duplicates")
    view.dup_groups = [DuplicateGroup(digest="d", size_bytes=200_000, paths=[big, copy], wasted_bytes=200_000)]
    view._render_duplicates()
    view.table.selectRow(0)
    assert len(view.preview_text.toPlainText()) == sv.PREVIEW_TEXT_MAX_BYTES

    monkeypatch.setattr(sv, "is_cloud_only_file", lambda _p: True)
    view.table.clearSelection()
    view.table.selectRow(0)
    assert "solo en la nube" in view.preview_text.toPlainText()


def test_storage_task_limiter_allows_two_and_releases(qapp: QApplication, tmp_path: Path) -> None:
    pending: list[tuple] = []
    view = _view(tmp_path, run_async=lambda fn, cb, label, *a, **k: pending.append((cb, k["on_error"], label)))
    errors: list[str] = []
    for i in range(3):
        view.run_async(lambda: 1, lambda _r: None, f"T{i}", on_error=errors.append)
    assert [p[2] for p in pending] == ["T0", "T1"]
    assert len(errors) == 1 and "2 procesos" in errors[0]

    pending[0][0](1)  # T0 finishes -> slot released
    pending[1][1]("cancelado")  # T1 canceled/paused -> slot released (user on_error also called)
    assert view._active_storage_tasks == 0 and errors[-1] == "cancelado"
    view.run_async(lambda: 1, lambda _r: None, "T3")
    assert pending[-1][2] == "T3"


def test_hardlink_requires_confirmation(qapp: QApplication, tmp_path: Path, monkeypatch) -> None:
    launched: list = []
    view = _view(tmp_path, run_async=lambda *a, **k: launched.append(a))
    view._switch_mode("duplicates")
    view.dup_groups = [DuplicateGroup(digest="d", size_bytes=1, paths=[tmp_path / "a", tmp_path / "b"], wasted_bytes=1)]
    view._render_duplicates()
    view.table.selectRow(0)
    monkeypatch.setattr(sv.QMessageBox, "warning", staticmethod(lambda *a, **k: sv.QMessageBox.StandardButton.No))
    view._on_hardlink_duplicates()
    assert launched == [] and "cancelado" in view.summary_lbl.text()
    monkeypatch.setattr(sv.QMessageBox, "warning", staticmethod(lambda *a, **k: sv.QMessageBox.StandardButton.Yes))
    view._on_hardlink_duplicates()
    assert len(launched) == 1


def test_hardlink_skips_copies_modified_after_scan(tmp_path: Path) -> None:
    f1, f2 = tmp_path / "a.bin", tmp_path / "b.bin"
    f1.write_bytes(b"x" * 4096)
    f2.write_bytes(b"x" * 4096)
    groups = find_duplicates([tmp_path])
    assert len(groups) == 1
    f2.write_bytes(b"y" * 4096)  # edited after the scan: unique data now
    res = deduplicate_group_via_hardlink(groups[0], f1)
    assert res["linked"] == 0 and res["skipped"] == 1
    assert f2.read_bytes() == b"y" * 4096  # untouched
