"""Processes & Agentic AI view: EcoQoS, Working Set Trimming, Zombie MCP hunter, SRE guardrails."""

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
from ...core.sre_policy import SREPolicyEngine
from ..svg_icons import load_svg_icon
from ..widgets import GlassPanel, StatusTag


class ProcessesView(QWidget):
    """Process monitor, Agentic AI memory optimizer, and SRE automation toggles."""

    def __init__(
        self,
        policy: SREPolicyEngine,
        run_async: Callable,
        boost_cb: Callable[[], None],
        notify_cb: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.policy = policy
        self.run_async = run_async
        self.boost_cb = boost_cb
        self.notify_cb = notify_cb
        self.zombies: list[ZombieWorker] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # Header + 1 primary action
        header = QHBoxLayout()
        tbox = QVBoxLayout()
        tbox.setSpacing(3)
        title = QLabel("Procesos e IA Agentica")
        title.setObjectName("PageTitle")
        sub = QLabel("Compactacion de memoria RAM, modo EcoQoS y deteccion de workers MCP huerfanos.")
        sub.setObjectName("PageSubtitle")
        tbox.addWidget(title)
        tbox.addWidget(sub)
        header.addLayout(tbox)
        header.addStretch()

        self.boost_btn = QPushButton(" Compactar RAM y EcoQoS")
        self.boost_btn.setObjectName("PrimaryAction")
        self.boost_btn.setIcon(load_svg_icon("process", color="#0B0D10", size=14))
        self.boost_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boost_btn.clicked.connect(self.boost_cb)
        header.addWidget(self.boost_btn)
        root.addLayout(header)

        # SRE Policy Bar (clean toggles without clutter)
        sre_panel = GlassPanel()
        sre_layout = QHBoxLayout(sre_panel)
        sre_layout.setContentsMargins(14, 10, 14, 10)
        sre_layout.setSpacing(18)

        self.auto_ram_chk = QCheckBox(
            f"Alivio automatico SRE si RAM libre < {self.policy.config.ram_threshold_gb:.1f} GB (histeresis 5m)"
        )
        self.auto_ram_chk.setChecked(self.policy.config.auto_ram_relief_enabled)
        self.auto_ram_chk.toggled.connect(self._save_policy_toggles)
        sre_layout.addWidget(self.auto_ram_chk)

        self.ecoqos_chk = QCheckBox("EcoQoS en navegadores y segundo plano")
        self.ecoqos_chk.setChecked(self.policy.config.auto_ecoqos_background_browsers)
        self.ecoqos_chk.toggled.connect(self._save_policy_toggles)
        sre_layout.addWidget(self.ecoqos_chk)

        sre_layout.addStretch()
        self.refresh_btn = QPushButton("Actualizar Lista")
        self.refresh_btn.setObjectName("GhostAction")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.refresh_all)
        sre_layout.addWidget(self.refresh_btn)
        root.addWidget(sre_panel)

        # Active top processes table
        self.proc_table = QTableWidget(0, 5)
        self.proc_table.setHorizontalHeaderLabels(["PID", "PROCESO", "CLASIFICACION", "RAM (MB)", "ECOQOS"])
        self.proc_table.verticalHeader().setVisible(False)
        self.proc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.proc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.proc_table.setAlternatingRowColors(True)
        hdr = self.proc_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
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
        self.kill_zombie_btn.setObjectName("GhostAction")
        self.kill_zombie_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.kill_zombie_btn.clicked.connect(self._kill_selected_zombie)
        z_hdr.addWidget(self.kill_zombie_btn)
        z_layout.addLayout(z_hdr)

        self.zombie_table = QTableWidget(0, 4)
        self.zombie_table.setHorizontalHeaderLabels(["PID", "PROCESO", "RAM (MB)", "COMANDO"])
        self.zombie_table.verticalHeader().setVisible(False)
        self.zombie_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.zombie_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.zombie_table.setAlternatingRowColors(True)
        zhdr = self.zombie_table.horizontalHeader()
        zhdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        zhdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        zhdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        zhdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        z_layout.addWidget(self.zombie_table)
        root.addWidget(z_panel, stretch=2)

    def _save_policy_toggles(self) -> None:
        self.policy.config.auto_ram_relief_enabled = self.auto_ram_chk.isChecked()
        self.policy.config.auto_ecoqos_background_browsers = self.ecoqos_chk.isChecked()
        self.policy.save_config()

    def refresh_all(self) -> None:
        self.run_async(lambda: list_top_processes(35), self._render_processes)
        self.run_async(detect_orphan_ai_workers, self._render_zombies)

    def _render_processes(self, entries: list[ProcessEntry]) -> None:
        self.proc_table.setRowCount(len(entries))
        for r, item in enumerate(entries):
            self.proc_table.setItem(r, 0, QTableWidgetItem(str(item.pid)))
            self.proc_table.setItem(r, 1, QTableWidgetItem(item.name))
            self.proc_table.setItem(r, 2, QTableWidgetItem(item.role))
            self.proc_table.setItem(r, 3, QTableWidgetItem(f"{item.ram_mb:.1f}"))
            self.proc_table.setItem(r, 4, QTableWidgetItem("ELEGIBLE" if item.ecoqos_eligible else "PROTEGIDO"))

    def _render_zombies(self, items: list[ZombieWorker]) -> None:
        self.zombies = items
        self.zombie_table.setRowCount(len(items))
        self.zombie_tag.set_tone(
            f"{len(items)} DETECTADOS",
            "warn" if items else "ok",
        )
        for r, z in enumerate(items):
            self.zombie_table.setItem(r, 0, QTableWidgetItem(str(z.pid)))
            self.zombie_table.setItem(r, 1, QTableWidgetItem(z.name))
            self.zombie_table.setItem(r, 2, QTableWidgetItem(f"{z.ram_mb:.1f}"))
            self.zombie_table.setItem(r, 3, QTableWidgetItem(z.cmdline))

    def _kill_selected_zombie(self) -> None:
        rows = sorted({idx.row() for idx in self.zombie_table.selectedIndexes()})
        if not rows:
            self.notify_cb("Seleccione un worker huerfano en la tabla inferior.")
            return
        idx = rows[0]
        if idx >= len(self.zombies):
            return
        target = self.zombies[idx]
        ok, msg = terminate_zombie_worker(target.pid)
        if ok:
            self.policy.record_audit_event("usuario", "Cierre worker MCP", msg, target.ram_mb)
        self.notify_cb(msg)
        self.refresh_all()
