"""Storage Manager view: Junk, BLAKE3 Duplicates + Preview/Auto-Cleaner, Hierarchy Tree, Orphans, Quarantine."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from typing import Callable

from PySide6.QtCore import QPoint, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.i18n import tr
from ...core.safety_guard import PreOpBackupManager, QuarantineVault
from ...core.sre_policy import SREPolicyEngine
from ...core.win32_bridge import is_user_admin, reveal_in_explorer, run_elevated_command
from ...storage.duplicate_finder import (
    DuplicateGroup,
    deduplicate_group_via_hardlink,
    find_duplicates,
    quarantine_duplicates_plan,
    select_duplicates_by_rule,
)
from ...storage.junk_scanner import JunkTarget, clean_junk_targets, scan_junk_targets
from ...storage.onedrive_optimizer import (
    OneDriveCandidate,
    OneDriveQuota,
    OneDriveTokenStore,
    dehydrate_local_onedrive_files,
    discover_onedrive_roots,
    ensure_valid_access_token,
    fetch_cloud_drive_quota,
    scan_cloud_onedrive,
    scan_local_onedrive_candidates,
    start_oauth_pkce_login,
    trash_cloud_onedrive_items,
)
from ...storage.orphan_hunter import OrphanCandidate, quarantine_orphans, scan_orphan_artifacts
from ...storage.tree_analyzer import FolderNode, StorageHierarchyReport, analyze_storage_hierarchy
from ..svg_icons import load_svg_icon
from ..theme import format_bytes, get_palette
from ..widgets import (
    GlassPanel,
    NumericTableItem,
    NumericTreeItem,
    StatusTag,
    configure_sortable_table,
)


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".ico"}
TEXT_EXTS = {".txt", ".md", ".py", ".json", ".csv", ".log", ".yaml", ".yml", ".xml", ".ini", ".iss"}


class StorageView(QWidget):
    """Surgical storage view with sortable tables, duplicate preview/auto-cleaner, and folder tree."""

    def __init__(
        self,
        vault: QuarantineVault,
        backup_mgr: PreOpBackupManager,
        policy: SREPolicyEngine,
        run_async: Callable,
        notify_cb: Callable[[str], None],
        lang: str = "es",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.vault = vault
        self.backup_mgr = backup_mgr
        self.policy = policy
        self.run_async = run_async
        self.notify_cb = notify_cb
        self.lang = lang

        self.mode = "junk"  # "junk" | "duplicates" | "tree" | "orphans" | "quarantine"
        self.junk_targets: list[JunkTarget] = []
        self.dup_groups: list[DuplicateGroup] = []
        self.orphans: list[OrphanCandidate] = []
        self.onedrive_items: list[OneDriveCandidate] = []
        self.onedrive_quota: OneDriveQuota | None = None
        self.onedrive_store = OneDriveTokenStore()
        self.tree_report: StorageHierarchyReport | None = None
        self.scan_root: Path = Path.home() / "Downloads"

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        # Header
        header = QHBoxLayout()
        tbox = QVBoxLayout()
        tbox.setSpacing(3)
        self.title_lbl = QLabel(tr("storage_title", lang))
        self.title_lbl.setObjectName("PageTitle")
        self.sub_lbl = QLabel(tr("storage_sub", lang))
        self.sub_lbl.setObjectName("PageSubtitle")
        tbox.addWidget(self.title_lbl)
        tbox.addWidget(self.sub_lbl)
        header.addLayout(tbox)
        header.addStretch()

        self.primary_btn = QPushButton(" Analizar Temporales")
        self.primary_btn.setObjectName("PrimaryAction")
        self.primary_btn.setIcon(load_svg_icon("refresh", color="#0B0D10", size=14))
        self.primary_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.primary_btn.clicked.connect(self._on_primary_action)
        header.addWidget(self.primary_btn)
        root.addLayout(header)

        # Row 1: Clean 5 Mode Tabs (never clipped)
        tabs_bar = QHBoxLayout()
        tabs_bar.setSpacing(6)
        self.mode_buttons: dict[str, QPushButton] = {}
        modes = [
            ("junk", tr("mode_junk", lang)),
            ("duplicates", tr("mode_dups", lang)),
            ("tree", tr("mode_tree", lang)),
            ("orphans", tr("mode_orphans", lang)),
            ("quarantine", tr("mode_quarantine", lang)),
            ("onedrive", tr("mode_onedrive", lang)),
        ]
        for key, label in modes:
            btn = QPushButton(label)
            btn.setObjectName("GhostAction")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, m=key: self._switch_mode(m))
            self.mode_buttons[key] = btn
            tabs_bar.addWidget(btn)
        tabs_bar.addStretch()
        root.addLayout(tabs_bar)

        # Row 2: Contextual Actions + Icon-only Explorer button (distinct color, hover tooltip)
        actions_bar = QHBoxLayout()
        actions_bar.setSpacing(8)
        self.secondary_btn = QPushButton("Ejecutar Limpieza Segura")
        self.secondary_btn.setObjectName("GhostAction")
        self.secondary_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.secondary_btn.clicked.connect(self._on_secondary_action)
        actions_bar.addWidget(self.secondary_btn)

        self.tertiary_btn = QPushButton("Hardlink NTFS")
        self.tertiary_btn.setObjectName("GhostAction")
        self.tertiary_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tertiary_btn.clicked.connect(self._on_tertiary_action)
        self.tertiary_btn.setVisible(False)
        actions_bar.addWidget(self.tertiary_btn)

        actions_bar.addStretch()

        self.reveal_btn = QPushButton()
        self.reveal_btn.setObjectName("ExplorerBtn")
        self.reveal_btn.setIcon(load_svg_icon("folder", color=get_palette("dark")["explorer_icon"], size=16))
        self.reveal_btn.setToolTip("Ver en el Explorador de Windows (seleccione un archivo o carpeta)")
        self.reveal_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reveal_btn.clicked.connect(self._reveal_selected_item)
        actions_bar.addWidget(self.reveal_btn)
        root.addLayout(actions_bar)

        # Smart Auto-Cleaner bar (visible only in Duplicates mode)
        self.dup_autoclean_panel = GlassPanel()
        dal = QHBoxLayout(self.dup_autoclean_panel)
        dal.setContentsMargins(12, 8, 12, 8)
        dal.setSpacing(10)
        dal.addWidget(QLabel("Regla de autolimpieza:"))
        self.rule_combo = QComboBox()
        self.rule_combo.addItem("Conservar el mas antiguo", "keep_oldest")
        self.rule_combo.addItem("Conservar el mas reciente", "keep_newest")
        self.rule_combo.addItem("Conservar ruta mas corta", "keep_shortest_path")
        self.rule_combo.addItem("Conservar fuera de Descargas", "keep_outside_downloads")
        self.rule_combo.currentIndexChanged.connect(self._preview_selected_group)
        dal.addWidget(self.rule_combo)

        self.autoclean_btn = QPushButton("Autolimpiar Todos los Grupos -> Cuarentena")
        self.autoclean_btn.setObjectName("PrimaryAction")
        self.autoclean_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.autoclean_btn.clicked.connect(self._on_autoclean_all_duplicates)
        dal.addWidget(self.autoclean_btn)
        dal.addStretch()
        self.dup_autoclean_panel.setVisible(False)
        root.addWidget(self.dup_autoclean_panel)

        # Hybrid OneDrive Local + Cloud panel (visible only in onedrive mode)
        self.onedrive_panel = GlassPanel()
        odl = QVBoxLayout(self.onedrive_panel)
        odl.setContentsMargins(12, 8, 12, 8)
        odl.setSpacing(8)

        od_top = QHBoxLayout()
        od_top.setSpacing(8)
        self.od_status_lbl = QLabel("OneDrive local detectado | Nube sin vincular")
        self.od_status_lbl.setObjectName("MonoValue")
        od_top.addWidget(self.od_status_lbl, stretch=1)

        self.od_quota_tag = StatusTag("MODO LOCAL LISTO", "neutral")
        od_top.addWidget(self.od_quota_tag)

        self.od_cfg_btn = QPushButton("Configurar Client ID")
        self.od_cfg_btn.setObjectName("GhostAction")
        self.od_cfg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.od_cfg_btn.clicked.connect(self._configure_onedrive_oauth)
        od_top.addWidget(self.od_cfg_btn)

        self.od_connect_btn = QPushButton("Conectar Cuenta (OAuth)")
        self.od_connect_btn.setObjectName("GhostAction")
        self.od_connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.od_connect_btn.clicked.connect(self._connect_onedrive)
        od_top.addWidget(self.od_connect_btn)

        self.od_disconnect_btn = QPushButton("Desconectar")
        self.od_disconnect_btn.setObjectName("GhostAction")
        self.od_disconnect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.od_disconnect_btn.clicked.connect(self._disconnect_onedrive)
        self.od_disconnect_btn.setVisible(False)
        od_top.addWidget(self.od_disconnect_btn)
        odl.addLayout(od_top)

        od_opts = QHBoxLayout()
        od_opts.setSpacing(10)
        od_opts.addWidget(QLabel("Alcance:"))
        self.od_scope_combo = QComboBox()
        self.od_scope_combo.addItem("Local: Archivos en disco (liberar a Solo en la Nube)", "local_hydrated")
        self.od_scope_combo.addItem("Nube: Duplicados exactos (Microsoft Graph)", "cloud_duplicates")
        self.od_scope_combo.addItem("Nube: Archivos pesados (Microsoft Graph)", "cloud_heavy")
        self.od_scope_combo.currentIndexChanged.connect(self._on_onedrive_scope_changed)
        od_opts.addWidget(self.od_scope_combo, stretch=1)

        od_opts.addWidget(QLabel("Umbral:"))
        self.od_thresh_combo = QComboBox()
        self.od_thresh_combo.addItem(">= 25 MB y > 30 dias sin uso", (25.0, 30))
        self.od_thresh_combo.addItem(">= 10 MB y > 15 dias sin uso", (10.0, 15))
        self.od_thresh_combo.addItem(">= 100 MB (cualquier fecha)", (100.0, 0))
        self.od_thresh_combo.addItem(">= 5 MB (todo en disco)", (5.0, 0))
        od_opts.addWidget(self.od_thresh_combo)
        odl.addLayout(od_opts)

        self.onedrive_panel.setVisible(False)
        root.addWidget(self.onedrive_panel)

        # Summary strip
        summary = GlassPanel()
        sum_layout = QHBoxLayout(summary)
        sum_layout.setContentsMargins(14, 9, 14, 9)
        self.summary_lbl = QLabel("Seleccione un modo y ejecute el analisis bajo demanda.")
        self.summary_lbl.setObjectName("MonoValue")
        sum_layout.addWidget(self.summary_lbl)
        sum_layout.addStretch()
        sum_layout.addWidget(StatusTag("RSTRTMGR + ONEDRIVE GUARD", "ok"))
        root.addWidget(summary)

        # Main workspace area: Table + Optional Duplicate Preview Pane
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 4)
        configure_sortable_table(self.table)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self._reveal_selected_item())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(lambda pos: self._show_explorer_menu(self.table, pos))
        self.main_splitter.addWidget(self.table)

        # Duplicate Preview Panel (right side of splitter)
        self.preview_panel = GlassPanel()
        pl = QVBoxLayout(self.preview_panel)
        pl.setContentsMargins(14, 12, 14, 12)
        pl.setSpacing(8)
        phdr = QHBoxLayout()
        plbl = QLabel("VISTA PREVIA DEL DUPLICADO")
        plbl.setObjectName("SectionLabel")
        phdr.addWidget(plbl)
        phdr.addStretch()
        self.open_folder_btn = QPushButton("Abrir Carpeta")
        self.open_folder_btn.setObjectName("GhostAction")
        self.open_folder_btn.clicked.connect(self._open_preview_folder)
        phdr.addWidget(self.open_folder_btn)
        pl.addLayout(phdr)

        self.preview_meta = QLabel("Seleccione un grupo duplicado para previsualizar el archivo y copias.")
        self.preview_meta.setObjectName("MonoValue")
        self.preview_meta.setWordWrap(True)
        pl.addWidget(self.preview_meta)

        self.preview_image = QLabel()
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_image.setMinimumHeight(150)
        self.preview_image.setVisible(False)
        pl.addWidget(self.preview_image)

        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        pl.addWidget(self.preview_text, stretch=1)
        self.preview_panel.setVisible(False)
        self.main_splitter.addWidget(self.preview_panel)
        self.main_splitter.setSizes([640, 340])

        # Hierarchical Tree + Format Table splitter (for "tree" mode)
        self.tree_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.folder_tree = QTreeWidget()
        self.folder_tree.setHeaderLabels(["CARPETA", "PESO", "ARCHIVOS", "%"])
        self.folder_tree.setAlternatingRowColors(True)
        self.folder_tree.setSortingEnabled(True)
        self.folder_tree.itemDoubleClicked.connect(lambda _it, _col: self._reveal_selected_item())
        self.folder_tree.itemSelectionChanged.connect(self._update_explorer_tooltip)
        self.folder_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.folder_tree.customContextMenuRequested.connect(
            lambda pos: self._show_explorer_menu(self.folder_tree, pos)
        )
        thdr = self.folder_tree.header()
        thdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        thdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        thdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        thdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tree_splitter.addWidget(self.folder_tree)

        self.format_table = QTableWidget(0, 5)
        self.format_table.setHorizontalHeaderLabels(["EXTENSION", "TIPO", "ARCHIVOS", "PESO TOTAL", "MAS PESADO"])
        configure_sortable_table(self.format_table)
        self.format_table.cellDoubleClicked.connect(lambda _r, _c: self._reveal_selected_item())
        self.format_table.itemSelectionChanged.connect(self._update_explorer_tooltip)
        self.format_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.format_table.customContextMenuRequested.connect(
            lambda pos: self._show_explorer_menu(self.format_table, pos)
        )
        fhdr = self.format_table.horizontalHeader()
        fhdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        fhdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        fhdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        fhdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        fhdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.tree_splitter.addWidget(self.format_table)
        self.tree_splitter.setSizes([500, 480])
        self.tree_splitter.setVisible(False)

        root.addWidget(self.main_splitter, stretch=1)
        root.addWidget(self.tree_splitter, stretch=1)

        self._switch_mode("junk")

    def apply_language_and_theme(self, lang: str, icon_inverted: str, theme_mode: str = "dark") -> None:
        self.lang = lang
        self.title_lbl.setText(tr("storage_title", lang))
        self.sub_lbl.setText(tr("storage_sub", lang))
        self.primary_btn.setIcon(load_svg_icon("refresh", color=icon_inverted, size=14))
        self.reveal_btn.setIcon(
            load_svg_icon("folder", color=get_palette(theme_mode)["explorer_icon"], size=16)
        )
        for key, k_tr in (
            ("junk", "mode_junk"),
            ("duplicates", "mode_dups"),
            ("tree", "mode_tree"),
            ("orphans", "mode_orphans"),
            ("quarantine", "mode_quarantine"),
            ("onedrive", "mode_onedrive"),
        ):
            self.mode_buttons[key].setText(tr(k_tr, lang))

    def _on_selection_changed(self) -> None:
        self._update_explorer_tooltip()
        self._preview_selected_group()

    def _update_explorer_tooltip(self) -> None:
        target = self._get_selected_explorer_path()
        if target is not None:
            self.reveal_btn.setToolTip(f"Ver en el Explorador de Windows\n{target}")
        else:
            self.reveal_btn.setToolTip("Ver en el Explorador de Windows (seleccione un elemento)")

    def _switch_mode(self, mode: str) -> None:
        self.mode = mode
        for key, btn in self.mode_buttons.items():
            btn.setProperty("selected", key == mode)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        self.main_splitter.setVisible(mode != "tree")
        self.tree_splitter.setVisible(mode == "tree")
        self.preview_panel.setVisible(mode == "duplicates")
        self.dup_autoclean_panel.setVisible(mode == "duplicates")
        self.onedrive_panel.setVisible(mode == "onedrive")
        self.tertiary_btn.setVisible(mode in ("duplicates", "quarantine"))
        if mode == "quarantine":
            self.tertiary_btn.setText("Depurar / Vaciar Boveda")
        else:
            self.tertiary_btn.setText("Hardlink NTFS")

        if mode == "junk":
            self.primary_btn.setText(" Analizar Temporales")
            self.secondary_btn.setText("Limpiar Seleccionados")
            self._configure_columns(["CATEGORIA", "OBJETIVO", "ARCHIVOS", "RECUPERABLE"])
            self._render_junk()
        elif mode == "duplicates":
            self.primary_btn.setText(" Elegir Carpeta y Buscar")
            self.secondary_btn.setText("Cuarentena Seleccionado")
            self._configure_columns(["COPIAS", "TAMANO UNIT.", "DESPERDICIO", "ARCHIVO PRINCIPAL Y COPIAS"])
            self._render_duplicates()
        elif mode == "tree":
            self.primary_btn.setText(" Elegir Carpeta / Disco")
            self.secondary_btn.setText("Enviar Mas Pesado a Cuarentena")
            self._render_tree()
        elif mode == "orphans":
            self.primary_btn.setText(" Detectar Huerfanos")
            self.secondary_btn.setText("Enviar a Cuarentena")
            self._configure_columns(["TIPO", "ESTADO", "TAMANO", "RUTA DETECTADA"])
            self._render_orphans()
        elif mode == "onedrive":
            self._refresh_onedrive_status()
            self._on_onedrive_scope_changed()
            self._configure_columns(["ORIGEN", "MOTIVO", "TAMANO", "RUTA EN ONEDRIVE"])
            self._render_onedrive()
        else:
            self.primary_btn.setText(" Actualizar Boveda")
            self.secondary_btn.setText("Restaurar Seleccionado")
            self._configure_columns(["FECHA", "CATEGORIA", "TAMANO", "RUTA ORIGINAL"])
            self._render_quarantine()

    def _configure_columns(self, headers: list[str]) -> None:
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        hdr = self.table.horizontalHeader()
        for idx in range(len(headers) - 1):
            hdr.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Stretch)

    def _progress_summary(self, pct: int, stage: str) -> None:
        self.summary_lbl.setText(f"[{pct}%] {stage}")

    def _on_primary_action(self) -> None:
        if self.mode == "junk":
            self.summary_lbl.setText("Escaneando temporales en segundo plano...")
            self.run_async(
                scan_junk_targets,
                self._on_junk_scanned,
                "Escaneo de temporales",
                progress_ui_cb=self._progress_summary,
            )
        elif self.mode == "duplicates":
            chosen = QFileDialog.getExistingDirectory(
                self, "Seleccionar carpeta para duplicados BLAKE3", str(self.scan_root)
            )
            if not chosen:
                return
            self.scan_root = Path(chosen)
            self.summary_lbl.setText(f"Calculando firmas BLAKE3 en {self.scan_root} (en segundo plano)...")
            self.run_async(
                lambda progress_cb=None: find_duplicates([self.scan_root], progress_cb=progress_cb),
                self._on_dups_scanned,
                f"Duplicados BLAKE3 ({self.scan_root.name})",
                progress_ui_cb=self._progress_summary,
            )
        elif self.mode == "tree":
            chosen = QFileDialog.getExistingDirectory(
                self, "Seleccionar carpeta o unidad para vista jerarquica", str(self.scan_root)
            )
            if not chosen:
                return
            self.scan_root = Path(chosen)
            self.summary_lbl.setText(f"Analizando arbol y formatos en {self.scan_root} (en segundo plano)...")
            self.run_async(
                lambda progress_cb=None: analyze_storage_hierarchy(self.scan_root, progress_cb=progress_cb),
                self._on_tree_scanned,
                f"Arbol almacenamiento ({self.scan_root.name})",
                progress_ui_cb=self._progress_summary,
            )
        elif self.mode == "orphans":
            self.summary_lbl.setText("Analizando artefactos sueltos en segundo plano...")
            self.run_async(
                scan_orphan_artifacts,
                self._on_orphans_scanned,
                "Deteccion de huerfanos",
                progress_ui_cb=self._progress_summary,
            )
        elif self.mode == "onedrive":
            self._run_onedrive_scan()
        else:
            self._render_quarantine()

    def _on_junk_scanned(self, targets: list[JunkTarget]) -> None:
        self.primary_btn.setEnabled(True)
        self.junk_targets = targets
        self._render_junk()

    def _render_junk(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.junk_targets))
        total = 0
        for row, tgt in enumerate(self.junk_targets):
            total += tgt.reclaimable_bytes
            c0 = QTableWidgetItem(tgt.category)
            c0.setData(Qt.ItemDataRole.UserRole + 1, row)
            self.table.setItem(row, 0, c0)
            self.table.setItem(row, 1, QTableWidgetItem(f"{tgt.label} ({tgt.path})"))
            self.table.setItem(row, 2, NumericTableItem(str(tgt.file_count), tgt.file_count))
            self.table.setItem(row, 3, NumericTableItem(format_bytes(tgt.reclaimable_bytes), tgt.reclaimable_bytes))
        self.table.setSortingEnabled(True)
        self.summary_lbl.setText(
            f"Objetivos analizados: {len(self.junk_targets)} | Recuperable seguro: {format_bytes(total)}"
        )

    def _on_dups_scanned(self, groups: list[DuplicateGroup]) -> None:
        self.primary_btn.setEnabled(True)
        self.dup_groups = groups
        self._render_duplicates()

    def _render_duplicates(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.dup_groups))
        wasted = 0
        for row, grp in enumerate(self.dup_groups):
            wasted += grp.wasted_bytes
            joined = " | ".join(str(p) for p in grp.paths[:3])
            if len(grp.paths) > 3:
                joined += f" (+{len(grp.paths) - 3})"
            c0 = NumericTableItem(str(len(grp.paths)), len(grp.paths))
            c0.setData(Qt.ItemDataRole.UserRole + 1, row)
            self.table.setItem(row, 0, c0)
            self.table.setItem(row, 1, NumericTableItem(format_bytes(grp.size_bytes), grp.size_bytes))
            self.table.setItem(row, 2, NumericTableItem(format_bytes(grp.wasted_bytes), grp.wasted_bytes))
            self.table.setItem(row, 3, QTableWidgetItem(joined))
        self.table.setSortingEnabled(True)
        self.summary_lbl.setText(
            f"Grupos duplicados BLAKE3 en {self.scan_root.name}: {len(self.dup_groups)} | "
            f"Espacio recuperable: {format_bytes(wasted)}"
        )

    def _preview_selected_group(self) -> None:
        if self.mode != "duplicates":
            return
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        if not rows:
            return
        item0 = self.table.item(rows[0], 0)
        if item0 is None:
            return
        orig = item0.data(Qt.ItemDataRole.UserRole + 1)
        if orig is None or orig >= len(self.dup_groups):
            return

        grp = self.dup_groups[orig]
        rule = str(self.rule_combo.currentData() or "keep_oldest")
        plan = select_duplicates_by_rule([grp], rule=rule)
        keep_path = plan[0][1] if plan else grp.paths[0]
        remove_paths = plan[0][2] if plan else grp.paths[1:]

        mtime = datetime.fromtimestamp(keep_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M") if keep_path.exists() else "N/D"
        lines = [
            f"CONSERVAR: {keep_path} ({mtime})",
            "ELIMINAR -> CUARENTENA:",
            *[f"  - {rp}" for rp in remove_paths],
            f"BLAKE3: {grp.digest[:24]}... | Unitario: {format_bytes(grp.size_bytes)}",
        ]
        self.preview_meta.setText("\n".join(lines))

        ext = keep_path.suffix.lower()
        if ext in IMAGE_EXTS and keep_path.exists():
            pix = QPixmap(str(keep_path))
            if not pix.isNull():
                self.preview_image.setPixmap(
                    pix.scaled(300, 170, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                )
                self.preview_image.setVisible(True)
                self.preview_text.setVisible(False)
                return

        self.preview_image.setVisible(False)
        self.preview_text.setVisible(True)
        if ext in TEXT_EXTS and keep_path.exists():
            try:
                snippet = keep_path.read_text(encoding="utf-8", errors="replace")[:3500]
                self.preview_text.setPlainText(snippet)
            except OSError:
                self.preview_text.setPlainText("No se pudo leer vista previa de texto.")
        else:
            self.preview_text.setPlainText(
                f"Archivo binario ({ext or 'sin extension'})\n"
                f"Tamano: {format_bytes(grp.size_bytes)}\n"
                f"Copias totales: {len(grp.paths)}"
            )

    def _open_preview_folder(self) -> None:
        self._reveal_selected_item()

    def _get_selected_explorer_path(self) -> Path | None:
        if self.mode == "junk":
            idxs = self._selected_model_indices()
            if idxs and idxs[0] < len(self.junk_targets):
                return self.junk_targets[idxs[0]].path
        elif self.mode == "duplicates":
            rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
            if rows:
                it = self.table.item(rows[0], 0)
                orig = it.data(Qt.ItemDataRole.UserRole + 1) if it else None
                if isinstance(orig, int) and orig < len(self.dup_groups):
                    return self.dup_groups[orig].paths[0]
        elif self.mode == "orphans":
            idxs = self._selected_model_indices()
            if idxs and idxs[0] < len(self.orphans):
                return self.orphans[idxs[0]].path
        elif self.mode == "onedrive":
            idxs = self._selected_model_indices()
            if idxs and idxs[0] < len(self.onedrive_items):
                return self.onedrive_items[idxs[0]].local_path
        elif self.mode == "quarantine":
            rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
            if rows:
                it = self.table.item(rows[0], 0)
                item_id = it.data(Qt.ItemDataRole.UserRole + 1) if it else None
                for rec in self.vault.list_items():
                    if rec.item_id == item_id:
                        vp = Path(rec.vault_path)
                        return vp if vp.exists() else Path(rec.original_path).parent
        elif self.mode == "tree" and self.tree_report:
            rows = sorted({idx.row() for idx in self.format_table.selectedIndexes()})
            if rows:
                it = self.format_table.item(rows[0], 0)
                orig = it.data(Qt.ItemDataRole.UserRole + 1) if it else None
                if isinstance(orig, int) and orig < len(self.tree_report.formats):
                    return self.tree_report.formats[orig].heaviest_file
            cur = self.folder_tree.currentItem()
            if cur is not None:
                p_str = cur.data(0, Qt.ItemDataRole.UserRole + 1)
                if p_str:
                    return Path(str(p_str))
        return None

    def _reveal_selected_item(self) -> None:
        if self.mode == "onedrive":
            idxs = self._selected_model_indices()
            if idxs and idxs[0] < len(self.onedrive_items):
                cand = self.onedrive_items[idxs[0]]
                if cand.local_path and cand.local_path.exists():
                    reveal_in_explorer(cand.local_path)
                    self.notify_cb(f"Abriendo en Explorador: {cand.local_path}")
                    return
                if cand.web_url:
                    QDesktopServices.openUrl(QUrl(cand.web_url))
                    self.notify_cb(f"Abriendo en OneDrive web: {cand.name}")
                    return
        target = self._get_selected_explorer_path()
        if target is None:
            self.notify_cb("Seleccione un elemento del analisis para abrirlo en el Explorador.")
            return
        if reveal_in_explorer(target):
            self.notify_cb(f"Abriendo en Explorador: {target}")
        else:
            self.notify_cb("No se encontro la ruta seleccionada en disco.")

    def _show_explorer_menu(self, widget: QWidget, pos: QPoint) -> None:
        menu = QMenu(widget)
        act = QAction("Ver en el Explorador de Windows", menu)
        act.triggered.connect(self._reveal_selected_item)
        menu.addAction(act)
        menu.exec(widget.mapToGlobal(pos))

    def _on_tree_scanned(self, report: StorageHierarchyReport) -> None:
        self.primary_btn.setEnabled(True)
        self.tree_report = report
        self._render_tree()

    def _render_tree(self) -> None:
        self.folder_tree.clear()
        self.format_table.setRowCount(0)
        if not self.tree_report:
            self.summary_lbl.setText("Elija una carpeta o unidad para analizar la jerarquia y formatos.")
            return

        total = max(1, self.tree_report.root_node.size_bytes)

        def _add_node(node: FolderNode, parent_item: NumericTreeItem | None) -> None:
            pct = (node.size_bytes / total) * 100.0
            item = NumericTreeItem(
                [node.name, format_bytes(node.size_bytes), str(node.file_count), f"{pct:.1f}%"]
            )
            item.setData(0, Qt.ItemDataRole.UserRole + 1, str(node.path))
            item.setData(1, Qt.ItemDataRole.UserRole, float(node.size_bytes))
            item.setData(2, Qt.ItemDataRole.UserRole, float(node.file_count))
            item.setData(3, Qt.ItemDataRole.UserRole, float(pct))
            if parent_item is None:
                self.folder_tree.addTopLevelItem(item)
                item.setExpanded(True)
            else:
                parent_item.addChild(item)
            for child in node.children[:40]:
                _add_node(child, item)

        self.folder_tree.setSortingEnabled(False)
        _add_node(self.tree_report.root_node, None)
        self.folder_tree.setSortingEnabled(True)

        fmts = self.tree_report.formats
        self.format_table.setSortingEnabled(False)
        self.format_table.setRowCount(len(fmts))
        for r, fg in enumerate(fmts):
            c0 = QTableWidgetItem(fg.extension)
            c0.setData(Qt.ItemDataRole.UserRole + 1, r)
            self.format_table.setItem(r, 0, c0)
            self.format_table.setItem(r, 1, QTableWidgetItem(fg.category))
            self.format_table.setItem(r, 2, NumericTableItem(str(fg.file_count), fg.file_count))
            self.format_table.setItem(r, 3, NumericTableItem(format_bytes(fg.total_bytes), fg.total_bytes))
            heavy_txt = f"{fg.heaviest_file.name} ({format_bytes(fg.heaviest_bytes)})" if fg.heaviest_file else "N/D"
            self.format_table.setItem(r, 4, QTableWidgetItem(heavy_txt))
        self.format_table.setSortingEnabled(True)

        self.summary_lbl.setText(
            f"Arbol analizado: {self.tree_report.root_node.path} | "
            f"Total: {format_bytes(self.tree_report.root_node.size_bytes)} en "
            f"{self.tree_report.root_node.file_count} archivos"
        )

    def _on_orphans_scanned(self, items: list[OrphanCandidate]) -> None:
        self.primary_btn.setEnabled(True)
        self.orphans = items
        self._render_orphans()

    def _render_orphans(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.orphans))
        total = 0
        for row, item in enumerate(self.orphans):
            total += item.size_bytes
            state = item.confidence if not item.in_use_by else f"EN USO ({item.in_use_by})"
            c0 = QTableWidgetItem(item.kind)
            c0.setData(Qt.ItemDataRole.UserRole + 1, row)
            self.table.setItem(row, 0, c0)
            self.table.setItem(row, 1, QTableWidgetItem(state))
            self.table.setItem(row, 2, NumericTableItem(format_bytes(item.size_bytes), item.size_bytes))
            self.table.setItem(row, 3, QTableWidgetItem(str(item.path)))
        self.table.setSortingEnabled(True)
        self.summary_lbl.setText(
            f"Artefactos huerfanos detectados: {len(self.orphans)} | Tamano total: {format_bytes(total)}"
        )

    def _render_quarantine(self) -> None:
        items = self.vault.list_items()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(items))
        total = 0
        for row, rec in enumerate(items):
            total += rec.size_bytes
            c0 = QTableWidgetItem(rec.quarantined_at[:10])
            c0.setData(Qt.ItemDataRole.UserRole + 1, rec.item_id)
            self.table.setItem(row, 0, c0)
            self.table.setItem(row, 1, QTableWidgetItem(rec.category))
            self.table.setItem(row, 2, NumericTableItem(format_bytes(rec.size_bytes), rec.size_bytes))
            self.table.setItem(row, 3, QTableWidgetItem(rec.original_path))
        self.table.setSortingEnabled(True)
        self.summary_lbl.setText(
            f"Elementos respaldados en Cuarentena: {len(items)} | Espacio en boveda: {format_bytes(total)}"
        )

    def _selected_model_indices(self) -> list[int]:
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        indices: list[int] = []
        for r in rows:
            it = self.table.item(r, 0)
            if it is not None:
                val = it.data(Qt.ItemDataRole.UserRole + 1)
                if isinstance(val, int):
                    indices.append(val)
        if not indices and self.mode == "junk":
            return list(range(len(self.junk_targets)))
        return indices

    def _on_tertiary_action(self) -> None:
        if self.mode == "quarantine":
            self._on_purge_quarantine()
        else:
            self._on_hardlink_duplicates()

    def _on_purge_quarantine(self) -> None:
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        all_items = self.vault.list_items()
        if not all_items:
            self.summary_lbl.setText("La boveda de cuarentena ya esta vacia.")
            return
        if rows:
            item_ids = []
            for r in rows:
                it = self.table.item(r, 0)
                val = it.data(Qt.ItemDataRole.UserRole + 1) if it else None
                if isinstance(val, str):
                    item_ids.append(val)
            scope_label = f"{len(item_ids)} elemento(s) seleccionados"
        else:
            item_ids = [rec.item_id for rec in all_items]
            scope_label = f"TODOS los {len(item_ids)} elementos de la Boveda"

        reply = QMessageBox.question(
            self,
            "Depurar Boveda de Cuarentena",
            f"Desea eliminar permanentemente de la Boveda {scope_label}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.tertiary_btn.setEnabled(False)

        def _purge(progress_cb=None) -> dict[str, int]:
            return self.vault.purge_items(item_ids, use_recycle_bin=False, progress_cb=progress_cb)

        def _done(res: dict[str, int]) -> None:
            self.tertiary_btn.setEnabled(True)
            msg = f"Boveda depurada: {res['purged']} elementos eliminados ({format_bytes(res['freed_bytes'])})."
            self.policy.record_audit_event("usuario", "Depuracion cuarentena", msg, res["freed_bytes"] / (1024 * 1024))
            self.notify_cb(msg)
            self._render_quarantine()

        self.run_async(
            _purge,
            _done,
            "Depurar Boveda de Cuarentena",
            progress_ui_cb=self._progress_summary,
            on_error=lambda _e: self.tertiary_btn.setEnabled(True),
        )

    def _on_autoclean_all_duplicates(self) -> None:
        if not self.dup_groups:
            return
        rule = str(self.rule_combo.currentData() or "keep_oldest")
        plan = select_duplicates_by_rule(self.dup_groups, rule=rule)

        def _run(progress_cb=None) -> dict[str, int]:
            snapshot_items = [
                {"keep": str(keep), "remove": [str(rp) for rp in rem], "size_bytes": grp.size_bytes}
                for grp, keep, rem in plan
            ]
            self.backup_mgr.create_operation_snapshot("autolimpieza_duplicados", snapshot_items)
            res = quarantine_duplicates_plan(plan, self.vault, progress_cb=progress_cb)
            return {"freed": res["freed_bytes"], "moved": res["moved"]}

        def _done(res: dict[str, int]) -> None:
            msg = f"Autolimpiador ({rule}): {res['moved']} copias a Cuarentena ({format_bytes(res['freed'])})."
            self.policy.record_audit_event("usuario", "Autolimpieza duplicados", msg, res["freed"] / (1024 * 1024))
            self.notify_cb(msg)
            self.run_async(
                lambda progress_cb=None: find_duplicates([self.scan_root], progress_cb=progress_cb),
                self._on_dups_scanned,
                "Reescaneo BLAKE3",
                progress_ui_cb=self._progress_summary,
            )

        self.run_async(_run, _done, "Autolimpieza duplicados", progress_ui_cb=self._progress_summary)

    def _on_secondary_action(self) -> None:
        if self.mode == "junk":
            idxs = self._selected_model_indices()
            targets = [self.junk_targets[i] for i in idxs if i < len(self.junk_targets)]
            if not targets:
                return
            if any(t.requires_admin for t in targets) and not is_user_admin():
                reply = QMessageBox.question(
                    self,
                    "Limpieza Profunda con Permisos Admin (UAC)",
                    "Algunas rutas seleccionadas (Windows\\Temp, Minidump, WER) requieren permisos "
                    "de Administrador para limpiarse a profundidad.\n\n"
                    "Deseas relanzar WinOptiAI como Administrador ahora?\n"
                    "(Pulsa 'No' para limpiar ahora mismo todas las carpetas de tu usuario.)",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    args = "" if getattr(sys, "frozen", False) else "-m winoptiai.app"
                    if run_elevated_command(sys.executable, args):
                        win = self.window()
                        if win is not None and hasattr(win, "_quit_app"):
                            win._quit_app()
                        else:
                            QApplication.quit()
                    return
            self.secondary_btn.setEnabled(False)

            def _clean(progress_cb=None) -> dict[str, int]:
                self.backup_mgr.create_operation_snapshot(
                    "limpieza_temporales",
                    [{"path": str(t.path), "files": t.file_count, "bytes": t.reclaimable_bytes} for t in targets],
                )
                return clean_junk_targets(targets, self.vault, use_quarantine=True, progress_cb=progress_cb)

            def _done(res: dict[str, int]) -> None:
                self.secondary_btn.setEnabled(True)
                uac_note = (
                    f" ({res['perm']} requieren 'Elevar Admin UAC' para residuos de Windows)"
                    if res.get("perm", 0) > 0
                    else ""
                )
                msg = (
                    f"Limpieza segura: {res['removed']} archivos a Cuarentena, "
                    f"{format_bytes(res['freed'])} liberados ({res['skipped']} omitidos).{uac_note}"
                )
                self.policy.record_audit_event("usuario", "Limpieza temporales", msg, res["freed"] / (1024 * 1024))
                self.notify_cb(msg)
                self._on_primary_action()

            self.run_async(
                _clean,
                _done,
                "Limpieza temporales",
                progress_ui_cb=self._progress_summary,
                on_error=lambda _e: self.secondary_btn.setEnabled(True),
            )

        elif self.mode == "duplicates":
            idxs = self._selected_model_indices()
            groups = [self.dup_groups[i] for i in idxs if i < len(self.dup_groups)]
            if not groups:
                self.summary_lbl.setText("Seleccione uno o mas grupos duplicados en la tabla.")
                return
            rule = str(self.rule_combo.currentData() or "keep_oldest")
            plan = select_duplicates_by_rule(groups, rule=rule)

            def _dedup(progress_cb=None) -> int:
                return quarantine_duplicates_plan(plan, self.vault, progress_cb=progress_cb)["freed_bytes"]

            def _done(freed: int) -> None:
                msg = f"Duplicados movidos a Cuarentena: {format_bytes(freed)} recuperados."
                self.policy.record_audit_event("usuario", "Duplicados BLAKE3", msg, freed / (1024 * 1024))
                self.notify_cb(msg)
                self.run_async(
                    lambda progress_cb=None: find_duplicates([self.scan_root], progress_cb=progress_cb),
                    self._on_dups_scanned,
                    "Reescaneo BLAKE3",
                    progress_ui_cb=self._progress_summary,
                )

            self.run_async(_dedup, _done, "Cuarentena duplicados", progress_ui_cb=self._progress_summary)

        elif self.mode == "tree":
            if not self.tree_report:
                return
            rows = sorted({idx.row() for idx in self.format_table.selectedIndexes()})
            if not rows:
                self.summary_lbl.setText("Seleccione una extension en la tabla derecha para enviar su archivo mas pesado.")
                return
            item0 = self.format_table.item(rows[0], 0)
            orig = item0.data(Qt.ItemDataRole.UserRole + 1) if item0 else None
            if orig is None or orig >= len(self.tree_report.formats):
                return
            heavy = self.tree_report.formats[orig].heaviest_file
            if not heavy:
                return

            def _q_heavy(progress_cb=None):
                if progress_cb:
                    progress_cb(35, f"Moviendo {heavy.name} a Cuarentena...")
                return self.vault.quarantine_path(heavy, category="Arbol/Formato")

            def _done_heavy(res) -> None:
                ok, msg, rec = res
                if ok and rec:
                    self.policy.record_audit_event("usuario", "Cuarentena por formato", f"{heavy.name}: {msg}", rec.size_bytes / (1024 * 1024))
                    self.notify_cb(f"Movido a Cuarentena: {heavy.name}")
                    self.run_async(
                        lambda progress_cb=None: analyze_storage_hierarchy(self.scan_root, progress_cb=progress_cb),
                        self._on_tree_scanned,
                        "Actualizar arbol",
                        progress_ui_cb=self._progress_summary,
                    )
                else:
                    self.notify_cb(msg)

            self.run_async(_q_heavy, _done_heavy, f"Cuarentena ({heavy.name})", progress_ui_cb=self._progress_summary)

        elif self.mode == "orphans":
            idxs = self._selected_model_indices()
            items = [self.orphans[i] for i in idxs if i < len(self.orphans)]
            if not items:
                self.summary_lbl.setText("Seleccione uno o mas artefactos huerfanos en la tabla.")
                return

            def _done(res: dict[str, int]) -> None:
                msg = f"Huerfanos a Cuarentena: {res['moved']} movidos ({format_bytes(res['freed_bytes'])})."
                self.policy.record_audit_event("usuario", "Cuarentena huerfanos", msg, res["freed_bytes"] / (1024 * 1024))
                self.notify_cb(msg)
                self._on_primary_action()

            self.run_async(
                lambda progress_cb=None: quarantine_orphans(items, self.vault, progress_cb=progress_cb),
                _done,
                "Cuarentena huerfanos",
                progress_ui_cb=self._progress_summary,
            )

        elif self.mode == "onedrive":
            self._optimize_selected_onedrive()

        else:
            rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
            if not rows:
                self.summary_lbl.setText("Seleccione un elemento de la boveda para restaurar.")
                return
            item_ids: list[str] = []
            for r in rows:
                it = self.table.item(r, 0)
                val = it.data(Qt.ItemDataRole.UserRole + 1) if it else None
                if isinstance(val, str):
                    item_ids.append(val)

            def _restore_all(progress_cb=None) -> int:
                restored = 0
                total = max(1, len(item_ids))
                for idx, iid in enumerate(item_ids, start=1):
                    if progress_cb and (idx == 1 or idx % 20 == 0 or idx == total):
                        progress_cb(10 + int(idx * 85 / total), f"Restaurando ({idx}/{total})...")
                    ok, _ = self.vault.restore_item(iid)
                    if ok:
                        restored += 1
                return restored

            def _done_restore(restored: int) -> None:
                msg = f"Restaurados {restored} elementos desde la Boveda de Cuarentena."
                self.policy.record_audit_event("usuario", "Restauracion cuarentena", msg)
                self.notify_cb(msg)
                self._render_quarantine()

            self.run_async(_restore_all, _done_restore, "Restauracion cuarentena", progress_ui_cb=self._progress_summary)

    def _on_hardlink_duplicates(self) -> None:
        idxs = self._selected_model_indices()
        groups = [self.dup_groups[i] for i in idxs if i < len(self.dup_groups)]
        if not groups:
            self.summary_lbl.setText("Seleccione grupos duplicados para enlazar via Hardlink NTFS.")
            return

        def _link(progress_cb=None) -> int:
            freed = 0
            total = max(1, len(groups))
            for idx, grp in enumerate(groups, start=1):
                if progress_cb and (idx == 1 or idx % 10 == 0 or idx == total):
                    progress_cb(10 + int(idx * 85 / total), f"Enlazando hardlinks NTFS ({idx}/{total})...")
                freed += deduplicate_group_via_hardlink(grp, grp.paths[0])["freed_bytes"]
            return freed

        def _done(freed: int) -> None:
            msg = f"Hardlinks NTFS creados: {format_bytes(freed)} ahorrados conservando todas las rutas."
            self.policy.record_audit_event("usuario", "Hardlink NTFS", msg, freed / (1024 * 1024))
            self.notify_cb(msg)
            self.run_async(
                lambda progress_cb=None: find_duplicates([self.scan_root], progress_cb=progress_cb),
                self._on_dups_scanned,
                "Reescaneo BLAKE3",
                progress_ui_cb=self._progress_summary,
            )

        self.run_async(_link, _done, "Hardlinks NTFS", progress_ui_cb=self._progress_summary)

    # ------------------------------------------------------------------
    # OneDrive Local (Files On-Demand) + Cloud (Microsoft Graph OAuth)
    # ------------------------------------------------------------------
    def _on_onedrive_scope_changed(self) -> None:
        if self.mode != "onedrive":
            return
        scope = str(self.od_scope_combo.currentData() or "local_hydrated")
        if scope == "local_hydrated":
            self.primary_btn.setText(" Escanear OneDrive Local")
            self.secondary_btn.setText("Liberar Disco (Solo en la Nube)")
        elif scope == "cloud_duplicates":
            self.primary_btn.setText(" Buscar Duplicados Nube")
            self.secondary_btn.setText("Enviar a Papelera OneDrive")
        else:
            self.primary_btn.setText(" Analizar Pesados Nube")
            self.secondary_btn.setText("Enviar a Papelera OneDrive")

    def _refresh_onedrive_status(self) -> None:
        roots = discover_onedrive_roots()
        local_desc = ", ".join(r.label for r in roots) if roots else "Sin carpeta local"
        ok, _tok, store_data = ensure_valid_access_token(self.onedrive_store)
        if ok:
            email = store_data.get("owner_email") or store_data.get("owner_name") or "Cuenta conectada"
            self.od_status_lbl.setText(f"Local: {local_desc}  |  Nube: {email}")
            self.od_connect_btn.setText("Reconectar (OAuth)")
            self.od_disconnect_btn.setVisible(True)
            if self.onedrive_quota and self.onedrive_quota.total_bytes > 0:
                q = self.onedrive_quota
                self.od_quota_tag.set_tone(
                    f"NUBE {format_bytes(q.used_bytes)} / {format_bytes(q.total_bytes)}",
                    "active",
                )
            else:
                self.od_quota_tag.set_tone("NUBE CONECTADA (DPAPI)", "ok")
        else:
            has_cid = bool(store_data.get("client_id"))
            hint = "Client ID configurado" if has_cid else "Falta Client ID para Nube"
            self.od_status_lbl.setText(f"Local: {local_desc}  |  {hint}")
            self.od_connect_btn.setText("Conectar Cuenta (OAuth)")
            self.od_disconnect_btn.setVisible(False)
            self.od_quota_tag.set_tone("MODO LOCAL LISTO" if roots else "SIN CUENTA", "neutral")

    def _configure_onedrive_oauth(self) -> None:
        cur = self.onedrive_store.load()
        dlg = QDialog(self)
        dlg.setWindowTitle("Configurar OAuth OneDrive (Microsoft Graph + DPAPI)")
        dlg.setFixedSize(540, 320)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        guide = QLabel(
            "Para explorar duplicados y cuota directo en Microsoft Graph (sin descargar archivos):\n"
            "1. En portal.azure.com -> Microsoft Entra ID -> Registros de aplicaciones -> Nuevo registro.\n"
            "2. Plataforma: Aplicacion movil y de escritorio -> Redirect URI: http://localhost\n"
            "3. Permisos API (Microsoft Graph Delegado): User.Read y Files.ReadWrite.\n"
            "Nota: Tus tokens se cifran en disco con Windows DPAPI. El modo Local no requiere Client ID."
        )
        guide.setObjectName("PageSubtitle")
        guide.setWordWrap(True)
        lay.addWidget(guide)

        lay.addWidget(QLabel("Application (Client) ID:"))
        cid_edit = QLineEdit(str(cur.get("client_id") or ""))
        cid_edit.setPlaceholderText("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
        lay.addWidget(cid_edit)

        lay.addWidget(QLabel("Tipo de cuenta / Authority:"))
        auth_combo = QComboBox()
        auth_combo.addItem("Cualquiera (Personal MSA + Corporativa / common)", "common")
        auth_combo.addItem("Solo Empresarial / Fundacion (organizations)", "organizations")
        auth_combo.addItem("Solo Microsoft Personal (consumers)", "consumers")
        idx_a = auth_combo.findData(cur.get("authority", "common"))
        if idx_a >= 0:
            auth_combo.setCurrentIndex(idx_a)
        lay.addWidget(auth_combo)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_b = QPushButton("Cancelar")
        cancel_b.setObjectName("GhostAction")
        cancel_b.clicked.connect(dlg.reject)
        btns.addWidget(cancel_b)

        save_b = QPushButton("Guardar Cifrado (DPAPI)")
        save_b.setObjectName("PrimaryAction")
        save_b.clicked.connect(dlg.accept)
        btns.addWidget(save_b)
        lay.addLayout(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        cur["client_id"] = cid_edit.text().strip()
        cur["authority"] = str(auth_combo.currentData() or "common")
        self.onedrive_store.save(cur)
        self._refresh_onedrive_status()
        self.notify_cb("Configuracion OAuth de OneDrive guardada de forma cifrada (DPAPI).")

    def _connect_onedrive(self) -> None:
        cur = self.onedrive_store.load()
        cid = str(cur.get("client_id") or "").strip()
        if not cid:
            self._configure_onedrive_oauth()
            cur = self.onedrive_store.load()
            cid = str(cur.get("client_id") or "").strip()
            if not cid:
                return
        authority = str(cur.get("authority") or "common")
        self.od_connect_btn.setEnabled(False)
        self.summary_lbl.setText("Abriendo navegador para autorizar OneDrive...")

        def _login(progress_cb=None) -> tuple[bool, str, OneDriveQuota | None]:
            ok, msg = start_oauth_pkce_login(
                cid,
                authority=authority,
                store=self.onedrive_store,
                progress_cb=progress_cb,
            )
            quota = None
            if ok:
                tok_ok, token, sdata = ensure_valid_access_token(self.onedrive_store)
                if tok_ok:
                    try:
                        quota = fetch_cloud_drive_quota(
                            token,
                            owner_hint=(sdata.get("owner_name", ""), sdata.get("owner_email", "")),
                        )
                    except OSError:
                        quota = None
            return ok, msg, quota

        def _done(res: tuple[bool, str, OneDriveQuota | None]) -> None:
            self.od_connect_btn.setEnabled(True)
            ok, msg, quota = res
            if quota is not None:
                self.onedrive_quota = quota
            self._refresh_onedrive_status()
            self.notify_cb(msg)
            self.summary_lbl.setText(msg)

        self.run_async(
            _login,
            _done,
            "Autenticacion OneDrive",
            progress_ui_cb=self._progress_summary,
            on_error=lambda _e: self.od_connect_btn.setEnabled(True),
        )

    def _disconnect_onedrive(self) -> None:
        self.onedrive_store.clear_tokens()
        self.onedrive_quota = None
        self._refresh_onedrive_status()
        self.notify_cb("Sesion de OneDrive Nube desconectada de este equipo.")

    def _run_onedrive_scan(self) -> None:
        scope = str(self.od_scope_combo.currentData() or "local_hydrated")
        thresh = self.od_thresh_combo.currentData()
        min_mb, min_days = thresh if isinstance(thresh, tuple) else (25.0, 30)

        if scope == "local_hydrated":
            self.summary_lbl.setText("Escaneando OneDrive local (Files On-Demand)...")
            self.run_async(
                lambda progress_cb=None: (
                    scan_local_onedrive_candidates(
                        min_size_mb=float(min_mb),
                        min_inactive_days=int(min_days),
                        progress_cb=progress_cb,
                    ),
                    None,
                ),
                self._on_onedrive_scanned,
                "Escaneo OneDrive Local",
                progress_ui_cb=self._progress_summary,
            )
            return

        ok, token, sdata = ensure_valid_access_token(self.onedrive_store)
        if not ok:
            self.summary_lbl.setText("Conecta tu cuenta OneDrive (OAuth) primero para escanear directo en la nube.")
            self._connect_onedrive()
            return

        kind = "duplicates" if scope == "cloud_duplicates" else "heavy"
        self.summary_lbl.setText("Consultando indice de archivos en Microsoft Graph...")

        def _cloud_job(progress_cb=None) -> tuple[list[OneDriveCandidate], OneDriveQuota | None]:
            quota = None
            try:
                quota = fetch_cloud_drive_quota(
                    token,
                    owner_hint=(sdata.get("owner_name", ""), sdata.get("owner_email", "")),
                )
            except OSError:
                pass
            items = scan_cloud_onedrive(
                token,
                scan_kind=kind,
                min_heavy_mb=float(min_mb),
                progress_cb=progress_cb,
            )
            return items, quota

        self.run_async(
            _cloud_job,
            self._on_onedrive_scanned,
            "Escaneo OneDrive Nube",
            progress_ui_cb=self._progress_summary,
        )

    def _on_onedrive_scanned(self, payload: tuple[list[OneDriveCandidate], OneDriveQuota | None]) -> None:
        items, quota = payload
        self.onedrive_items = items
        if quota is not None:
            self.onedrive_quota = quota
        self._refresh_onedrive_status()
        self._render_onedrive()

    def _render_onedrive(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.onedrive_items))
        total = 0
        for row, item in enumerate(self.onedrive_items):
            total += item.size_bytes
            origin_txt = "LOCAL SSD" if item.scope == "LOCAL_HYDRATED" else (
                "NUBE DUP" if item.scope == "CLOUD_DUPLICATE" else "NUBE PESADO"
            )
            c0 = QTableWidgetItem(origin_txt)
            c0.setData(Qt.ItemDataRole.UserRole + 1, row)
            self.table.setItem(row, 0, c0)
            self.table.setItem(row, 1, QTableWidgetItem(f"{item.reason} ({item.last_modified})"))
            self.table.setItem(row, 2, NumericTableItem(format_bytes(item.size_bytes), item.size_bytes))
            self.table.setItem(row, 3, QTableWidgetItem(item.location))
        self.table.setSortingEnabled(True)
        self.summary_lbl.setText(
            f"OneDrive: {len(self.onedrive_items)} candidatos | Espacio recuperable: {format_bytes(total)}"
        )

    def _optimize_selected_onedrive(self) -> None:
        idxs = self._selected_model_indices()
        if not idxs:
            self.summary_lbl.setText("Seleccione uno o mas archivos de OneDrive en la tabla.")
            return
        selected = [self.onedrive_items[i] for i in idxs if i < len(self.onedrive_items)]
        if not selected:
            return

        local_items = [c for c in selected if c.scope == "LOCAL_HYDRATED"]
        cloud_items = [c for c in selected if c.scope in ("CLOUD_DUPLICATE", "CLOUD_HEAVY")]

        if cloud_items:
            total_b = sum(c.size_bytes for c in cloud_items)
            reply = QMessageBox.question(
                self,
                "Mover archivos en la nube a Papelera de OneDrive",
                f"Se enviaran {len(cloud_items)} archivo(s) ({format_bytes(total_b)}) a la Papelera de OneDrive "
                "(recuperable en la web durante 30-93 dias, sin borrado permanente).\n\nDeseas continuar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.secondary_btn.setEnabled(False)

        if local_items and not cloud_items:
            def _dehydrate(progress_cb=None) -> dict[str, int]:
                return dehydrate_local_onedrive_files(
                    local_items,
                    backup_mgr=self.backup_mgr,
                    progress_cb=progress_cb,
                )

            def _done_local(res: dict[str, int]) -> None:
                self.secondary_btn.setEnabled(True)
                msg = (
                    f"OneDrive Local liberado: {res['dehydrated']} archivos pasados a 'Solo en la nube' "
                    f"({format_bytes(res['freed_bytes'])} en SSD, {res['skipped']} omitidos)."
                )
                self.policy.record_audit_event("usuario", "OneDrive Solo Nube", msg, res["freed_bytes"] / (1024 * 1024))
                self.notify_cb(msg)
                self._run_onedrive_scan()

            self.run_async(
                _dehydrate,
                _done_local,
                "Deshidratar OneDrive Local",
                progress_ui_cb=self._progress_summary,
                on_error=lambda _e: self.secondary_btn.setEnabled(True),
            )
            return

        ok, token, _ = ensure_valid_access_token(self.onedrive_store)
        if not ok:
            self.secondary_btn.setEnabled(True)
            self.notify_cb("Sesion OAuth expirada; vuelve a conectar OneDrive.")
            return

        def _trash_cloud(progress_cb=None) -> dict[str, int]:
            return trash_cloud_onedrive_items(
                token,
                cloud_items,
                backup_mgr=self.backup_mgr,
                progress_cb=progress_cb,
            )

        def _done_cloud(res: dict[str, int]) -> None:
            self.secondary_btn.setEnabled(True)
            msg = (
                f"OneDrive Nube: {res['trashed']} archivos movidos a Papelera "
                f"({format_bytes(res['freed_bytes'])}, {res['skipped']} omitidos)."
            )
            self.policy.record_audit_event("usuario", "OneDrive Nube Papelera", msg, res["freed_bytes"] / (1024 * 1024))
            self.notify_cb(msg)
            self._run_onedrive_scan()

        self.run_async(
            _trash_cloud,
            _done_cloud,
            "Papelera OneDrive Nube",
            progress_ui_cb=self._progress_summary,
            on_error=lambda _e: self.secondary_btn.setEnabled(True),
        )
