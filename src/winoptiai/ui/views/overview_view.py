"""Resumen view: live RAM/CPU/MHz/Temp telemetry, active tasks banner, SRE status, and 1 primary action."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.i18n import tr
from ...core.metrics_history import MetricsHistory
from ...core.telemetry import LiveSystemTelemetry
from ..history_charts import FreedSpacePanel, HistoryPanel
from ..svg_icons import load_svg_icon
from ..theme import get_palette
from ..widgets import GlassPanel, NumericTableItem, SharpMetricCell, StatusTag, configure_sortable_table


class OverviewView(QWidget):
    """Dashboard overview with real-time CPU/Temp/RAM telemetry and active task visibility."""

    trigger_ai_boost = Signal()

    def __init__(self, lang: str = "es", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.lang = lang
        self._theme_mode = "dark"
        # v0.5.7: contenido desplazable. A 980x650 el historial conserva una altura legible
        # (el resto de la vista se desplaza en lugar de aplastar los graficos).
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("OverviewScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Selectores explicitos: una regla sin selector se heredaria a todos los hijos.
        self.scroll.setStyleSheet(
            "QScrollArea#OverviewScroll, QWidget#qt_scrollarea_viewport, QWidget#OverviewContent"
            " { background: transparent; }"
        )
        self.scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setObjectName("OverviewContent")
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(10)

        # Header row: Title + single primary action
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        self.title_lbl = QLabel(tr("overview_title", lang))
        self.title_lbl.setObjectName("PageTitle")
        self.sub_lbl = QLabel(tr("overview_sub", lang))
        self.sub_lbl.setObjectName("PageSubtitle")
        self.sub_lbl.setWordWrap(True)  # v0.5.6: nunca recortado en ventanas angostas
        title_box.addWidget(self.title_lbl)
        title_box.addWidget(self.sub_lbl)
        header.addLayout(title_box)
        header.addStretch()

        self.boost_btn = QPushButton(f" {tr('btn_ai_boost', lang)}")
        self.boost_btn.setObjectName("PrimaryAction")
        self.boost_btn.setIcon(load_svg_icon("process", color="#0B0D10", size=15))
        self.boost_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boost_btn.clicked.connect(self.trigger_ai_boost.emit)
        header.addWidget(self.boost_btn)
        root.addLayout(header)

        # 4 non-redundant metric cells
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        self.ram_cell = SharpMetricCell(tr("metric_ram", lang), "process", compact=True)
        self.disk_cell = SharpMetricCell(tr("metric_disk", lang), "storage", compact=True)
        row1.addWidget(self.ram_cell)
        row1.addWidget(self.disk_cell)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        self.cpu_cell = SharpMetricCell(tr("metric_cpu_temp", lang), "thermal", compact=True)
        self.sre_cell = SharpMetricCell(tr("metric_sre", lang), "shield", compact=True)
        row2.addWidget(self.cpu_cell)
        row2.addWidget(self.sre_cell)
        root.addLayout(row2)

        # Active Tasks strip (shows live background scans/optimizations running right now)
        tasks_panel = GlassPanel()
        tl = QHBoxLayout(tasks_panel)
        tl.setContentsMargins(14, 9, 14, 9)
        tl.setSpacing(10)
        self.active_tag = StatusTag("EN REPOSO", "neutral")
        tl.addWidget(self.active_tag)
        self.active_tasks_lbl = QLabel("Sin tareas pesadas activas en segundo plano.")
        self.active_tasks_lbl.setObjectName("MonoValue")
        tl.addWidget(self.active_tasks_lbl, stretch=1)
        root.addWidget(tasks_panel)

        # v0.5.7: monitoreo con historial (24 h / 7 d), espacio liberado y registro, en pestanas.
        audit_panel = GlassPanel()
        audit_layout = QVBoxLayout(audit_panel)
        audit_layout.setContentsMargins(16, 12, 16, 12)
        audit_layout.setSpacing(4)

        audit_hdr = QHBoxLayout()
        self.audit_lbl = QLabel(tr("monitor_feed", lang))
        self.audit_lbl.setObjectName("SectionLabel")
        audit_hdr.addWidget(self.audit_lbl)
        audit_hdr.addStretch()
        self.policy_tag = StatusTag("HIBRIDO SRE", "active")
        audit_hdr.addWidget(self.policy_tag)
        audit_layout.addLayout(audit_hdr)

        palette_fn = lambda: get_palette(self._theme_mode)  # noqa: E731
        self.monitor_tabs = QTabWidget()
        self.monitor_tabs.setDocumentMode(True)
        self.history_panel = HistoryPanel(palette_fn)
        self.freed_panel = FreedSpacePanel(palette_fn)
        self.monitor_tabs.addTab(self.history_panel, tr("tab_history", lang))
        self.monitor_tabs.addTab(self.freed_panel, tr("tab_freed", lang))

        audit_page = QWidget()
        ap_layout = QVBoxLayout(audit_page)
        ap_layout.setContentsMargins(0, 8, 0, 0)
        self.audit_table = QTableWidget(0, 4)
        self.audit_table.setHorizontalHeaderLabels(["HORA", "ORIGEN", "ACCION", "RESULTADO"])
        configure_sortable_table(self.audit_table)
        self.audit_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.audit_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.audit_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.audit_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.audit_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        ap_layout.addWidget(self.audit_table)
        self.monitor_tabs.addTab(audit_page, tr("tab_audit", lang))
        self.monitor_tabs.currentChanged.connect(lambda _i: self.schedule_history_refresh(0))
        audit_layout.addWidget(self.monitor_tabs, stretch=1)
        audit_panel.setMinimumHeight(300)
        root.addWidget(audit_panel, stretch=1)

    def attach_metrics(self, history: MetricsHistory, threshold_fn) -> None:
        """Conectar el historial local (lecturas siempre en la hebra de MetricsHistory)."""
        self.history_panel.attach(history, threshold_fn)
        self.freed_panel.attach(history, threshold_fn)

    def schedule_history_refresh(self, delay_ms: int = 600) -> None:
        """Recargar solo la pestana visible (coalescido); las demas se recargan al mostrarse."""
        current = self.monitor_tabs.currentWidget()
        if current is self.history_panel:
            self.history_panel.schedule_refresh(delay_ms)
        elif current is self.freed_panel:
            self.freed_panel.schedule_refresh(delay_ms)

    def apply_language_and_theme(self, lang: str, theme_mode: str, icon_inverted: str) -> None:
        self.lang = lang
        self._theme_mode = theme_mode
        self.title_lbl.setText(tr("overview_title", lang))
        self.sub_lbl.setText(tr("overview_sub", lang))
        self.boost_btn.setText(f" {tr('btn_ai_boost', lang)}")
        self.boost_btn.setIcon(load_svg_icon("process", color=icon_inverted, size=15))
        self.ram_cell.set_title(tr("metric_ram", lang))
        self.disk_cell.set_title(tr("metric_disk", lang))
        self.cpu_cell.set_title(tr("metric_cpu_temp", lang))
        self.sre_cell.set_title(tr("metric_sre", lang))
        self.audit_lbl.setText(tr("monitor_feed", lang))
        for i, key in enumerate(("tab_history", "tab_freed", "tab_audit")):
            self.monitor_tabs.setTabText(i, tr(key, lang))
        self.history_panel.chart.update()
        self.freed_panel.chart.update()
        self.freed_panel.legend.update()
        for cell in (self.ram_cell, self.disk_cell, self.cpu_cell, self.sre_cell):
            cell.refresh_theme(theme_mode)

    def set_active_tasks(self, task_names: list[str]) -> None:
        if task_names:
            self.active_tag.set_tone(f"{len(task_names)} ACTIVAS", "active")
            self.active_tasks_lbl.setText("Ejecutando ahora: " + " | ".join(task_names))
        else:
            self.active_tag.set_tone("EN REPOSO", "neutral")
            self.active_tasks_lbl.setText("Monitoreo pasivo ligero activo (sin tareas pesadas en curso).")

    def update_telemetry(
        self,
        ram: dict[str, float],
        live: LiveSystemTelemetry,
        disk_free_gb: float,
        disk_total_gb: float,
        sre_active: bool,
        threshold_gb: float,
        thermal_label: str,
    ) -> None:
        free_gb = ram["free_gb"]
        total_gb = ram["total_gb"]
        used_pct = int(ram["used_pct"])
        ram_tone = "risk" if free_gb < threshold_gb else ("warn" if free_gb < threshold_gb + 1.0 else "ok")
        ram_tag = "PRESION" if free_gb < threshold_gb else ("AJUSTADA" if free_gb < threshold_gb + 1.0 else "ESTABLE")
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

        freq_ghz = live.cpu_freq_mhz / 1000.0 if live.cpu_freq_mhz else 0.0
        temp_part = f" | {live.cpu_temp_c:.1f} C" if live.cpu_temp_c is not None else ""
        cpu_int = int(live.cpu_utility_pct)
        cpu_tone = "risk" if (live.cpu_temp_c or 0) >= 85 or cpu_int >= 90 else ("warn" if cpu_int >= 70 else "neutral")
        self.cpu_cell.update_metric(
            f"{live.cpu_utility_pct:.0f}% ({freq_ghz:.2f} GHz){temp_part}",
            f"Turbo {live.cpu_turbo_pct:.0f}% | Perfil: {thermal_label}",
            cpu_int,
            f"{live.cpu_temp_c:.0f} C" if live.cpu_temp_c else ("CARGA ALTA" if cpu_int >= 75 else "NORMAL"),
            cpu_tone,
        )

        self.sre_cell.update_metric(
            "Activo" if sre_active else "Manual",
            f"Umbral calibrado < {threshold_gb:.1f} GB (histeresis 5m)",
            100 if sre_active else 0,
            "GUARDRAIL" if sre_active else "PAUSADO",
            "active" if sre_active else "neutral",
        )

    def set_audit_rows(self, rows: list[dict]) -> None:
        from datetime import datetime

        self.audit_table.setSortingEnabled(False)
        self.audit_table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            raw_ts = str(item.get("timestamp", ""))
            try:
                ts = datetime.fromisoformat(raw_ts).astimezone().strftime("%H:%M:%S")
            except ValueError:
                ts = raw_ts[11:19]
            self.audit_table.setItem(r, 0, NumericTableItem(ts, r))
            self.audit_table.setItem(r, 1, QTableWidgetItem(str(item.get("actor", "")).upper()))
            self.audit_table.setItem(r, 2, QTableWidgetItem(str(item.get("action", ""))))
            self.audit_table.setItem(r, 3, QTableWidgetItem(str(item.get("detail", ""))))
        self.audit_table.setSortingEnabled(True)
        # Nuevos eventos (AI Boost, limpiezas, informes) -> marcadores y acumulados al dia.
        self.schedule_history_refresh()
