"""Thermal control, real-time CPU/Temp monitor, and actionable Universal Hardware Audit view."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
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

from ...core.i18n import tr
from ...core.sre_policy import SREPolicyEngine
from ...core.telemetry import LiveSystemTelemetry, probe_elevated_temperatures
from ...thermal_bios.bios_auditor import (
    HardwareAuditReport,
    execute_audit_action,
    run_hardware_bios_audit,
)
from ...thermal_bios.thermal_controller import (
    THERMAL_PROFILES,
    apply_thermal_profile,
    restore_default_power_scheme,
)
from ..svg_icons import load_svg_icon
from ..widgets import GlassPanel, StatusTag, configure_sortable_table


class ThermalBiosView(QWidget):
    """Real-time CPU/Thermal telemetry + universal hardware audit with 1-click remediations."""

    def __init__(
        self,
        policy: SREPolicyEngine,
        run_async: Callable,
        notify_cb: Callable[[str], None],
        on_elevated_temps: Callable[[float | None, float | None], None],
        lang: str = "es",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.policy = policy
        self.run_async = run_async
        self.notify_cb = notify_cb
        self.on_elevated_temps = on_elevated_temps
        self.lang = lang
        self.profile_buttons: dict[str, QPushButton] = {}
        self.last_report: HardwareAuditReport | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        # Header + 1 primary action
        header = QHBoxLayout()
        tbox = QVBoxLayout()
        tbox.setSpacing(3)
        self.title_lbl = QLabel(tr("thermal_title", lang))
        self.title_lbl.setObjectName("PageTitle")
        self.sub_lbl = QLabel(tr("thermal_sub", lang))
        self.sub_lbl.setObjectName("PageSubtitle")
        tbox.addWidget(self.title_lbl)
        tbox.addWidget(self.sub_lbl)
        header.addLayout(tbox)
        header.addStretch()

        self.audit_btn = QPushButton(" Escanear Hardware y BIOS")
        self.audit_btn.setObjectName("PrimaryAction")
        self.audit_btn.setIcon(load_svg_icon("shield", color="#0B0D10", size=14))
        self.audit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.audit_btn.clicked.connect(self.refresh_audit)
        header.addWidget(self.audit_btn)
        root.addLayout(header)

        # Real-Time CPU Frequency / Turbo / Per-Core / Temperature strip
        rt_panel = GlassPanel(elevated=True)
        rt_layout = QHBoxLayout(rt_panel)
        rt_layout.setContentsMargins(14, 10, 14, 10)
        rt_layout.setSpacing(12)

        self.rt_cpu_lbl = QLabel("CPU: --% | Frecuencia: -- GHz | Turbo: --%")
        self.rt_cpu_lbl.setObjectName("MonoValue")
        rt_layout.addWidget(self.rt_cpu_lbl, stretch=1)

        self.rt_temp_tag = StatusTag("SENSOR TERMICO", "neutral")
        rt_layout.addWidget(self.rt_temp_tag)

        self.uac_temp_btn = QPushButton("Leer Sensores (UAC)")
        self.uac_temp_btn.setObjectName("GhostAction")
        self.uac_temp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.uac_temp_btn.clicked.connect(self._on_probe_temps)
        rt_layout.addWidget(self.uac_temp_btn)
        root.addWidget(rt_panel)

        # Thermal Profiles Strip
        profiles_row = QHBoxLayout()
        profiles_row.setSpacing(10)
        for key, prof in THERMAL_PROFILES.items():
            card = GlassPanel()
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 12, 14, 12)
            cl.setSpacing(8)

            top = QHBoxLayout()
            name_lbl = QLabel(prof.title)
            name_lbl.setStyleSheet("font-size: 13px; font-weight: 600;")
            top.addWidget(name_lbl)
            top.addStretch()
            top.addWidget(StatusTag(f"EPP {prof.epp_ac}%", "neutral"))
            cl.addLayout(top)

            desc = QLabel(prof.subtitle)
            desc.setObjectName("PageSubtitle")
            desc.setWordWrap(True)
            cl.addWidget(desc)

            btn = QPushButton("Activar Perfil")
            btn.setObjectName("GhostAction")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self._select_profile(k))
            self.profile_buttons[key] = btn
            cl.addWidget(btn)
            profiles_row.addWidget(card)
        root.addLayout(profiles_row)

        # Hardware inventory summary + power restore
        hw_panel = GlassPanel()
        hw_layout = QHBoxLayout(hw_panel)
        hw_layout.setContentsMargins(14, 10, 14, 10)
        hw_layout.setSpacing(12)

        self.hw_lbl = QLabel("Escaneando perfil completo de hardware...")
        self.hw_lbl.setObjectName("MonoValue")
        self.hw_lbl.setWordWrap(True)
        hw_layout.addWidget(self.hw_lbl, stretch=1)

        self.reset_pwr_btn = QPushButton("Restaurar Energia Fabrica")
        self.reset_pwr_btn.setObjectName("GhostAction")
        self.reset_pwr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_pwr_btn.clicked.connect(self._on_restore_power)
        hw_layout.addWidget(self.reset_pwr_btn)
        root.addWidget(hw_panel)

        # Sortable Audit Recommendations Table WITH automated 1-click "ACCION" column
        self.rec_table = QTableWidget(0, 4)
        self.rec_table.setHorizontalHeaderLabels(
            ["SUBSISTEMA", "ESTADO", "DIAGNOSTICO Y RECOMENDACION", "ACCION AUTOMATICA"]
        )
        configure_sortable_table(self.rec_table)
        self.rec_table.setWordWrap(True)
        hdr = self.rec_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.rec_table, stretch=1)

        self._highlight_profile_button(self.policy.config.active_thermal_profile)

    def apply_language_and_theme(self, lang: str, icon_inverted: str) -> None:
        self.lang = lang
        self.title_lbl.setText(tr("thermal_title", lang))
        self.sub_lbl.setText(tr("thermal_sub", lang))
        self.audit_btn.setIcon(load_svg_icon("shield", color=icon_inverted, size=14))

    def update_live_telemetry(self, live: LiveSystemTelemetry) -> None:
        freq_ghz = live.cpu_freq_mhz / 1000.0 if live.cpu_freq_mhz else 0.0
        cores_preview = " ".join(f"{int(c)}%" for c in live.per_core_pct[:8])
        self.rt_cpu_lbl.setText(
            f"CPU: {live.cpu_utility_pct:.0f}%  |  Reloj: {freq_ghz:.2f} GHz  |  "
            f"Turbo: {live.cpu_turbo_pct:.0f}%  |  Nucleos: [{cores_preview}]"
        )
        if live.cpu_temp_c is not None:
            nvme_str = f" / NVMe {live.nvme_temp_c:.0f} C" if live.nvme_temp_c is not None else ""
            tone = "risk" if live.cpu_temp_c >= 85 else ("warn" if live.cpu_temp_c >= 72 else "ok")
            self.rt_temp_tag.set_tone(f"CPU {live.cpu_temp_c:.1f} C{nvme_str}", tone)
        else:
            self.rt_temp_tag.set_tone("ACPI PROTEGIDO (UAC)", "neutral")

    def _on_probe_temps(self) -> None:
        self.uac_temp_btn.setEnabled(False)
        self.notify_cb("Solicitando lectura termica ACPI/NVMe (UAC)...")

        def _done(res: tuple[float | None, float | None, str]) -> None:
            self.uac_temp_btn.setEnabled(True)
            cpu_c, nvme_c, msg = res
            self.on_elevated_temps(cpu_c, nvme_c)
            self.notify_cb(msg)

        self.run_async(probe_elevated_temperatures, _done, "Lectura termica UAC")

    def _highlight_profile_button(self, active_key: str) -> None:
        for key, btn in self.profile_buttons.items():
            is_active = key == active_key
            btn.setText("Perfil Activo" if is_active else "Activar Perfil")
            btn.setProperty("selected", is_active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _select_profile(self, key: str) -> None:
        ok, msg = apply_thermal_profile(key)
        if ok:
            self.policy.config.active_thermal_profile = key
            self.policy.save_config()
            self._highlight_profile_button(key)
            self.policy.record_audit_event("usuario", "Perfil termico", msg)
        self.notify_cb(msg)

    def _on_restore_power(self) -> None:
        ok, msg = restore_default_power_scheme()
        if ok:
            self.policy.config.active_thermal_profile = "balanced"
            self.policy.save_config()
            self._highlight_profile_button("balanced")
            self.policy.record_audit_event("usuario", "Energia fabrica", msg)
        self.notify_cb(msg)

    def refresh_audit(self) -> None:
        self.audit_btn.setEnabled(False)
        self.run_async(run_hardware_bios_audit, self._on_audit_ready, "Auditoria universal hardware")

    def _run_recommendation(self, action_id: str, area: str) -> None:
        ok, msg = execute_audit_action(action_id)
        if ok:
            if action_id == "apply_cool_profile":
                self.policy.config.active_thermal_profile = "cool"
                self.policy.save_config()
                self._highlight_profile_button("cool")
            elif action_id == "apply_balanced_profile":
                self.policy.config.active_thermal_profile = "balanced"
                self.policy.save_config()
                self._highlight_profile_button("balanced")
            self.policy.record_audit_event("auditoria", f"Accion {area}", msg)
        self.notify_cb(msg)

    def _on_audit_ready(self, report: HardwareAuditReport) -> None:
        self.audit_btn.setEnabled(True)
        self.last_report = report
        tipo = "Portatil" if report.is_laptop else "Escritorio"
        self.hw_lbl.setText(
            f"EQUIPO: {report.manufacturer} {report.model} ({tipo})  |  BIOS: {report.bios_version} ({report.bios_date})\n"
            f"CPU: {report.cpu_name} ({report.cpu_cores})  |  RAM: {report.total_ram_gb:.1f} GB (Umbral SRE: {report.recommended_ram_threshold_gb:.1f} GB)\n"
            f"GPU: {report.gpu_name} ({report.gpu_driver})  |  DISCO: {report.nvme_model} [{report.media_type} - {report.nvme_health}]"
        )

        self.rec_table.setSortingEnabled(False)
        self.rec_table.setRowCount(len(report.recommendations))
        for r, item in enumerate(report.recommendations):
            self.rec_table.setItem(r, 0, QTableWidgetItem(item["area"]))
            self.rec_table.setItem(r, 1, QTableWidgetItem(item["estado"]))
            self.rec_table.setItem(r, 2, QTableWidgetItem(item["detalle"]))

            action_id = item.get("action_id", "")
            action_label = item.get("action_label", "Ejecutar")
            btn = QPushButton(action_label)
            btn.setObjectName("GhostAction")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, aid=action_id, ar=item["area"]: self._run_recommendation(aid, ar))
            self.rec_table.setCellWidget(r, 3, btn)
        self.rec_table.setSortingEnabled(True)
        self.rec_table.resizeRowsToContents()
