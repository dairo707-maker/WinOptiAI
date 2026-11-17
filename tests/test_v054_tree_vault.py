"""WinOptiAI v0.5.4: mapa jerarquico, archivos mas pesados por tipo y purga robusta de la Boveda."""

from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRectF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from winoptiai.core.safety_guard import PreOpBackupManager, QuarantineVault, force_remove_tree  # noqa: E402
from winoptiai.core.sre_policy import SREPolicyEngine  # noqa: E402
from winoptiai.storage.tree_analyzer import analyze_storage_hierarchy  # noqa: E402
from winoptiai.ui.theme import get_palette  # noqa: E402
from winoptiai.ui.treemap import TreemapWidget, squarify  # noqa: E402
from winoptiai.ui.views import storage_view as sv  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view(tmp_path: Path) -> sv.StorageView:
    return sv.StorageView(
        QuarantineVault(root_dir=tmp_path / "app"),
        PreOpBackupManager(root_dir=tmp_path / "app"),
        SREPolicyEngine(app_dir=tmp_path / "app"),
        lambda *a, **k: None,
        lambda _m: None,
    )


def _sample_tree(root: Path) -> None:
    (root / "videos").mkdir(parents=True)
    (root / "docs" / "sub").mkdir(parents=True)
    for i in range(3):
        (root / "videos" / f"v{i}.mp4").write_bytes(b"v" * (5000 * (i + 1)))
    for i in range(4):
        (root / "docs" / f"d{i}.pdf").write_bytes(b"d" * (1000 * (i + 1)))
    (root / "docs" / "sub" / "tabla.xlsx").write_bytes(b"x" * 7000)
    (root / "suelto.zip").write_bytes(b"z" * 9000)


def test_onedrive_unpinned_folders_are_traversed_but_cloud_files_skipped() -> None:
    from winoptiai.core.win32_bridge import attrs_skip_entry

    onedrive_dir = 0x100031  # atributos reales de src/ en OneDrive: DIRECTORY|ARCHIVE|READONLY|UNPINNED
    assert attrs_skip_entry(onedrive_dir, is_dir=True) is False
    assert attrs_skip_entry(0x00400000 | 0x10, is_dir=True) is True  # carpeta que requiere la nube
    assert attrs_skip_entry(0x100020, is_dir=False) is True  # archivo UNPINNED: nunca se lee
    assert attrs_skip_entry(0x00400020, is_dir=False) is True  # archivo solo en la nube
    assert attrs_skip_entry(0x20, is_dir=False) is False
    assert attrs_skip_entry(0x410, is_dir=True) is True  # junction / reparse


def test_squarify_fills_area_without_overlap() -> None:
    rect = QRectF(0, 0, 400, 300)
    rects = squarify([50, 30, 10, 5, 5], rect)
    assert abs(sum(r.width() * r.height() for r in rects) - 400 * 300) < 1.0
    for i, a in enumerate(rects):
        assert rect.adjusted(-0.01, -0.01, 0.01, 0.01).contains(a)
        for b in rects[i + 1 :]:
            inter = a.intersected(b)
            assert inter.width() * inter.height() < 0.5


def test_analyzer_keeps_top_files_per_extension(tmp_path: Path) -> None:
    _sample_tree(tmp_path)
    rep = analyze_storage_hierarchy(tmp_path)
    mp4 = next(f for f in rep.formats if f.extension == ".mp4")
    assert [p.name for p, _ in mp4.top_files] == ["v2.mp4", "v1.mp4", "v0.mp4"]
    assert rep.heaviest_files[0][0].name == "v2.mp4"  # top global incluye archivos < 5 MB
    assert len(rep.heaviest_files) == 9


def test_treemap_navigation_and_reveal(qapp: QApplication, tmp_path: Path) -> None:
    _sample_tree(tmp_path)
    rep = analyze_storage_hierarchy(tmp_path)
    tm = TreemapWidget(lambda: get_palette("dark"))
    tm.resize(600, 400)
    tm.set_root(rep.root_node)
    labels = {t.label for t in tm._tiles if t.depth == 1}
    assert {"videos", "docs", "(archivos en esta carpeta)"} <= labels
    revealed: list[str] = []
    tm.reveal_requested.connect(revealed.append)
    docs = next(t for t in tm._tiles if t.depth == 1 and t.label == "docs")
    tm.enter(docs.node)
    assert tm.can_go_up() and tm.breadcrumb().endswith("docs")
    sub = next(t for t in tm._tiles if t.depth == 1 and t.label == "sub")
    assert tm.tile_at(sub.rect.center().toPoint()) is not None
    tm.reveal_requested.emit(tm._path_of(sub))
    assert revealed == [str(tmp_path / "docs" / "sub")]
    tm.go_up()
    assert not tm.can_go_up()
    tm.grab()  # pintar sin errores


def test_heavy_files_tab_filters_by_type_and_reveals(qapp: QApplication, tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "data"
    _sample_tree(data)
    view = _view(tmp_path)
    view._switch_mode("tree")
    view.tree_report = analyze_storage_hierarchy(data)
    view._render_tree()
    assert view.heavy_tree.topLevelItemCount() == 9  # top global

    idx = view.heavy_type_combo.findData("cat:Video")
    view.heavy_type_combo.setCurrentIndex(idx)
    names = [view.heavy_tree.topLevelItem(i).text(0) for i in range(view.heavy_tree.topLevelItemCount())]
    assert names == ["v2.mp4", "v1.mp4", "v0.mp4"]

    view.heavy_type_combo.setCurrentIndex(0)
    view.heavy_view_combo.setCurrentIndex(view.heavy_view_combo.findData("group"))
    groups = {view.heavy_tree.topLevelItem(i).text(0).split()[0]: view.heavy_tree.topLevelItem(i) for i in range(view.heavy_tree.topLevelItemCount())}
    assert groups[".pdf"].childCount() == 4

    opened: list[Path] = []
    monkeypatch.setattr(sv, "reveal_in_explorer", lambda p: opened.append(Path(p)) or True)
    view._reveal_heavy_item(groups[".pdf"].child(0))
    assert opened and opened[0].suffix == ".pdf" and opened[0].exists()

    view.tree_tabs.setCurrentIndex(2)
    view.heavy_tree.setCurrentItem(groups[".pdf"].child(0))
    assert view._get_selected_explorer_path() == opened[0]


def test_force_remove_tree_handles_readonly_and_long_paths(tmp_path: Path) -> None:
    root = tmp_path / "batch"
    deep = root
    while len(str(deep)) < 300:
        deep = deep / "carpeta_muy_larga_de_pyrefly_typeshed"
    os.makedirs("\\\\?\\" + str(deep) if os.name == "nt" else deep)
    target = str(deep / "singapore.pyi")
    with open("\\\\?\\" + target if os.name == "nt" else target, "w", encoding="utf-8") as fh:
        fh.write("x")
    ro = root / "solo_lectura.txt"
    ro.write_text("y", encoding="utf-8")
    os.chmod(ro, stat.S_IREAD)
    assert force_remove_tree(root) == []
    assert not root.exists()


def test_purge_vault_with_readonly_files_and_orphans(tmp_path: Path) -> None:
    vault = QuarantineVault(root_dir=tmp_path / "app")
    src = tmp_path / "temp"
    src.mkdir()
    files = []
    for i in range(3):
        f = src / f"f{i}.pyi"
        f.write_text("z" * 10, encoding="utf-8")
        os.chmod(f, stat.S_IREAD)  # como el lote real de pyrefly (archivos de solo lectura)
        files.append((f, 10))
    res = vault.quarantine_batch_bundle(files, base_dir=src, bundle_name="user_temp", category="Basura:Sistema")
    assert res["moved"] == 3
    orphan = vault.items_dir / "21cdda70d17f__strings.json"
    orphan.write_text("{}", encoding="utf-8")
    assert vault.list_orphan_entries() == [orphan]

    ids = [r.item_id for r in vault.list_items()]
    out = vault.purge_items(ids, include_orphans=True)
    assert out["purged"] == 1 and out["failed"] == 0 and out["orphans_removed"] == 1
    assert vault.list_items() == [] and list(vault.items_dir.iterdir()) == []


def test_purge_reports_blocked_files_and_keeps_record(tmp_path: Path, monkeypatch) -> None:
    from winoptiai.core import safety_guard as sg

    vault = QuarantineVault(root_dir=tmp_path / "app")
    src = tmp_path / "temp"
    src.mkdir()
    (src / "a.tmp").write_text("a" * 50, encoding="utf-8")
    (src / "b.tmp").write_text("b" * 70, encoding="utf-8")
    vault.quarantine_batch_bundle([(src / "a.tmp", 50), (src / "b.tmp", 70)], base_dir=src, bundle_name="t", category="Basura:x")
    rec = vault.list_items()[0]
    real_unlink = os.unlink

    def _locked(p, *a, **k):  # simular b.tmp abierto por otro programa
        if str(p).endswith("b.tmp"):
            raise PermissionError("en uso")
        return real_unlink(p, *a, **k)

    monkeypatch.setattr(sg.os, "unlink", _locked)
    out = vault.purge_items([rec.item_id])
    assert out["purged"] == 0 and out["failed"] == 1 and out["blocked_files"] == 1
    assert any(s.endswith("b.tmp") for s in out["blocked_samples"])
    kept = vault.list_items()
    assert len(kept) == 1 and kept[0].size_bytes == 70  # tamano restante real
