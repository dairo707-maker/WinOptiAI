"""Storage Manager view: Junk caches, BLAKE3 duplicates, Orphan artifacts, Quarantine."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.safety_guard import QuarantineVault
from ...core.sre_policy import SREPolicyEngine
from ...storage.duplicate_finder import (
    DuplicateGroup,
    deduplicate_group_to_quarantine,
    deduplicate_group_via_hardlink,
    find_duplicates,
)
from ...storage.junk_scanner import JunkTarget, clean_junk_target, scan_junk_targets
from ...storage.orphan_hunter import OrphanCandidate, quarantine_orphans, scan_orphan_artifacts
from ..svg_icons import load_svg_icon
from ..theme import format_bytes
from ..widgets import GlassPanel, StatusTag


class StorageView(QWidget):
    """Surgical storage management view with 1 primary contextual action."""

    def __init__(
        self,
        vault: QuarantineVault,
        policy: SREPolicyEngine,
        run_async: Callable,
        notify_cb: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.vault = vault
        self.policy = policy
        self.run_async = run_async
        self.notify_cb = notify_cb

        self.mode = "junk"  # "junk" | "duplicates" | "orphans" | "quarantine"
        self.junk_targets: list[JunkTarget] = []
        self.dup_groups: list[DuplicateGroup] = []
        self.orphans: list[OrphanCandidate] = []
        self.dup_root: Path = Path.home() / "Downloads"

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # Header
        header = QHBoxLayout()
        tbox = QVBoxLayout()
        tbox.setSpacing(3)
        title = QLabel("Gestor de Almacenamiento")
        title.setObjectName("PageTitle")
        sub = QLabel(
            "Proteccion activa OneDrive Cloud-Only y verificacion de bloqueos con Windows Restart Manager."
        )
        sub.setObjectName("PageSubtitle")
        tbox.addWidget(title)
        tbox.addWidget(sub)
        header.addLayout(tbox)
        header.addStretch()

        self.primary_btn = QPushButton(" Analizar Temporales")
        self.primary_btn.setObjectName("PrimaryAction")
        self.primary_btn.setIcon(load_svg_icon("refresh", color="#0B0D10", size=14))
        self.primary_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.primary_btn.clicked.connect(self._on_primary_action)
        header.addWidget(self.primary_btn)
        root.addLayout(header)

        # Mode switch bar + contextual secondary control
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.mode_buttons: dict[str, QPushButton] = {}
        modes = [
            ("junk", "Temporales y Caches"),
            ("duplicates", "Duplicados BLAKE3"),
            ("orphans", "Archivos Huerfanos"),
            ("quarantine", "Boveda Cuarentena"),
        ]
        for key, label in modes:
            btn = QPushButton(label)
            btn.setObjectName("GhostAction")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, m=key: self._switch_mode(m))
            self.mode_buttons[key] = btn
            bar.addWidget(btn)

        bar.addStretch()
        self.secondary_btn = QPushButton("Ejecutar Limpieza Segura")
        self.secondary_btn.setObjectName("GhostAction")
        self.secondary_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.secondary_btn.clicked.connect(self._on_secondary_action)
        bar.addWidget(self.secondary_btn)

        self.tertiary_btn = QPushButton("Enlazar Hardlink NTFS")
        self.tertiary_btn.setObjectName("GhostAction")
        self.tertiary_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tertiary_btn.clicked.connect(self._on_hardlink_duplicates)
        self.tertiary_btn.setVisible(False)
        bar.addWidget(self.tertiary_btn)
        root.addLayout(bar)

        # Summary strip
        summary = GlassPanel()
        sum_layout = QHBoxLayout(summary)
        sum_layout.setContentsMargins(14, 10, 14, 10)
        self.summary_lbl = QLabel("Seleccione un modo y ejecute el analisis bajo demanda.")
        self.summary_lbl.setObjectName("MonoValue")
        sum_layout.addWidget(self.summary_lbl)
        sum_layout.addStretch()
        self.guard_tag = StatusTag("RSTRTMGR + ONEDRIVE GUARD", "ok")
        sum_layout.addWidget(self.guard_tag)
        root.addWidget(summary)

        # Clean data table
        self.table = QTableWidget(0, 4)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, stretch=1)

        self._switch_mode("junk")

    def _switch_mode(self, mode: str) -> None:
        self.mode = mode
        for key, btn in self.mode_buttons.items():
            btn.setProperty("selected", key == mode)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        self.tertiary_btn.setVisible(mode == "duplicates")

        if mode == "junk":
            self.primary_btn.setText(" Analizar Temporales")
            self.secondary_btn.setText("Limpiar Seleccionados")
            self.secondary_btn.setVisible(True)
            self._configure_columns(["CATEGORIA", "OBJETIVO", "ARCHIVOS", "RECUPERABLE"])
            self._render_junk()
        elif mode == "duplicates":
            self.primary_btn.setText(" Elegir Carpeta y Buscar")
            self.secondary_btn.setText("Mover Copias a Cuarentena")
            self.secondary_btn.setVisible(True)
            self._configure_columns(["COPIAS", "TAMANO UNIT.", "DESPERDICIO", "ARCHIVO PRINCIPAL Y COPIAS"])
            self._render_duplicates()
        elif mode == "orphans":
            self.primary_btn.setText(" Detectar Huerfanos")
            self.secondary_btn.setText("Enviar a Cuarentena")
            self.secondary_btn.setVisible(True)
            self._configure_columns(["TIPO", "ESTADO", "TAMANO", "RUTA DETECTADA"])
            self._render_orphans()
        else:
            self.primary_btn.setText(" Actualizar Boveda")
            self.secondary_btn.setText("Restaurar Seleccionado")
            self.secondary_btn.setVisible(True)
            self._configure_columns(["FECHA", "CATEGORIA", "TAMANO", "RUTA ORIGINAL"])
            self._render_quarantine()

    def _configure_columns(self, headers: list[str]) -> None:
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        hdr = self.table.horizontalHeader()
        for idx in range(len(headers) - 1):
            hdr.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Stretch)

    def _on_primary_action(self) -> None:
        if self.mode == "junk":
            self.primary_btn.setEnabled(False)
            self.summary_lbl.setText("Escaneando temporales y caches seguros...")
            self.run_async(scan_junk_targets, self._on_junk_scanned)
        elif self.mode == "duplicates":
            chosen = QFileDialog.getExistingDirectory(
                self,
                "Seleccionar carpeta para buscar duplicados BLAKE3",
                str(self.dup_root),
            )
            if not chosen:
                return
            self.dup_root = Path(chosen)
            self.primary_btn.setEnabled(False)
            self.summary_lbl.setText(f"Calculando firmas BLAKE3 en {self.dup_root}...")
            self.run_async(lambda: find_duplicates([self.dup_root]), self._on_dups_scanned)
        elif self.mode == "orphans":
            self.primary_btn.setEnabled(False)
            self.summary_lbl.setText("Analizando artefactos sueltos y bloqueos del sistema...")
            self.run_async(scan_orphan_artifacts, self._on_orphans_scanned)
        else:
            self._render_quarantine()

    def _on_junk_scanned(self, targets: list[JunkTarget]) -> None:
        self.primary_btn.setEnabled(True)
        self.junk_targets = targets
        self._render_junk()

    def _render_junk(self) -> None:
        self.table.setRowCount(len(self.junk_targets))
        total = 0
        for row, tgt in enumerate(self.junk_targets):
            total += tgt.reclaimable_bytes
            self.table.setItem(row, 0, QTableWidgetItem(tgt.category))
            self.table.setItem(row, 1, QTableWidgetItem(f"{tgt.label} ({tgt.path})"))
            self.table.setItem(row, 2, QTableWidgetItem(str(tgt.file_count)))
            self.table.setItem(row, 3, QTableWidgetItem(format_bytes(tgt.reclaimable_bytes)))
        self.summary_lbl.setText(
            f"Objetivos analizados: {len(self.junk_targets)} | Recuperable seguro: {format_bytes(total)}"
        )

    def _on_dups_scanned(self, groups: list[DuplicateGroup]) -> None:
        self.primary_btn.setEnabled(True)
        self.dup_groups = groups
        self._render_duplicates()

    def _render_duplicates(self) -> None:
        self.table.setRowCount(len(self.dup_groups))
        wasted = 0
        for row, grp in enumerate(self.dup_groups):
            wasted += grp.wasted_bytes
            joined = " | ".join(str(p) for p in grp.paths[:3])
            if len(grp.paths) > 3:
                joined += f" (+{len(grp.paths) - 3})"
            self.table.setItem(row, 0, QTableWidgetItem(str(len(grp.paths))))
            self.table.setItem(row, 1, QTableWidgetItem(format_bytes(grp.size_bytes)))
            self.table.setItem(row, 2, QTableWidgetItem(format_bytes(grp.wasted_bytes)))
            self.table.setItem(row, 3, QTableWidgetItem(joined))
        self.summary_lbl.setText(
            f"Grupos duplicados BLAKE3 en {self.dup_root.name}: {len(self.dup_groups)} | "
            f"Espacio recuperable: {format_bytes(wasted)}"
        )

    def _on_orphans_scanned(self, items: list[OrphanCandidate]) -> None:
        self.primary_btn.setEnabled(True)
        self.orphans = items
        self._render_orphans()

    def _render_orphans(self) -> None:
        self.table.setRowCount(len(self.orphans))
        total = 0
        for row, item in enumerate(self.orphans):
            total += item.size_bytes
            state = item.confidence if not item.in_use_by else f"EN USO ({item.in_use_by})"
            self.table.setItem(row, 0, QTableWidgetItem(item.kind))
            self.table.setItem(row, 1, QTableWidgetItem(state))
            self.table.setItem(row, 2, QTableWidgetItem(format_bytes(item.size_bytes)))
            self.table.setItem(row, 3, QTableWidgetItem(str(item.path)))
        self.summary_lbl.setText(
            f"Artefactos huerfanos detectados: {len(self.orphans)} | Tamano total: {format_bytes(total)}"
        )

    def _render_quarantine(self) -> None:
        items = self.vault.list_items()
        self.table.setRowCount(len(items))
        total = 0
        for row, rec in enumerate(items):
            total += rec.size_bytes
            self.table.setItem(row, 0, QTableWidgetItem(rec.quarantined_at[:10]))
            self.table.setItem(row, 1, QTableWidgetItem(rec.category))
            self.table.setItem(row, 2, QTableWidgetItem(format_bytes(rec.size_bytes)))
            self.table.setItem(row, 3, QTableWidgetItem(rec.original_path))
        self.summary_lbl.setText(
            f"Elementos respaldados en Cuarentena: {len(items)} | Espacio en boveda: {format_bytes(total)}"
        )

    def _selected_rows(self) -> list[int]:
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        if rows:
            return rows
        return list(range(self.table.rowCount())) if self.mode == "junk" else []

    def _on_secondary_action(self) -> None:
        if self.mode == "junk":
            rows = self._selected_rows()
            targets = [self.junk_targets[r] for r in rows if r < len(self.junk_targets)]
            if not targets:
                return
            self.secondary_btn.setEnabled(False)

            def _clean() -> dict[str, int]:
                freed = 0
                removed = 0
                skipped = 0
                for t in targets:
                    res = clean_junk_target(t, self.vault, use_quarantine=False)
                    freed += res["freed_bytes"]
                    removed += res["removed"]
                    skipped += res["skipped_locked"]
                return {"freed": freed, "removed": removed, "skipped": skipped}

            def _done(res: dict[str, int]) -> None:
                self.secondary_btn.setEnabled(True)
                msg = (
                    f"Limpieza segura: {res['removed']} archivos depurados, "
                    f"{format_bytes(res['freed'])} liberados ({res['skipped']} en uso omitidos)."
                )
                self.policy.record_audit_event("usuario", "Limpieza temporales", msg, res["freed"] / (1024 * 1024))
                self.notify_cb(msg)
                self._on_primary_action()

            self.run_async(_clean, _done)

        elif self.mode == "duplicates":
            rows = self._selected_rows()
            groups = [self.dup_groups[r] for r in rows if r < len(self.dup_groups)]
            if not groups:
                self.summary_lbl.setText("Seleccione uno o mas grupos duplicados en la tabla.")
                return

            def _dedup() -> int:
                freed = 0
                for grp in groups:
                    res = deduplicate_group_to_quarantine(grp, grp.paths[0], self.vault)
                    freed += res["freed_bytes"]
                return freed

            def _done(freed: int) -> None:
                msg = f"Duplicados movidos a Cuarentena: {format_bytes(freed)} recuperados."
                self.policy.record_audit_event("usuario", "Duplicados BLAKE3", msg, freed / (1024 * 1024))
                self.notify_cb(msg)
                self.run_async(lambda: find_duplicates([self.dup_root]), self._on_dups_scanned)

            self.run_async(_dedup, _done)

        elif self.mode == "orphans":
            rows = self._selected_rows()
            items = [self.orphans[r] for r in rows if r < len(self.orphans)]
            if not items:
                self.summary_lbl.setText("Seleccione uno o mas artefactos huerfanos en la tabla.")
                return

            def _move() -> dict[str, int]:
                return quarantine_orphans(items, self.vault)

            def _done(res: dict[str, int]) -> None:
                msg = f"Huerfanos a Cuarentena: {res['moved']} movidos ({format_bytes(res['freed_bytes'])})."
                self.policy.record_audit_event(
                    "usuario", "Cuarentena huerfanos", msg, res["freed_bytes"] / (1024 * 1024)
                )
                self.notify_cb(msg)
                self._on_primary_action()

            self.run_async(_move, _done)

        else:
            items = self.vault.list_items()
            rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
            if not rows:
                self.summary_lbl.setText("Seleccione un elemento de la boveda para restaurar.")
                return
            restored = 0
            for r in rows:
                if r < len(items):
                    ok, _ = self.vault.restore_item(items[r].item_id)
                    if ok:
                        restored += 1
            msg = f"Restaurados {restored} elementos desde la Boveda de Cuarentena."
            self.policy.record_audit_event("usuario", "Restauracion cuarentena", msg)
            self.notify_cb(msg)
            self._render_quarantine()

    def _on_hardlink_duplicates(self) -> None:
        rows = self._selected_rows()
        groups = [self.dup_groups[r] for r in rows if r < len(self.dup_groups)]
        if not groups:
            self.summary_lbl.setText("Seleccione grupos duplicados para enlazar via Hardlink NTFS.")
            return

        def _link() -> int:
            freed = 0
            for grp in groups:
                res = deduplicate_group_via_hardlink(grp, grp.paths[0])
                freed += res["freed_bytes"]
            return freed

        def _done(freed: int) -> None:
            msg = f"Hardlinks NTFS creados: {format_bytes(freed)} ahorrados conservando todas las rutas."
            self.policy.record_audit_event("usuario", "Hardlink NTFS", msg, freed / (1024 * 1024))
            self.notify_cb(msg)
            self.run_async(lambda: find_duplicates([self.dup_root]), self._on_dups_scanned)

        self.run_async(_link, _done)
