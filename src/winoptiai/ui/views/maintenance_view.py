"""v0.6.9: pestana Mantenimiento: Registro (entradas rotas), unidades y SSD, espacio del sistema."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.i18n import tr
from ...core.sre_policy import SREPolicyEngine
from ...core.win32_bridge import reveal_in_explorer, run_elevated_command
from ..context_menu import copy_text, install_action_menu
from ..theme import format_bytes
from ..widgets import (
    FlowLayout,
    GlassPanel,
    NumericTableItem,
    SectionBenefitStrip,
    StatusTag,
    apply_table_tooltips,
    configure_interactive_columns,
    configure_sortable_table,
    set_button_role,
)


class MaintenanceView(QWidget):
    def __init__(
        self,
        policy: SREPolicyEngine,
        run_async: Callable,
        notify_cb: Callable[[str], None],
        lang: str = "es",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.policy = policy
        self.run_async = run_async
        self.notify_cb = notify_cb
        self.lang = lang
        self.broken: list = []
        self.volumes: list = []
        self.space_items: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        tbox = QVBoxLayout()
        tbox.setSpacing(2)
        self.title_lbl = QLabel(tr("nav_maintenance", lang))
        self.title_lbl.setObjectName("PageTitle")
        self.sub_lbl = QLabel("Registro sin entradas rotas, unidades optimizadas segun su tipo, salud del SSD y espacio del sistema.")
        self.sub_lbl.setObjectName("PageSubtitle")
        self.sub_lbl.setWordWrap(True)
        tbox.addWidget(self.title_lbl)
        tbox.addWidget(self.sub_lbl)
        header.addLayout(tbox, 1)
        self.scan_all_btn = QPushButton("Revisar todo")
        set_button_role(self.scan_all_btn, "PrimaryAction")
        self.scan_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_all_btn.clicked.connect(self.refresh_all)
        header.addWidget(self.scan_all_btn)
        root.addLayout(header)

        root.addWidget(SectionBenefitStrip("maintenance"))

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_registry_tab(), "Registro")
        self.tabs.addTab(self._build_drives_tab(), "Unidades y SSD")
        self.tabs.addTab(self._build_space_tab(), "Espacio del sistema")
        root.addWidget(self.tabs, stretch=1)

    # ------------------------------------------------------------------ construccion
    def _panel(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 10, 0, 0)
        lay.setSpacing(8)
        return page, lay

    def _build_registry_tab(self) -> QWidget:
        page, lay = self._panel()
        info = GlassPanel()
        il = QHBoxLayout(info)
        il.setContentsMargins(12, 8, 12, 8)
        hint = QLabel(
            "Solo entradas que apuntan a programas o archivos que ya no existen en tus discos internos "
            "(restos de apps desinstaladas). Antes de borrar se guarda una copia .reg restaurable."
        )
        hint.setObjectName("BodyText")
        hint.setWordWrap(True)
        il.addWidget(hint, 1)
        self.reg_tag = StatusTag("SIN REVISAR", "neutral")
        il.addWidget(self.reg_tag)
        lay.addWidget(info)

        row = FlowLayout(spacing=8)
        self.reg_scan_btn = QPushButton("Buscar entradas rotas")
        set_button_role(self.reg_scan_btn, "GhostAction")
        self.reg_scan_btn.clicked.connect(self.refresh_registry)
        row.addWidget(self.reg_scan_btn)
        self.reg_clean_btn = QPushButton("Limpiar seleccionadas")
        set_button_role(self.reg_clean_btn, "MoveAction")
        self.reg_clean_btn.clicked.connect(self._clean_selected_registry)
        row.addWidget(self.reg_clean_btn)
        self.reg_restore_btn = QPushButton("Restaurar ultimo respaldo")
        set_button_role(self.reg_restore_btn, "RestoreAction")
        self.reg_restore_btn.clicked.connect(self._restore_last_backup)
        row.addWidget(self.reg_restore_btn)
        self.reg_open_btn = QPushButton("Ver respaldos")
        set_button_role(self.reg_open_btn, "GhostAction")
        self.reg_open_btn.clicked.connect(self._open_backups)
        row.addWidget(self.reg_open_btn)
        holder = QWidget()
        holder.setLayout(row)
        lay.addWidget(holder)

        self.reg_table = QTableWidget(0, 4)
        self.reg_table.setHorizontalHeaderLabels(["TIPO", "NOMBRE", "APUNTA A (YA NO EXISTE)", "ALCANCE"])
        configure_sortable_table(self.reg_table)
        self.reg_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        configure_interactive_columns(self.reg_table, [210, 230, 420, 150], policy=self.policy, storage_key="maint_reg_table")
        lay.addWidget(self.reg_table, stretch=1)
        install_action_menu(self.reg_table, extras=self._reg_menu_extras)
        return page

    def _build_drives_tab(self) -> QWidget:
        page, lay = self._panel()
        self.ssd_lbl = QLabel("Pulsa 'Revisar todo' para ver la salud de tus discos.")
        self.ssd_lbl.setObjectName("BodyText")
        self.ssd_lbl.setWordWrap(True)
        lay.addWidget(self.ssd_lbl)
        why = QLabel(
            "SSD: se optimiza con TRIM (avisa al disco que bloques estan libres); desfragmentarlo lo desgasta "
            "sin beneficio. HDD: se analiza y desfragmenta. Windows lo hace con sus herramientas oficiales."
        )
        why.setObjectName("Caption")
        why.setWordWrap(True)
        lay.addWidget(why)
        row = FlowLayout(spacing=8)
        self.opt_btn = QPushButton("Optimizar unidad seleccionada (UAC)")
        set_button_role(self.opt_btn, "PrimaryAction")
        self.opt_btn.clicked.connect(self._optimize_selected)
        row.addWidget(self.opt_btn)
        holder = QWidget()
        holder.setLayout(row)
        lay.addWidget(holder)
        self.vol_table = QTableWidget(0, 6)
        self.vol_table.setHorizontalHeaderLabels(["UNIDAD", "TIPO", "ESTADO", "LIBRE", "TAMANO", "OPTIMIZACION"])
        configure_sortable_table(self.vol_table)
        configure_interactive_columns(self.vol_table, [150, 120, 110, 110, 110, 220], policy=self.policy, storage_key="maint_vol_table")
        lay.addWidget(self.vol_table, stretch=1)
        install_action_menu(self.vol_table, extras=lambda: [("Optimizar (UAC)", self._optimize_selected, bool(self._selected_volume()))])
        return page

    def _build_space_tab(self) -> QWidget:
        page, lay = self._panel()
        hint = QLabel("Lo que ocupa Windows en C: y se puede ajustar. Cada accion explica su efecto y usa UAC.")
        hint.setObjectName("BodyText")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        row = FlowLayout(spacing=8)
        self.space_btn = QPushButton("Ejecutar accion seleccionada (UAC)")
        set_button_role(self.space_btn, "MoveAction")
        self.space_btn.clicked.connect(self._run_selected_space_action)
        row.addWidget(self.space_btn)
        holder = QWidget()
        holder.setLayout(row)
        lay.addWidget(holder)
        self.space_table = QTableWidget(0, 4)
        self.space_table.setHorizontalHeaderLabels(["ELEMENTO", "OCUPA", "QUE HACE", "ACCION"])
        configure_sortable_table(self.space_table)
        self.space_table.setWordWrap(True)
        configure_interactive_columns(self.space_table, [260, 90, 520, 210], policy=self.policy, storage_key="maint_space_table")
        lay.addWidget(self.space_table, stretch=1)
        install_action_menu(self.space_table, extras=self._space_menu_extras)
        return page

    # ------------------------------------------------------------------ revisar
    def refresh_all(self) -> None:
        self.refresh_registry()
        self.refresh_drives()
        self.refresh_space()

    def refresh_registry(self) -> None:
        from ...maintenance.registry_cleaner import scan_broken_registry_entries

        self.reg_scan_btn.setEnabled(False)
        self.reg_tag.set_tone("REVISANDO", "active")
        self.run_async(scan_broken_registry_entries, self._render_registry, "Revisar Registro",
                       notify_on_complete=False, on_error=lambda _e: self.reg_scan_btn.setEnabled(True))

    def _render_registry(self, entries: list) -> None:
        self.reg_scan_btn.setEnabled(True)
        self.broken = list(entries)
        self.reg_tag.set_tone(f"{len(entries)} ROTAS" if entries else "TODO EN ORDEN", "warn" if entries else "ok")
        self.reg_table.setSortingEnabled(False)
        self.reg_table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            c0 = QTableWidgetItem(e.category_label)
            c0.setData(Qt.ItemDataRole.UserRole + 1, r)
            self.reg_table.setItem(r, 0, c0)
            self.reg_table.setItem(r, 1, QTableWidgetItem(e.name))
            tgt = QTableWidgetItem(e.target)
            tgt.setToolTip(f"{e.target}\n\nClave: {e.full_key}" + (f"\nValor: {e.value}" if e.value else ""))
            self.reg_table.setItem(r, 2, tgt)
            self.reg_table.setItem(r, 3, QTableWidgetItem("Equipo (UAC)" if e.needs_admin else "Tu usuario"))
        apply_table_tooltips(self.reg_table)
        self.reg_table.setSortingEnabled(True)

    def refresh_drives(self) -> None:
        from ...maintenance.drives import list_volumes

        self.run_async(list_volumes, self._render_drives, "Revisar unidades", notify_on_complete=False)

    def _render_drives(self, vols: list) -> None:
        from ...maintenance.drives import admin_hint, ssd_health_summary

        self.volumes = list(vols)
        self.vol_table.setSortingEnabled(False)
        self.vol_table.setRowCount(len(vols))
        for r, v in enumerate(vols):
            c0 = QTableWidgetItem(f"{v.letter}:  {v.label}".strip())
            c0.setData(Qt.ItemDataRole.UserRole + 1, r)
            self.vol_table.setItem(r, 0, c0)
            self.vol_table.setItem(r, 1, QTableWidgetItem(v.kind_label))
            self.vol_table.setItem(r, 2, QTableWidgetItem(v.health_label))
            self.vol_table.setItem(r, 3, NumericTableItem(format_bytes(v.free), v.free))
            self.vol_table.setItem(r, 4, NumericTableItem(format_bytes(v.size), v.size))
            self.vol_table.setItem(r, 5, QTableWidgetItem(v.recommended_action))
        apply_table_tooltips(self.vol_table)
        self.vol_table.setSortingEnabled(True)
        lines = [ssd_health_summary(v) for v in vols] or ["No se encontraron unidades internas."]
        hint = admin_hint()
        self.ssd_lbl.setText("\n".join(lines))
        if hint and not any(v.wear_pct >= 0 for v in vols):
            self.ssd_lbl.setToolTip(hint)
        if self.volumes:
            self.vol_table.selectRow(0)

    def refresh_space(self) -> None:
        from ...maintenance.drives import system_space_items

        self.run_async(system_space_items, self._render_space, "Revisar espacio del sistema", notify_on_complete=False)

    def _render_space(self, items: list) -> None:
        self.space_items = list(items)
        self.space_table.setSortingEnabled(False)
        self.space_table.setRowCount(len(items))
        for r, it in enumerate(items):
            c0 = QTableWidgetItem(it.title)
            c0.setData(Qt.ItemDataRole.UserRole + 1, r)
            self.space_table.setItem(r, 0, c0)
            self.space_table.setItem(r, 1, NumericTableItem(format_bytes(it.size_bytes) if it.size_bytes else "--", it.size_bytes))
            expl = QTableWidgetItem(it.explanation)
            expl.setToolTip(it.explanation)
            self.space_table.setItem(r, 2, expl)
            self.space_table.setItem(r, 3, QTableWidgetItem(it.action_label or "Solo informativo"))
        apply_table_tooltips(self.space_table)
        self.space_table.setSortingEnabled(True)
        self.space_table.resizeRowsToContents()

    # ------------------------------------------------------------------ seleccion
    def _selected_rows(self, table: QTableWidget, source: list) -> list:
        rows = sorted({i.row() for i in table.selectedIndexes()})
        out = []
        for r in rows:
            it = table.item(r, 0)
            idx = it.data(Qt.ItemDataRole.UserRole + 1) if it else None
            if isinstance(idx, int) and 0 <= idx < len(source):
                out.append(source[idx])
        return out

    def _selected_volume(self):
        sel = self._selected_rows(self.vol_table, self.volumes)
        return sel[0] if sel else None

    def _reg_menu_extras(self):
        sel = self._selected_rows(self.reg_table, self.broken)
        if not sel:
            return []
        return [
            (f"Limpiar {len(sel)} entrada(s)", self._clean_selected_registry, True),
            None,
            ("Copiar clave del Registro", lambda: copy_text("\n".join(e.full_key for e in sel)), True),
        ]

    def _space_menu_extras(self):
        sel = self._selected_rows(self.space_table, self.space_items)
        if not sel or not sel[0].action_label:
            return []
        return [(sel[0].action_label, self._run_selected_space_action, True)]

    # ------------------------------------------------------------------ acciones
    def _clean_selected_registry(self) -> None:
        from ...maintenance.registry_cleaner import clean_entries, elevated_delete_command

        sel = self._selected_rows(self.reg_table, self.broken) or list(self.broken)
        if not sel:
            self.notify_cb("No hay entradas rotas para limpiar. Usa 'Buscar entradas rotas'.")
            return
        n_admin = sum(1 for e in sel if e.needs_admin)
        ans = QMessageBox.question(
            self,
            "Limpiar Registro",
            f"Se borraran {len(sel)} entrada(s) rotas ({n_admin} piden permiso de administrador).\n\n"
            "Antes se guarda una copia .reg de cada una para poder restaurarla. Continuar?",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.reg_clean_btn.setEnabled(False)

        def _work(subtask_cb=None):
            return clean_entries(sel, subtask_cb=subtask_cb)

        def _done(res) -> None:
            self.reg_clean_btn.setEnabled(True)
            done, admin, folder = res
            msg = f"Registro: {len(done)} entrada(s) borradas. Copia guardada en {folder.name}."
            self.policy.record_audit_event("usuario", "Limpiar Registro", msg)
            if admin:
                ok = run_elevated_command("cmd.exe", elevated_delete_command(admin))
                msg += (
                    f" {len(admin)} del equipo se borraron con permiso de administrador."
                    if ok else f" {len(admin)} del equipo quedaron pendientes (UAC cancelado)."
                )
                self.policy.record_audit_event("usuario", "Limpiar Registro (UAC)", f"{len(admin)} entradas HKLM; ok={ok}")
            self.notify_cb(msg)
            QTimer.singleShot(2500, self.refresh_registry)

        def _err(_e: str) -> None:
            self.reg_clean_btn.setEnabled(True)

        self.run_async(_work, _done, "Limpiar Registro", notify_on_complete=False, on_error=_err)

    def _restore_last_backup(self) -> None:
        from ...maintenance.registry_cleaner import list_backups, restore_backup

        backups = list_backups()
        if not backups:
            self.notify_cb("Todavia no hay respaldos del Registro.")
            return
        last = backups[0]
        ans = QMessageBox.question(self, "Restaurar Registro", f"Restaurar las entradas del respaldo {last.name}?")
        if ans != QMessageBox.StandardButton.Yes:
            return
        ok, fail, hklm = restore_backup(last)
        msg = f"Restauradas {ok} entrada(s) de tu usuario" + (f", {fail} con error" if fail else "") + "."
        if hklm:
            args = "/c " + " & ".join(f'reg import "{f}"' for f in hklm)
            done = run_elevated_command("cmd.exe", args)
            msg += f" {len(hklm)} del equipo " + ("restauradas con UAC." if done else "pendientes (UAC cancelado).")
        self.policy.record_audit_event("usuario", "Restaurar Registro", msg)
        self.notify_cb(msg)
        QTimer.singleShot(2500, self.refresh_registry)

    def _open_backups(self) -> None:
        from ...maintenance.registry_cleaner import backups_root

        reveal_in_explorer(str(backups_root()))

    def _optimize_selected(self) -> None:
        from ...maintenance.drives import optimize_volume_elevated

        vol = self._selected_volume()
        if vol is None:
            self.notify_cb("Selecciona una unidad de la tabla.")
            return
        ok, msg = optimize_volume_elevated(vol)
        self.policy.record_audit_event("usuario", "Optimizar unidad", msg)
        self.notify_cb(msg)

    def _run_selected_space_action(self) -> None:
        from ...maintenance.drives import run_space_action

        sel = self._selected_rows(self.space_table, self.space_items)
        if not sel or not sel[0].action_label:
            self.notify_cb("Selecciona un elemento con accion disponible.")
            return
        item = sel[0]
        ans = QMessageBox.question(self, item.action_label, f"{item.title}\n\n{item.explanation}\n\nContinuar?")
        if ans != QMessageBox.StandardButton.Yes:
            return
        ok, msg = run_space_action(item.key)
        self.policy.record_audit_event("usuario", f"Espacio del sistema: {item.key}", msg)
        self.notify_cb(msg)
        if ok:
            QTimer.singleShot(6000, self.refresh_space)

    def apply_language_and_theme(self, lang: str, _icon_inverted: str = "") -> None:
        self.lang = lang
        self.title_lbl.setText(tr("nav_maintenance", lang))
