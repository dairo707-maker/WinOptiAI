"""Resumen view (no vertical scroll at 980x650): single-row KPI cards, health semaphores, and live charts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.help_catalog import TOOLTIPS
from ...core.i18n import tr
from ...core.metrics_history import MetricsHistory
from ...core.telemetry import LiveSystemTelemetry, diagnose_bottleneck
from ..history_charts import FreedSpacePanel, HistoryPanel, SystemGaugesWidget
from ..svg_icons import load_svg_icon
from ..context_menu import copy_row_extra, copy_text, install_action_menu
from ..theme import get_palette
from ..widgets import (
    AdaptiveButton,
    FlowLayout,
    GlassPanel,
    NumericTableItem,
    SectionBenefitStrip,
    SemaphoreDot,
    SharpMetricCell,
    StatusTag,
    apply_table_tooltips,
    configure_interactive_columns,
    configure_sortable_table,
)

if TYPE_CHECKING:
    from ...core.sre_policy import SREPolicyEngine


class OverviewView(QWidget):
    """Scroll-free dashboard overview with TRODAI semaphores, radial gauges, and 24h/7d history."""

    trigger_ai_boost = Signal()
    trigger_focus_mode = Signal()
    jump_tab_requested = Signal(int)

    def __init__(
        self,
        lang: str = "es",
        parent: QWidget | None = None,
        policy: SREPolicyEngine | None = None,
    ) -> None:
        super().__init__(parent)
        self.lang = lang
        self.policy = policy
        self._theme_mode = "dark"
        self._subsystems: dict[str, tuple[str, str]] = {
            "ram": ("OK", "ok"),
            "disk": ("OK", "ok"),
            "thermal": ("NORMAL", "ok"),
            "apps": ("SIN ESCANEO", "neutral"),
            "startup": ("SIN ESCANEO", "neutral"),
        }

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 12)
        root.setSpacing(8)

        # Compact efficient header + inline status tag + optional guide toggle
        header = QHBoxLayout()
        header.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        self.title_lbl = QLabel(tr("overview_title", lang))
        self.title_lbl.setObjectName("PageTitle")
        self.sub_lbl = QLabel(tr("overview_sub", lang))
        self.sub_lbl.setObjectName("PageSubtitle")
        self.sub_lbl.setWordWrap(True)
        title_box.addWidget(self.title_lbl)
        title_box.addWidget(self.sub_lbl)
        header.addLayout(title_box, stretch=1)

        self.active_tag = StatusTag("EN REPOSO", "neutral")
        self.active_tasks_lbl = self.active_tag  # alias legible para tooltips
        header.addWidget(self.active_tag)

        self.help_toggle_btn = QPushButton("?")
        self.help_toggle_btn.setObjectName("GhostAction")
        self.help_toggle_btn.setToolTip("Mostrar u ocultar que mejora esta vista")
        self.help_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.help_toggle_btn.clicked.connect(self._toggle_benefit_strip)
        header.addWidget(self.help_toggle_btn)

        self.focus_btn = AdaptiveButton("Modo Enfoque")
        self.focus_btn.setObjectName("GhostAction")
        self.focus_btn.set_variants(["Modo Enfoque", "Enfoque"])
        self.focus_btn.setCheckable(True)
        self.focus_btn.setToolTip(TOOLTIPS["overview_focus"])
        self.focus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.focus_btn.clicked.connect(self.trigger_focus_mode.emit)
        header.addWidget(self.focus_btn)

        self.boost_btn = QPushButton(f" {tr('btn_ai_boost', lang)}")
        self.boost_btn.setObjectName("PrimaryAction")
        self.boost_btn.setIcon(load_svg_icon("process", color="#0A0F1D", size=14))
        self.boost_btn.setToolTip(TOOLTIPS["overview_boost"])
        self.boost_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boost_btn.clicked.connect(self.trigger_ai_boost.emit)
        header.addWidget(self.boost_btn)
        root.addLayout(header)

        self.benefit_strip = SectionBenefitStrip("overview")
        self.benefit_strip.setVisible(False)
        root.addWidget(self.benefit_strip)

        # 4 KPI cards in ONE single horizontal row -> zero scroll at 980x650
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.ram_cell = SharpMetricCell(tr("metric_ram", lang), "process", ultra_compact=True)
        self.ram_cell.setToolTip(TOOLTIPS["metric_ram"])
        self.disk_cell = SharpMetricCell(tr("metric_disk", lang), "storage", ultra_compact=True)
        self.disk_cell.setToolTip(TOOLTIPS["metric_disk"])
        self.cpu_cell = SharpMetricCell(tr("metric_cpu_temp", lang), "thermal", ultra_compact=True)
        self.cpu_cell.setToolTip(TOOLTIPS["metric_cpu_temp"])
        self.sre_cell = SharpMetricCell(tr("metric_sre", lang), "shield", ultra_compact=True)
        self.sre_cell.setToolTip(TOOLTIPS["metric_sre"])
        for cell in (self.ram_cell, self.disk_cell, self.cpu_cell, self.sre_cell):
            row1.addWidget(cell, stretch=1)
        root.addLayout(row1)

        # Compact Semaforo de Salud bar with clickable subsystem shortcuts
        sem_panel = GlassPanel()
        sem_outer = QHBoxLayout(sem_panel)
        sem_outer.setContentsMargins(10, 5, 10, 5)
        sem_outer.setSpacing(8)
        sem_lbl = QLabel("SEMAFORO")
        sem_lbl.setObjectName("SectionLabel")
        sem_outer.addWidget(sem_lbl)

        sem_flow = FlowLayout(spacing=6)
        self._sem_widgets: dict[str, tuple[SemaphoreDot, QPushButton, str]] = {}
        specs = [
            ("ram", "RAM", 2),
            ("disk", "Disco", 1),
            ("thermal", "Termica", 3),
            ("apps", "Apps", 4),
            ("startup", "Inicio", 5),
        ]
        for key, label, target_tab in specs:
            pill = QWidget()
            pl = QHBoxLayout(pill)
            pl.setContentsMargins(2, 0, 2, 0)
            pl.setSpacing(4)
            dot = SemaphoreDot("neutral", self._theme_mode)
            btn = QPushButton(f"{label}: --")
            btn.setObjectName("GhostAction")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"Ir a la seccion {label}")
            btn.clicked.connect(lambda _=False, tab=target_tab: self.jump_tab_requested.emit(tab))
            pl.addWidget(dot)
            pl.addWidget(btn)
            self._sem_widgets[key] = (dot, btn, label)
            sem_flow.addWidget(pill)
        sem_outer.addLayout(sem_flow, stretch=1)
        self.policy_tag = StatusTag("TRODAI SRE", "active")
        sem_outer.addWidget(self.policy_tag)
        root.addWidget(sem_panel)

        # Main visual monitoring area: 24h/7d curves + live gauges | Space Freed | Audit Log
        audit_panel = GlassPanel()
        audit_layout = QVBoxLayout(audit_panel)
        audit_layout.setContentsMargins(12, 8, 12, 8)
        audit_layout.setSpacing(4)

        palette_fn = lambda: get_palette(self._theme_mode)  # noqa: E731
        self.monitor_tabs = QTabWidget()
        self.monitor_tabs.setDocumentMode(True)

        charts_page = QWidget()
        cp_layout = QHBoxLayout(charts_page)
        cp_layout.setContentsMargins(0, 6, 0, 0)
        cp_layout.setSpacing(10)
        self.history_panel = HistoryPanel(palette_fn)
        self.gauges_widget = SystemGaugesWidget(palette_fn)
        self.gauges_widget.setMinimumWidth(190)
        self.gauges_widget.setMaximumWidth(235)
        cp_layout.addWidget(self.history_panel, stretch=7)
        cp_layout.addWidget(self.gauges_widget, stretch=3)
        self.monitor_tabs.addTab(charts_page, tr("tab_history", lang))

        self.freed_panel = FreedSpacePanel(palette_fn)
        self.monitor_tabs.addTab(self.freed_panel, tr("tab_freed", lang))

        audit_page = QWidget()
        ap_layout = QVBoxLayout(audit_page)
        ap_layout.setContentsMargins(0, 6, 0, 0)
        self.audit_table = QTableWidget(0, 4)
        self.audit_table.setHorizontalHeaderLabels(["HORA", "ORIGEN", "ACCION", "RESULTADO"])
        configure_sortable_table(self.audit_table)
        self.audit_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        configure_interactive_columns(
            self.audit_table,
            [98, 108, 185, 480],
            policy=self.policy,
            storage_key="overview_audit_table",
        )
        ap_layout.addWidget(self.audit_table)
        # v0.6.5: clic derecho en el registro
        install_action_menu(self.audit_table, extras=lambda: [copy_row_extra(self.audit_table)])
        self.monitor_tabs.addTab(audit_page, tr("tab_audit", lang))
        self.monitor_tabs.currentChanged.connect(lambda _i: self.schedule_history_refresh(0))
        audit_layout.addWidget(self.monitor_tabs, stretch=1)
        root.addWidget(audit_panel, stretch=1)

    def _toggle_benefit_strip(self) -> None:
        show = not self.benefit_strip.isVisible()
        self.benefit_strip.setVisible(show)
        self.benefit_strip.set_expanded(show)

    def update_subsystem_semaphore(self, key: str, state_text: str, tone: str) -> None:
        self._subsystems[key] = (state_text, tone)
        entry = self._sem_widgets.get(key)
        if entry is None:
            return
        dot, btn, label = entry
        dot.set_tone(tone, self._theme_mode)
        btn.setText(f"{label}: {state_text}")

    def attach_metrics(self, history: MetricsHistory, threshold_fn) -> None:
        """Conectar el historial local (lecturas siempre en la hebra de MetricsHistory)."""
        self.history_panel.attach(history, threshold_fn)
        self.freed_panel.attach(history, threshold_fn)

    def schedule_history_refresh(self, delay_ms: int = 600) -> None:
        """Recargar solo la pestana visible (coalescido); las demas se recargan al mostrarse."""
        current = self.monitor_tabs.currentWidget()
        if current is self.freed_panel:
            self.freed_panel.schedule_refresh(delay_ms)
        elif self.monitor_tabs.currentIndex() == 0:
            self.history_panel.schedule_refresh(delay_ms)

    def apply_language_and_theme(self, lang: str, theme_mode: str, icon_inverted: str) -> None:
        self.lang = lang
        self._theme_mode = theme_mode
        self.title_lbl.setText(tr("overview_title", lang))
        self.sub_lbl.setText(tr("overview_sub", lang))
        self.boost_btn.setText(f" {tr('btn_ai_boost', lang)}")
        self.boost_btn.setIcon(load_svg_icon("process", color=icon_inverted, size=14))
        self.ram_cell.set_title(tr("metric_ram", lang))
        self.disk_cell.set_title(tr("metric_disk", lang))
        self.cpu_cell.set_title(tr("metric_cpu_temp", lang))
        self.sre_cell.set_title(tr("metric_sre", lang))
        for i, key in enumerate(("tab_history", "tab_freed", "tab_audit")):
            self.monitor_tabs.setTabText(i, tr(key, lang))
        self.history_panel.chart.update()
        self.gauges_widget.update()
        self.freed_panel.chart.update()
        self.freed_panel.legend.update()
        for cell in (self.ram_cell, self.disk_cell, self.cpu_cell, self.sre_cell):
            cell.refresh_theme(theme_mode)
        for key, (state_text, tone) in self._subsystems.items():
            dot, _btn, _lbl = self._sem_widgets[key]
            dot.set_tone(tone, theme_mode)

    def set_active_tasks(self, task_names: list[str]) -> None:
        if task_names:
            self.active_tag.set_tone(f"{len(task_names)} EN CURSO", "active")
            self.active_tag.setToolTip("Tareas activas:\n" + "\n".join(task_names))
        else:
            self.active_tag.set_tone("EN REPOSO", "neutral")
            self.active_tag.setToolTip("Monitoreo pasivo TRODAI activo")

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
        ram_tag = "CRITICO" if ram_tone == "risk" else ("AJUSTADA" if ram_tone == "warn" else "OK")
        ram_sub = f"de {total_gb:.0f} GB ({used_pct}%)"
        if live.commit_pct > 0:
            ram_sub += f" · Commit {live.commit_pct:.0f}%"
        self.ram_cell.update_metric(
            f"{free_gb:.2f} GB libres",
            ram_sub,
            used_pct,
            ram_tag,
            ram_tone,
        )
        self.update_subsystem_semaphore("ram", ram_tag, ram_tone)

        used_disk = max(0.0, disk_total_gb - disk_free_gb)
        disk_pct = int((used_disk / disk_total_gb) * 100) if disk_total_gb > 0 else 0
        disk_tone = "risk" if disk_pct >= 92 or live.disk_active_pct >= 92 else ("warn" if disk_pct >= 82 or live.disk_active_pct >= 75 else "ok")
        disk_tag = "SATURADO" if live.disk_active_pct >= 90 else ("LLENO" if disk_pct >= 92 else ("ALTO" if disk_tone == "warn" else "OK"))
        io_rw = live.disk_read_mb_s + live.disk_write_mb_s
        disk_sub = f"{used_disk:.0f} / {disk_total_gb:.0f} GB ({disk_pct}%)"
        if live.disk_active_pct > 0 or io_rw > 0:
            disk_sub += f" · Act. {live.disk_active_pct:.0f}% · {io_rw:.1f} MB/s"
        self.disk_cell.update_metric(
            f"{disk_free_gb:.1f} GB libres",
            disk_sub,
            disk_pct,
            disk_tag,
            disk_tone,
        )
        self.update_subsystem_semaphore("disk", f"{100 - disk_pct}% lib.", disk_tone)

        freq_ghz = live.cpu_freq_mhz / 1000.0 if live.cpu_freq_mhz else 0.0
        temp_part = f" · {live.cpu_temp_c:.0f} C" if live.cpu_temp_c is not None else ""
        cpu_int = int(live.cpu_utility_pct)
        cpu_tone = "risk" if (live.cpu_temp_c or 0) >= 85 or cpu_int >= 90 else ("warn" if (live.cpu_temp_c or 0) >= 72 or cpu_int >= 70 else "ok")
        cpu_tag = f"{live.cpu_temp_c:.0f} C" if live.cpu_temp_c else ("ALTA" if cpu_tone != "ok" else "OK")
        thermal_short = thermal_label.replace(" Inteligente", "").replace(" Local Maxima", " Max").replace(" / Silencioso", "")
        gpu_part = f" · GPU {live.gpu_util_pct:.0f}%" if (live.gpu_util_pct > 0 or live.gpu_vram_shared_mb > 0) else ""
        self.cpu_cell.update_metric(
            f"{live.cpu_utility_pct:.0f}% · {freq_ghz:.2f} GHz{temp_part}",
            f"Turbo {live.cpu_turbo_pct:.0f}%{gpu_part} · {thermal_short}",
            cpu_int,
            cpu_tag,
            cpu_tone,
        )
        self.update_subsystem_semaphore("thermal", cpu_tag, cpu_tone)

        net_total = live.net_rx_mb_s + live.net_tx_mb_s
        sre_sub = f"Umbral < {threshold_gb:.1f} GB · 5m"
        if net_total > 0 or live.handles_count > 0:
            sre_sub = f"Umbral < {threshold_gb:.1f} GB · Red {net_total:.1f} MB/s"
        self.sre_cell.update_metric(
            "Activo" if sre_active else "Manual",
            sre_sub,
            100 if sre_active else 0,
            "ON" if sre_active else "PAUSA",
            "ok" if sre_active else "warn",
        )

        diag = diagnose_bottleneck(live, float(ram["used_pct"]), free_gb, threshold_gb)
        self.policy_tag.set_tone(diag.label.upper(), "active" if diag.tone == "ok" else diag.tone)
        self.policy_tag.setToolTip(
            f"{diag.detail}\nHandles: {live.handles_count} | Hilos: {live.threads_count} | "
            f"VRAM comp.: {live.gpu_vram_shared_mb:.0f} MB"
        )

        # Semáforo global para el panel de medidores radiales
        worst = "ok"
        if "risk" in (ram_tone, disk_tone, cpu_tone):
            worst = "risk"
        elif "warn" in (ram_tone, disk_tone, cpu_tone):
            worst = "warn"
        h_label = "OPTIMO" if worst == "ok" else ("ATENCION" if worst == "warn" else "CRITICO")
        details = (
            f"{free_gb:.1f} GB libres",
            f"{disk_free_gb:.0f} GB libres",
            f"{freq_ghz:.2f} GHz" if freq_ghz else "En uso",
        )
        self.gauges_widget.update_values(
            used_pct, ram_tone, disk_pct, disk_tone, cpu_int, cpu_tone, h_label, worst,
            details=details, fourth=self._fourth_gauge(live),
        )

    def set_focus_mode_active(self, active: bool) -> None:
        self.focus_btn.blockSignals(True)
        self.focus_btn.setChecked(bool(active))
        self.focus_btn.set_variants(["Enfoque: ON", "Enf. ON"] if active else ["Modo Enfoque", "Enfoque"])
        self.focus_btn.setProperty("selected", bool(active))
        self.focus_btn.style().unpolish(self.focus_btn)
        self.focus_btn.style().polish(self.focus_btn)
        self.focus_btn.blockSignals(False)

    @staticmethod
    def _fourth_gauge(live: LiveSystemTelemetry) -> dict:
        """4.o medidor: temperatura de CPU si hay sensor; si no, memoria virtual (archivo de paginacion)."""
        temp = live.cpu_temp_c
        if temp is not None and temp > 0:
            t = int(round(temp))
            tone = "risk" if t >= 85 else ("warn" if t >= 72 else "ok")
            return {"label": "TEMP. CPU", "pct": min(100, t), "tone": tone, "text": f"{t} C",
                    "detail": "Critica" if tone == "risk" else ("Elevada" if tone == "warn" else "Normal")}
        if live.commit_pct > 0:
            cp = int(round(live.commit_pct))
            tone = "risk" if cp >= 90 else ("warn" if cp >= 78 else "ok")
            return {"label": "COMMIT MEM.", "pct": min(100, cp), "tone": tone, "text": f"{cp}%",
                    "detail": f"{live.commit_used_gb:.1f} / {live.commit_limit_gb:.1f} GB"}
        try:
            import psutil

            sw = psutil.swap_memory()
            pct = int(sw.percent)
            tone = "risk" if pct >= 85 else ("warn" if pct >= 65 else "ok")
            used_gb = sw.used / (1024 ** 3)
            return {"label": "MEM. VIRTUAL", "pct": pct, "tone": tone, "text": f"{pct}%",
                    "detail": f"{used_gb:.1f} GB uso"}
        except Exception:  # noqa: BLE001
            return {"label": "MEM. VIRTUAL", "pct": 0, "tone": "neutral", "text": "--", "detail": "No disponible"}

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
        apply_table_tooltips(self.audit_table)
        self.audit_table.setSortingEnabled(True)
        self.schedule_history_refresh()
