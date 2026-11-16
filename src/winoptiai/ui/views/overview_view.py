"""Resumen view: clean non-redundant live telemetry, SRE status, and 1 primary AI Boost action."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..svg_icons import load_svg_icon
from ..theme import PALETTE
from ..widgets import GlassPanel, SharpMetricCell, StatusTag


class OverviewView(QWidget):
    """Dashboard overview with zero visual clutter and 1 primary action."""

    trigger_ai_boost = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # Header row: Title + single primary action
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        title = QLabel("Estado del Sistema")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Telemetria en vivo, guardrails SRE y preparacion de memoria para IA.")
        subtitle.setObjectName("PageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()

        self.boost_btn = QPushButton(" Ejecutar AI Boost")
        self.boost_btn.setObjectName("PrimaryAction")
        self.boost_btn.setIcon(load_svg_icon("process", color="#0B0D10", size=15))
        self.boost_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boost_btn.clicked.connect(self.trigger_ai_boost.emit)
        header.addWidget(self.boost_btn)
        root.addLayout(header)

        # 4 non-redundant metric cells in a crisp 2x2 grid
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        self.ram_cell = SharpMetricCell("Memoria Fisica", "process")
        self.disk_cell = SharpMetricCell("Almacenamiento C:", "storage")
        row1.addWidget(self.ram_cell)
        row1.addWidget(self.disk_cell)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        self.cpu_cell = SharpMetricCell("Carga de CPU", "thermal")
        self.sre_cell = SharpMetricCell("Guardia SRE", "shield")
        row2.addWidget(self.cpu_cell)
        row2.addWidget(self.sre_cell)
        root.addLayout(row2)

        # Minimalist operational audit feed
        audit_panel = GlassPanel()
        audit_layout = QVBoxLayout(audit_panel)
        audit_layout.setContentsMargins(16, 14, 16, 14)
        audit_layout.setSpacing(10)

        audit_hdr = QHBoxLayout()
        lbl = QLabel("REGISTRO DE OPERACIONES")
        lbl.setObjectName("SectionLabel")
        audit_hdr.addWidget(lbl)
        audit_hdr.addStretch()
        self.policy_tag = StatusTag("HIBRIDO SRE", "active")
        audit_hdr.addWidget(self.policy_tag)
        audit_layout.addLayout(audit_hdr)

        self.audit_table = QTableWidget(0, 4)
        self.audit_table.setHorizontalHeaderLabels(["HORA", "ORIGEN", "ACCION", "RESULTADO"])
        self.audit_table.verticalHeader().setVisible(False)
        self.audit_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.audit_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.audit_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.audit_table.setAlternatingRowColors(True)
        self.audit_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.audit_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.audit_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.audit_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        audit_layout.addWidget(self.audit_table)
        root.addWidget(audit_panel, stretch=1)

    def update_telemetry(
        self,
        ram: dict[str, float],
        cpu_pct: float,
        disk_free_gb: float,
        disk_total_gb: float,
        sre_active: bool,
        threshold_gb: float,
        thermal_label: str,
    ) -> None:
        free_gb = ram["free_gb"]
        total_gb = ram["total_gb"]
        used_pct = int(ram["used_pct"])
        ram_tone = "risk" if free_gb < threshold_gb else ("warn" if free_gb < 3.0 else "ok")
        ram_tag = "PRESION" if free_gb < threshold_gb else ("AJUSTADA" if free_gb < 3.0 else "ESTABLE")
        self.ram_cell.update_metric(
            f"{free_gb:.2f} GB libres",
            f"{ram['used_gb']:.2f} GB en uso de {total_gb:.1f} GB totales",
            used_pct,
            ram_tag,
            ram_tone,
        )

        used_disk = max(0.0, disk_total_gb - disk_free_gb)
        disk_pct = int((used_disk / disk_total_gb) * 100) if disk_total_gb > 0 else 0
        self.disk_cell.update_metric(
            f"{disk_free_gb:.1f} GB libres",
            f"{used_disk:.1f} GB ocupados de {disk_total_gb:.1f} GB",
            disk_pct,
            "SALUDABLE" if disk_pct < 85 else "ALTO USO",
            "ok" if disk_pct < 85 else "warn",
        )

        cpu_int = int(cpu_pct)
        self.cpu_cell.update_metric(
            f"{cpu_pct:.0f} %",
            f"Perfil termico activo: {thermal_label}",
            cpu_int,
            "CARGA ALTA" if cpu_int >= 75 else "NORMAL",
            "warn" if cpu_int >= 75 else "neutral",
        )

        self.sre_cell.update_metric(
            "Activo" if sre_active else "Manual",
            f"Umbral automatico < {threshold_gb:.1f} GB (histeresis 5m)",
            100 if sre_active else 0,
            "GUARDRAIL" if sre_active else "PAUSADO",
            "active" if sre_active else "neutral",
        )

    def set_audit_rows(self, rows: list[dict]) -> None:
        self.audit_table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            ts = str(item.get("timestamp", ""))[11:19]
            self.audit_table.setItem(r, 0, QTableWidgetItem(ts))
            self.audit_table.setItem(r, 1, QTableWidgetItem(str(item.get("actor", "")).upper()))
            self.audit_table.setItem(r, 2, QTableWidgetItem(str(item.get("action", ""))))
            self.audit_table.setItem(r, 3, QTableWidgetItem(str(item.get("detail", ""))))
