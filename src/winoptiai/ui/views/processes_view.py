"""Processes & Agentic AI view: active app tasks, live OS processes (sortable), EcoQoS, MCP zombies."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...ai_optimizer.process_manager import (
    ProcessEntry,
    ZombieWorker,
    apply_manual_process_ecoqos,
    apply_manual_process_io_priority,
    detect_orphan_ai_workers,
    list_top_processes,
    terminate_zombie_worker,
)
from ...core.i18n import tr
from ...core.sre_policy import SREPolicyEngine
from ...core.usage_telemetry import format_last_used_time
from ..svg_icons import load_svg_icon
from ..context_menu import copy_row_extra, copy_text, install_action_menu
from ...core.help_catalog import TOOLTIPS
from ..widgets import (
    FlowLayout,
    GlassPanel,
    NumericTableItem,
    SectionBenefitStrip,
    StatusTag,
    apply_table_tooltips,
    configure_interactive_columns,
    configure_sortable_table,
)


class ProcessesView(QWidget):
    """Sortable active process monitor, live app task monitor, and SRE toggles."""

    def __init__(
        self,
        policy: SREPolicyEngine,
        run_async: Callable,
        boost_cb: Callable[[], None],
        notify_cb: Callable[[str], None],
        lang: str = "es",
        parent: QWidget | None = None,
        *,
        focus_cb: Callable[[], None] | None = None,
        standby_cb: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.policy = policy
        self.run_async = run_async
        self.boost_cb = boost_cb
        self.notify_cb = notify_cb
        self.focus_cb = focus_cb
        self.standby_cb = standby_cb
        self.lang = lang
        self.zombies: list[ZombieWorker] = []
        self._entries: list[ProcessEntry] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        # Header + 1 primary action
        header = QHBoxLayout()
        tbox = QVBoxLayout()
        tbox.setSpacing(3)
        self.title_lbl = QLabel(tr("proc_title", lang))
        self.title_lbl.setObjectName("PageTitle")
        self.sub_lbl = QLabel(tr("proc_sub", lang))
        self.sub_lbl.setObjectName("PageSubtitle")
        self.sub_lbl.setWordWrap(True)  # v0.5.6: nunca recortado en ventanas angostas
        tbox.addWidget(self.title_lbl)
        tbox.addWidget(self.sub_lbl)
        header.addLayout(tbox, 1)  # v0.5.6: el titulo usa el espacio libre

        self.boost_btn = QPushButton(" Compactar RAM y EcoQoS")
        self.boost_btn.setObjectName("PrimaryAction")
        self.boost_btn.setIcon(load_svg_icon("process", color="#0B0D10", size=14))
        self.boost_btn.setToolTip(TOOLTIPS["proc_boost"])
        self.boost_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boost_btn.clicked.connect(self.boost_cb)
        header.addWidget(self.boost_btn)
        root.addLayout(header)

        self.benefit_strip = SectionBenefitStrip("processes")
        root.addWidget(self.benefit_strip)

        # Active WinOptiAI Tasks + SRE Toggles + Manual Perf Controls (FlowLayout: never clips)
        sre_panel = GlassPanel()
        sre_layout = FlowLayout(sre_panel, spacing=10)
        sre_layout.setContentsMargins(14, 10, 14, 10)

        self.auto_ram_chk = QCheckBox(
            f"Alivio SRE si RAM libre < {self.policy.config.ram_threshold_gb:.1f} GB (5m)"
        )
        self.auto_ram_chk.setChecked(self.policy.config.auto_ram_relief_enabled)
        self.auto_ram_chk.setToolTip(TOOLTIPS["proc_auto_ram"])
        self.auto_ram_chk.toggled.connect(self._save_policy_toggles)
        sre_layout.addWidget(self.auto_ram_chk)

        self.ecoqos_chk = QCheckBox("EcoQoS en segundo plano")
        self.ecoqos_chk.setChecked(self.policy.config.auto_ecoqos_background_browsers)
        self.ecoqos_chk.setToolTip(TOOLTIPS["proc_ecoqos"])
        self.ecoqos_chk.toggled.connect(self._save_policy_toggles)
        sre_layout.addWidget(self.ecoqos_chk)

        self.active_task_tag = StatusTag("0 TAREAS APP", "neutral")
        sre_layout.addWidget(self.active_task_tag)

        self.focus_btn = QPushButton("Modo Enfoque (IA)")
        self.focus_btn.setObjectName("GhostAction")
        self.focus_btn.setCheckable(True)
        self.focus_btn.setToolTip(TOOLTIPS["proc_focus"])
        self.focus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.focus_btn.clicked.connect(lambda: self.focus_cb() if self.focus_cb else None)
        sre_layout.addWidget(self.focus_btn)

        self.standby_btn = QPushButton("Purgar Standby (UAC)")
        self.standby_btn.setObjectName("GhostAction")
        self.standby_btn.setToolTip(TOOLTIPS["proc_standby"])
        self.standby_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.standby_btn.clicked.connect(lambda: self.standby_cb() if self.standby_cb else self._purge_standby_fallback())
        sre_layout.addWidget(self.standby_btn)

        self.manual_eco_btn = QPushButton("EcoQoS Sel.")
        self.manual_eco_btn.setObjectName("GhostAction")
        self.manual_eco_btn.setToolTip(TOOLTIPS["proc_ecoqos_manual"])
        self.manual_eco_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.manual_eco_btn.clicked.connect(self._toggle_selected_ecoqos)
        sre_layout.addWidget(self.manual_eco_btn)

        self.manual_io_btn = QPushButton("E/S Baja Sel.")
        self.manual_io_btn.setObjectName("GhostAction")
        self.manual_io_btn.setToolTip(TOOLTIPS["proc_iolow_manual"])
        self.manual_io_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.manual_io_btn.clicked.connect(self._toggle_selected_io_low)
        sre_layout.addWidget(self.manual_io_btn)

        self.refresh_btn = QPushButton("Actualizar")
        self.refresh_btn.setObjectName("GhostAction")
        self.refresh_btn.setToolTip(TOOLTIPS["proc_refresh"])
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.refresh_all)
        sre_layout.addWidget(self.refresh_btn)
        root.addWidget(sre_panel)

        # Active top processes table (sortable by PID, Name, Class, CPU%, E/S MB/s, RAM, EcoQoS/IO, Last Used)
        self.proc_table = QTableWidget(0, 8)
        self.proc_table.setHorizontalHeaderLabels(
            ["PID", "PROCESO", "CLASIFICACION", "CPU (%)", "E/S MB/s", "RAM (MB)", "ECOQOS / E/S", "ULTIMO USO"]
        )
        configure_sortable_table(self.proc_table)
        configure_interactive_columns(
            self.proc_table,
            [78, 220, 155, 86, 102, 100, 132, 128],
            policy=self.policy,
            storage_key="proc_table",
        )
        root.addWidget(self.proc_table, stretch=3)

        # Orphan AI / MCP workers panel
        z_panel = GlassPanel()
        z_layout = QVBoxLayout(z_panel)
        z_layout.setContentsMargins(14, 12, 14, 12)
        z_layout.setSpacing(8)

        z_hdr = QHBoxLayout()
        z_lbl = QLabel("CAZADOR DE WORKERS MCP / NODE / PYTHON HUERFANOS")
        z_lbl.setObjectName("SectionLabel")
        z_hdr.addWidget(z_lbl)
        z_hdr.addStretch()
        self.zombie_tag = StatusTag("0 DETECTADOS", "neutral")
        z_hdr.addWidget(self.zombie_tag)
        self.kill_zombie_btn = QPushButton("Cerrar Zombi Seleccionado")
        self.kill_zombie_btn.setObjectName("RiskAction")  # v0.5.6: cierra procesos
        self.kill_zombie_btn.setToolTip(TOOLTIPS["proc_kill_zombie"])
        self.kill_zombie_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.kill_zombie_btn.clicked.connect(self._kill_selected_zombie)
        z_hdr.addWidget(self.kill_zombie_btn)
        z_layout.addLayout(z_hdr)

        self.zombie_table = QTableWidget(0, 4)
        self.zombie_table.setHorizontalHeaderLabels(["PID", "PROCESO", "RAM (MB)", "COMANDO"])
        configure_sortable_table(self.zombie_table)
        configure_interactive_columns(
            self.zombie_table,
            [78, 180, 105, 500],
            policy=self.policy,
            storage_key="zombie_table",
        )
        z_layout.addWidget(self.zombie_table)
        # v0.6.5: clic derecho = mismas acciones del apartado
        install_action_menu(self.proc_table, extras=lambda: self._proc_menu_extras(self.proc_table))
        install_action_menu(
            self.zombie_table,
            row_buttons=[self.kill_zombie_btn],
            extras=lambda: self._proc_menu_extras(self.zombie_table),
        )
        root.addWidget(z_panel, stretch=2)

    def apply_language_and_theme(self, lang: str, icon_inverted: str) -> None:
        self.lang = lang
        self.title_lbl.setText(tr("proc_title", lang))
        self.sub_lbl.setText(tr("proc_sub", lang))
        self.boost_btn.setIcon(load_svg_icon("process", color=icon_inverted, size=14))

    def set_active_tasks(self, task_names: list[str]) -> None:
        if task_names:
            self.active_task_tag.set_tone(f"{len(task_names)} ACTIVAS", "active")  # v0.5.6: sin texto cortado
            self.active_task_tag.setToolTip("\n".join(task_names))
        else:
            self.active_task_tag.set_tone("0 TAREAS APP", "neutral")

    def _save_policy_toggles(self) -> None:
        self.policy.config.auto_ram_relief_enabled = self.auto_ram_chk.isChecked()
        self.policy.config.auto_ecoqos_background_browsers = self.ecoqos_chk.isChecked()
        self.policy.save_config()

    def refresh_all(self) -> None:
        self.run_async(lambda: list_top_processes(45), self._render_processes, "Escaneo procesos")
        self.run_async(detect_orphan_ai_workers, self._render_zombies, "Cazador MCP")

    def set_focus_mode_active(self, active: bool) -> None:
        self.focus_btn.blockSignals(True)
        self.focus_btn.setChecked(bool(active))
        self.focus_btn.setText("Enfoque: ON (Revertir)" if active else "Modo Enfoque (IA)")
        self.focus_btn.setProperty("selected", bool(active))
        self.focus_btn.style().unpolish(self.focus_btn)
        self.focus_btn.style().polish(self.focus_btn)
        self.focus_btn.blockSignals(False)

    def _purge_standby_fallback(self) -> None:
        from ...core.win32_bridge import purge_standby_memory_list

        self.standby_btn.setEnabled(False)
        self.run_async(
            lambda: purge_standby_memory_list(allow_uac=True),
            lambda res: (self.standby_btn.setEnabled(True), self.notify_cb(res[1])),
            "Purgar Standby RAM",
            notify_on_complete=False,
            on_error=lambda _e: self.standby_btn.setEnabled(True),
        )

    def _selected_entry(self) -> ProcessEntry | None:
        r = self.proc_table.currentRow()
        if r < 0:
            return None
        it = self.proc_table.item(r, 0)
        if it is None:
            return None
        try:
            pid = int(it.text())
        except ValueError:
            return None
        return next((e for e in self._entries if e.pid == pid), None)

    def _toggle_selected_ecoqos(self) -> None:
        ent = self._selected_entry()
        if ent is None:
            self.notify_cb("Selecciona un proceso en la tabla primero.")
            return
        ok, msg = apply_manual_process_ecoqos(ent.pid, ent.name, not ent.ecoqos_active)
        self.notify_cb(msg)
        if ok:
            self.refresh_all()

    def _toggle_selected_io_low(self) -> None:
        ent = self._selected_entry()
        if ent is None:
            self.notify_cb("Selecciona un proceso en la tabla primero.")
            return
        ok, msg = apply_manual_process_io_priority(ent.pid, ent.name, not ent.io_low)
        self.notify_cb(msg)
        if ok:
            self.refresh_all()

    def _render_processes(self, entries: list[ProcessEntry]) -> None:
        self._entries = list(entries)
        self.proc_table.setSortingEnabled(False)
        self.proc_table.setRowCount(len(entries))
        for r, item in enumerate(entries):
            ts = float(getattr(item, "started_ts", 0.0))
            self.proc_table.setItem(r, 0, NumericTableItem(str(item.pid), item.pid))
            self.proc_table.setItem(r, 1, QTableWidgetItem(item.name))
            self.proc_table.setItem(r, 2, QTableWidgetItem(item.role))
            self.proc_table.setItem(r, 3, NumericTableItem(f"{item.cpu_pct:.1f}", item.cpu_pct))
            io_rate = float(getattr(item, "io_mb_s", 0.0))
            self.proc_table.setItem(r, 4, NumericTableItem(f"{io_rate:.2f}", io_rate))
            self.proc_table.setItem(r, 5, NumericTableItem(f"{item.ram_mb:.1f}", item.ram_mb))
            if not item.ecoqos_eligible:
                st_txt = "PROTEGIDO"
            elif item.ecoqos_active and item.io_low:
                st_txt = "ECO + I/O BAJA"
            elif item.ecoqos_active:
                st_txt = "ECO ACTIVO"
            elif item.io_low:
                st_txt = "E/S BAJA"
            else:
                st_txt = "ELEGIBLE"
            self.proc_table.setItem(r, 6, QTableWidgetItem(st_txt))
            self.proc_table.setItem(r, 7, NumericTableItem(format_last_used_time(ts), ts))
        apply_table_tooltips(self.proc_table)
        self.proc_table.setSortingEnabled(True)

    def _render_zombies(self, items: list[ZombieWorker]) -> None:
        self.zombies = items
        self.zombie_table.setSortingEnabled(False)
        self.zombie_table.setRowCount(len(items))
        self.zombie_tag.set_tone(f"{len(items)} DETECTADOS", "warn" if items else "ok")
        for r, z in enumerate(items):
            pid_item = NumericTableItem(str(z.pid), z.pid)
            pid_item.setData(Qt.ItemDataRole.UserRole + 1, r)
            self.zombie_table.setItem(r, 0, pid_item)
            self.zombie_table.setItem(r, 1, QTableWidgetItem(z.name))
            self.zombie_table.setItem(r, 2, NumericTableItem(f"{z.ram_mb:.1f}", z.ram_mb))
            self.zombie_table.setItem(r, 3, QTableWidgetItem(z.cmdline))
        apply_table_tooltips(self.zombie_table)
        self.zombie_table.setSortingEnabled(True)

    def _proc_menu_extras(self, table):
        from ...core.win32_bridge import reveal_in_explorer

        r = table.currentRow()
        pid_item = table.item(r, 0) if r >= 0 else None
        name_item = table.item(r, 1) if r >= 0 else None
        if pid_item is None:
            return []
        exe = ""
        try:
            import psutil

            exe = psutil.Process(int(pid_item.text())).exe()
        except Exception:  # noqa: BLE001 - proceso cerrado o sin permiso
            exe = ""
        extras_list: list = []
        if table is self.proc_table:
            ent = self._selected_entry()
            if ent is not None and ent.ecoqos_eligible:
                extras_list.append((
                    "Quitar EcoQoS" if ent.ecoqos_active else "Aplicar EcoQoS",
                    self._toggle_selected_ecoqos,
                    True,
                ))
                extras_list.append((
                    "Prioridad E/S Normal" if ent.io_low else "Prioridad E/S Baja",
                    self._toggle_selected_io_low,
                    True,
                ))
        extras_list.extend([
            ("Abrir ubicacion del archivo", lambda: reveal_in_explorer(exe), bool(exe)),
            ("Copiar nombre", lambda: copy_text(name_item.text() if name_item else ""), name_item is not None),
            ("Copiar PID", lambda: copy_text(pid_item.text()), True),
            copy_row_extra(table),
        ])
        return extras_list

    def _kill_selected_zombie(self) -> None:
        rows = sorted({idx.row() for idx in self.zombie_table.selectedIndexes()})
        if not rows:
            self.notify_cb("Seleccione un worker huerfano en la tabla inferior.")
            return
        item0 = self.zombie_table.item(rows[0], 0)
        if item0 is None:
            return
        orig_idx = item0.data(Qt.ItemDataRole.UserRole + 1)
        if orig_idx is None or orig_idx >= len(self.zombies):
            return
        target = self.zombies[orig_idx]
        ok, msg = terminate_zombie_worker(target.pid)
        if ok:
            self.policy.record_audit_event("usuario", "Cierre worker MCP", msg, target.ram_mb)
        self.notify_cb(msg)
        self.refresh_all()
