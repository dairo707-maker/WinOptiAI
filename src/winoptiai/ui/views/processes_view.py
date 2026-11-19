"""Processes & Agentic AI view: active app tasks, live OS processes (sortable), EcoQoS, MCP zombies."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
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
    detect_orphan_ai_workers,
    list_top_processes,
    terminate_zombie_worker,
)
from ...core.i18n import tr
from ...core.sre_policy import SREPolicyEngine
from ..svg_icons import load_svg_icon
from ...core.help_catalog import TOOLTIPS
from ..widgets import (
    GlassPanel,
    NumericTableItem,
    SectionBenefitStrip,
    StatusTag,
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
    ) -> None:
        super().__init__(parent)
        self.policy = policy
        self.run_async = run_async
        self.boost_cb = boost_cb
        self.notify_cb = notify_cb
        self.lang = lang
        self.zombies: list[ZombieWorker] = []

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

        # Active WinOptiAI Tasks + SRE Toggles bar
        sre_panel = GlassPanel()
        sre_layout = QHBoxLayout(sre_panel)
        sre_layout.setContentsMargins(14, 10, 14, 10)
        sre_layout.setSpacing(16)

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

        sre_layout.addStretch()
        self.active_task_tag = StatusTag("0 TAREAS APP", "neutral")
        sre_layout.addWidget(self.active_task_tag)

        self.refresh_btn = QPushButton("Actualizar")
        self.refresh_btn.setObjectName("GhostAction")
        self.refresh_btn.setToolTip(TOOLTIPS["proc_refresh"])
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.refresh_all)
        sre_layout.addWidget(self.refresh_btn)
        root.addWidget(sre_panel)

        # Active top processes table (sortable by PID, Name, Class, CPU%, RAM, EcoQoS)
        self.proc_table = QTableWidget(0, 6)
        self.proc_table.setHorizontalHeaderLabels(
            ["PID", "PROCESO", "CLASIFICACION", "CPU (%)", "RAM (MB)", "ECOQOS"]
        )
        configure_sortable_table(self.proc_table)
        hdr = self.proc_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
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
        zhdr = self.zombie_table.horizontalHeader()
        zhdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        zhdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        zhdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        zhdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        z_layout.addWidget(self.zombie_table)
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

    def _render_processes(self, entries: list[ProcessEntry]) -> None:
        self.proc_table.setSortingEnabled(False)
        self.proc_table.setRowCount(len(entries))
        for r, item in enumerate(entries):
            self.proc_table.setItem(r, 0, NumericTableItem(str(item.pid), item.pid))
            self.proc_table.setItem(r, 1, QTableWidgetItem(item.name))
            self.proc_table.setItem(r, 2, QTableWidgetItem(item.role))
            self.proc_table.setItem(r, 3, NumericTableItem(f"{item.cpu_pct:.1f}", item.cpu_pct))
            self.proc_table.setItem(r, 4, NumericTableItem(f"{item.ram_mb:.1f}", item.ram_mb))
            self.proc_table.setItem(
                r, 5, QTableWidgetItem("ELEGIBLE" if item.ecoqos_eligible else "PROTEGIDO")
            )
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
        self.zombie_table.setSortingEnabled(True)

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
