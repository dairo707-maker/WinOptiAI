"""WinOptiAI v0.5.9: Boveda fuera de escaneos, programas protegidos en Duplicados, cuarentena
instantanea con Deshacer, microprocesos (lotes, cache de huellas, Guardar Pausa en analisis)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from winoptiai.core import safety_guard as sg  # noqa: E402
from winoptiai.core.safety_guard import PreOpBackupManager, QuarantineVault  # noqa: E402
from winoptiai.core.sre_policy import SREPolicyEngine  # noqa: E402
from winoptiai.core.task_control import TaskController, TaskSaveRequested, stop_point  # noqa: E402
from winoptiai.storage.duplicate_finder import (  # noqa: E402
    DuplicateGroup,
    HashCache,
    find_duplicates,
    select_duplicates_by_rule,
)
from winoptiai.storage.orphan_hunter import OrphanCandidate  # noqa: E402
from winoptiai.storage.program_guard import program_dir_reason  # noqa: E402
from winoptiai.storage.tree_analyzer import analyze_storage_hierarchy  # noqa: E402
from winoptiai.ui import workers  # noqa: E402
from winoptiai.ui.fx import set_animations_enabled  # noqa: E402
from winoptiai.ui.views import storage_view as sv  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    set_animations_enabled(False)
    return QApplication.instance() or QApplication([])


def _write(p: Path, data: bytes) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


# ---------------------------------------------------------------- 1. Boveda fuera de escaneos
def test_vault_contents_never_reappear_in_scans(tmp_path: Path) -> None:
    vault = QuarantineVault(root_dir=tmp_path / "datos_app")
    src = _write(tmp_path / "docs" / "informe.pdf", b"p" * 5000)
    _write(tmp_path / "docs" / "copia_informe.pdf", b"p" * 5000)
    ok, _m, rec = vault.quarantine_path(src, category="Prueba", skip_lock_check=True)
    assert ok and rec is not None
    groups = find_duplicates([tmp_path])
    assert all("datos_app" not in str(p) for g in groups for p in g.paths)
    rep = analyze_storage_hierarchy(tmp_path)
    assert all("datos_app" not in str(p) for p, _e, _s in rep.heaviest_files)
    assert sg.is_internal_app_path(Path(rec.vault_path))


# ---------------------------------------------------------------- 2. Programas protegidos
def test_duplicates_skip_programs_envs_and_installs(tmp_path: Path) -> None:
    data = b"x" * 4096
    _write(tmp_path / "Documentos" / "a.bin", data)
    _write(tmp_path / "Documentos" / "b.bin", data)
    _write(tmp_path / "proyecto" / ".venv" / "Lib" / "c.bin", data)  # entorno virtual
    _write(tmp_path / "py" / "Lib" / "site-packages" / "d.bin", data)
    _write(tmp_path / "app_portable" / "app.exe", b"MZ" * 900)
    _write(tmp_path / "app_portable" / "core.dll", b"DL" * 900)
    _write(tmp_path / "app_portable" / "e.bin", data)  # instalacion completa (exe + dll)
    _write(tmp_path / "entorno" / "pyvenv.cfg", b"home = x\n" * 200)
    _write(tmp_path / "entorno" / "f.bin", data)
    groups = find_duplicates([tmp_path])
    assert len(groups) == 1
    names = sorted(p.name for p in groups[0].paths)
    assert names == ["a.bin", "b.bin"]
    assert groups.protected_dirs >= 3


def test_copied_folder_structure_is_protected(tmp_path: Path) -> None:
    for folder in ("Proyecto", "Proyecto - copia"):
        for i in range(5):
            _write(tmp_path / folder / f"modulo_{i}.txt", (f"contenido {i} " * 300).encode())
    _write(tmp_path / "suelto1.dat", b"z" * 3000)
    _write(tmp_path / "suelto2.dat", b"z" * 3000)
    groups = find_duplicates([tmp_path])
    structural = [g for g in groups if g.protected_reason]
    assert len(structural) == 5
    plan = select_duplicates_by_rule(groups)
    removed = [p for _g, _k, rem in plan for p in rem]
    assert len(removed) == 1 and removed[0].suffix == ".dat"


def test_rule_keeps_user_copy_and_never_touches_program_copies(tmp_path: Path) -> None:
    user = tmp_path / "Descargas" / "manual.pdf"
    prog = tmp_path / "AppData" / "Local" / "Programs" / "App" / "manual.pdf"
    grp = DuplicateGroup(digest="d", size_bytes=10, paths=[prog, user], wasted_bytes=10)
    assert select_duplicates_by_rule([grp]) == []  # una sola copia del usuario: se conserva
    assert program_dir_reason(prog.parent)


# ---------------------------------------------------------------- 3. Microprocesos
def test_quarantine_many_commits_in_small_batches(tmp_path: Path, monkeypatch) -> None:
    vault = QuarantineVault(root_dir=tmp_path / "app")
    files = [(_write(tmp_path / "t" / f"f{i}.tmp", b"q" * 10), "Prueba") for i in range(120)]
    real_move = vault._move_fast
    calls = {"n": 0}

    def _boom(src, dst):
        calls["n"] += 1
        if calls["n"] == 81:
            raise RuntimeError("cierre inesperado simulado")
        real_move(src, dst)

    monkeypatch.setattr(vault, "_move_fast", _boom)
    with pytest.raises(RuntimeError):
        vault.quarantine_many(files)
    # antes: 0 registros (todo se escribia al final); ahora lo movido queda registrado
    assert len(vault.list_items()) >= 50


def test_bulk_restore_puts_everything_back_without_overwriting(tmp_path: Path) -> None:
    vault = QuarantineVault(root_dir=tmp_path / "app")
    files = [_write(tmp_path / "lib" / f"m{i}.py", f"x{i}".encode() * 50) for i in range(30)]
    res = vault.quarantine_many([(f, "Duplicado BLAKE3") for f in files])
    assert res["moved"] == 30 and not files[0].exists()
    _write(files[0], b"nuevo")  # alguien recreo el original: no se sobrescribe
    out = vault.restore_items_bulk(predicate=lambda r: r["category"] == "Duplicado BLAKE3", checkpoint_every=7)
    assert out["restored"] == 29 and out["conflicts"] == 1
    assert files[5].read_bytes() == b"x5" * 50 and files[0].read_bytes() == b"nuevo"
    assert len(vault.list_items()) == 1


def test_hash_cache_reuses_fingerprints(tmp_path: Path) -> None:
    for name in ("a.bin", "b.bin", "c.bin"):
        _write(tmp_path / "data" / name, b"k" * 9000)
    cache = HashCache(tmp_path / "cache.sqlite")
    find_duplicates([tmp_path / "data"], cache=cache)
    first_misses = cache.misses
    cache.hits = cache.misses = 0
    groups = find_duplicates([tmp_path / "data"], cache=cache)
    assert first_misses > 0 and cache.misses == 0 and cache.hits >= 3
    assert len(groups) == 1
    cache.close()


def test_save_pause_in_analysis_creates_resumable_session(qapp: QApplication) -> None:
    ctrl = TaskController()
    ctrl.pause_and_save()
    with pytest.raises(TaskSaveRequested):
        stop_point(ctrl)

    def _scan(controller=None):
        controller.pause_and_save()
        stop_point(controller)

    task = workers.AsyncTask("Duplicados", _scan)
    task.save_handler = lambda pct: "sesion123"
    got: list[str] = []
    task.signals.paused_saved.connect(lambda _t, sid, _p, _d: got.append(sid), Qt.ConnectionType.DirectConnection)
    task.run()
    assert got == ["sesion123"]


# ---------------------------------------------------------------- 4. Cuarentena instantanea + Deshacer
def _view(tmp_path: Path) -> sv.StorageView:
    return sv.StorageView(
        QuarantineVault(root_dir=tmp_path / "app"),
        PreOpBackupManager(root_dir=tmp_path / "app"),
        SREPolicyEngine(app_dir=tmp_path / "app"),
        lambda *a, **k: None,
        lambda _m: None,
    )


def test_quick_quarantine_removes_rows_without_rescan_and_undo_restores(qapp: QApplication, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sv, "play_recycle_sound", lambda: True)
    view = _view(tmp_path)
    view.resize(900, 600)
    view.show()
    f1 = _write(tmp_path / "x" / "viejo.tmp", b"a" * 100)
    f2 = _write(tmp_path / "x" / "otro.tmp", b"b" * 100)
    view._switch_mode("orphans")
    view.orphans = [
        OrphanCandidate(path=f, kind="tmp", confidence="SEGURO", size_bytes=100, last_modified="x") for f in (f1, f2)
    ]
    view._render_orphans()
    view.table.selectRow(0)
    captured: list[list[Path]] = []
    monkeypatch.setattr(view, "_quarantine_paths", lambda paths, cat: captured.append(list(paths)))
    view.table.setFocus()
    QApplication.sendEvent(view.table, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier))
    assert len(captured) == 1 and len(captured[0]) == 1  # Supr -> envio inmediato de la seleccion

    res = view.vault.quarantine_many([(captured[0][0], "Huerfano")])
    view._after_quick_quarantine(res, "Huerfano", "orphans", [])
    assert view.table.rowCount() == 1 and not captured[0][0].exists()
    assert "Boveda Cuarentena (1)" in view.mode_buttons["quarantine"].text()
    assert view._undo_toast.isVisible()

    ids = [iid for iid, _o in res["moved_items"]]
    undo = {"dup_groups": [], "orphans": view.orphans + [o for o in [OrphanCandidate(path=captured[0][0], kind="tmp", confidence="SEGURO", size_bytes=100, last_modified="x")]], "tree_report": None}
    for iid in ids:
        view.vault.restore_item(iid)
    view._restore_lists(undo)
    view._render_current_mode()
    assert captured[0][0].exists() and view.table.rowCount() == 2


def test_internal_paths_are_never_quarantined_again(qapp: QApplication, tmp_path: Path) -> None:
    view = _view(tmp_path)
    inside = _write(view.vault.items_dir / "abc__x.rar", b"r" * 10)
    view._quarantine_paths([inside], "Arbol/Formato")
    assert "ya estan en la Boveda" in view.summary_lbl.text()


# ---------------------------------------------------------------- 5. Cierre total
def test_shutdown_kills_app_children_but_keeps_protected() -> None:
    import subprocess
    import time as _t

    from winoptiai.core import win32_bridge as wb

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    worker = subprocess.Popen(["ping", "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL, creationflags=flags)
    keeper = subprocess.Popen(["ping", "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL, creationflags=flags)
    wb.protect_child_pid(keeper.pid)
    try:
        _t.sleep(0.25)
        assert worker.poll() is None and keeper.poll() is None
        res = wb.terminate_app_child_processes()
        _t.sleep(0.5)
        assert worker.poll() is not None  # proceso derivado de la app: cerrado
        assert keeper.poll() is None  # protegido (como el actualizador): sigue vivo
        assert res["closed"] >= 1
    finally:
        keeper.kill()
        worker.kill()
        wb._PROTECTED_CHILD_PIDS.discard(keeper.pid)


def test_quarantine_many_stops_on_cancel_and_keeps_record(tmp_path: Path) -> None:
    vault = QuarantineVault(root_dir=tmp_path / "app")
    files = [(_write(tmp_path / "c" / f"f{i}.tmp", b"w" * 10), "Prueba") for i in range(40)]
    ctrl = TaskController()
    calls = {"n": 0}
    real_move = vault._move_fast

    def _move(src, dst):
        calls["n"] += 1
        if calls["n"] == 10:
            ctrl.cancel()  # el usuario cierra la app a mitad
        real_move(src, dst)

    vault._move_fast = _move
    res = vault.quarantine_many(files, controller=ctrl)
    assert res["interrupted"] == "cancel" and res["moved"] == 10
    assert len(vault.list_items()) == 10  # lo movido quedo registrado (restaurable)


def test_hang_watchdog_ignores_system_sleep(tmp_path: Path, monkeypatch) -> None:
    import time as _t

    from winoptiai.core import crash_guard as cg

    guard = cg.CrashGuard(app_dir=tmp_path, version="0.5.9")
    clock = {"now": 1000.0}
    monkeypatch.setattr(cg.time, "monotonic", lambda: clock["now"])
    guard.start_hang_watchdog(threshold_s=8.0, poll_s=0.02)
    try:
        _t.sleep(0.1)
        clock["now"] += 7200  # portatil suspendido 2 horas: la interfaz no "se bloqueo"
        _t.sleep(0.2)
        assert guard.hang_count == 0
    finally:
        guard.stop_hang_watchdog()


def test_recycle_sound_never_raises() -> None:
    from winoptiai.core.win32_bridge import play_recycle_sound, recycle_sound_path

    assert isinstance(recycle_sound_path(), str)
    assert isinstance(play_recycle_sound(), bool)
