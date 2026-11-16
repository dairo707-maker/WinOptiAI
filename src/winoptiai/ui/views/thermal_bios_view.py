"""Thermal control & BIOS/Hardware Audit view for Windows 11 & Lenovo 82FE."""

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

from ...core.sre_policy import SREPolicyEngine
from ...thermal_bios.bios_auditor import (
    HardwareAuditReport,
    reboot_to_uefi_firmware,
    run_hardware_bios_audit,
    run_nvme_trim_analysis,
)
from ...thermal_bios.thermal_controller import (
    THERMAL_PROFILES,
    apply_thermal_profile,
    restore_default_power_scheme,
)
from ..svg_icons import load_svg_icon
from ..widgets import GlassPanel, StatusTag


class ThermalBiosView(QWidget):
    """Thermal profile manager and read-only UEFI/Driver/NVMe hardware auditor."""

    def __init__(
        self,
        policy: SREPolicyEngine,
        run_async: Callable,
        notify_cb: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.policy = policy
        self.run_async = run_async
        self.notify_cb = notify_cb
        self.profile_buttons: dict[str, QPushButton] = {}
        self.last_report: HardwareAuditReport | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # Header + 1 primary action
        header = QHBoxLayout()
        tbox = QVBoxLayout()
        tbox.setSpacing(3)
        title = QLabel("Control Termico y Auditoria BIOS")
        title.setObjectName("PageTitle")
        sub = QLabel("Regulacion oficial de energia EPP/Turbo Boost, analisis de drivers e integridad UEFI.")
        sub.setObjectName("PageSubtitle")
        tbox.addWidget(title)
        tbox.addWidget(sub)
        header.addLayout(tbox)
        header.addStretch()

        self.audit_btn = QPushButton(" Auditar Hardware y BIOS")
        self.audit_btn.setObjectName("PrimaryAction")
        self.audit_btn.setIcon(load_svg_icon("shield", color="#0B0D10", size=14))
        self.audit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.audit_btn.clicked.connect(self.refresh_audit)
        header.addWidget(self.audit_btn)
        root.addLayout(header)

        # Thermal Profiles Strip (3 clean 0px cards)
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

        # Hardware spec summary + secondary firmware actions
        hw_panel = GlassPanel()
        hw_layout = QHBoxLayout(hw_panel)
        hw_layout.setContentsMargins(14, 12, 14, 12)
        hw_layout.setSpacing(12)

        self.hw_lbl = QLabel("Cargando inventario SMBIOS / WMI...")
        self.hw_lbl.setObjectName("MonoValue")
        self.hw_lbl.setWordWrap(True)
        hw_layout.addWidget(self.hw_lbl, stretch=1)

        self.trim_btn = QPushButton("Optimizar TRIM SSD")
        self.trim_btn.setObjectName("GhostAction")
        self.trim_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.trim_btn.clicked.connect(self._on_trim)
        hw_layout.addWidget(self.trim_btn)

        self.uefi_btn = QPushButton("Reiniciar a UEFI BIOS")
        self.uefi_btn.setObjectName("GhostAction")
        self.uefi_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.uefi_btn.clicked.connect(self._on_reboot_uefi)
        hw_layout.addWidget(self.uefi_btn)

        self.reset_pwr_btn = QPushButton("Restaurar Energia")
        self.reset_pwr_btn.setObjectName("GhostAction")
        self.reset_pwr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_pwr_btn.clicked.connect(self._on_restore_power)
        hw_layout.addWidget(self.reset_pwr_btn)
        root.addWidget(hw_panel)

        # Recommendations table
        self.rec_table = QTableWidget(0, 3)
        self.rec_table.setHorizontalHeaderLabels(["SUBSISTEMA", "ESTADO", "DIAGNOSTICO Y RECOMENDACION"])
        self.rec_table.verticalHeader().setVisible(False)
        self.rec_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.rec_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.rec_table.setWordWrap(True)
        self.rec_table.setAlternatingRowColors(True)
        hdr = self.rec_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.rec_table, stretch=1)

        self._highlight_profile_button(self.policy.config.active_thermal_profile)

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

    def _on_trim(self) -> None:
        _, msg = run_nvme_trim_analysis()
        self.notify_cb(msg)

    def _on_reboot_uefi(self) -> None:
        _, msg = reboot_to_uefi_firmware()
        self.notify_cb(msg)

    def refresh_audit(self) -> None:
        self.audit_btn.setEnabled(False)
        self.run_async(run_hardware_bios_audit, self._on_audit_ready)

    def _on_audit_ready(self, report: HardwareAuditReport) -> None:
        self.audit_btn.setEnabled(True)
        self.last_report = report
        self.hw_lbl.setText(
            f"EQUIPO: {report.manufacturer} {report.model}  |  BIOS: {report.bios_version} ({report.bios_date})\n"
            f"CPU: {report.cpu_name} ({report.cpu_cores})  |  VIRT: {report.virtualization}  |  SECURE BOOT: {report.secure_boot}\n"
            f"GPU: {report.gpu_name} (Driver {report.gpu_driver})  |  NVMe: {report.nvme_model} [{report.nvme_health}]"
        )
        self.rec_table.setRowCount(len(report.recommendations))
        for r, item in enumerate(report.recommendations):
            self.rec_table.setItem(r, 0, QTableWidgetItem(item["area"]))
            self.rec_table.setItem(r, 1, QTableWidgetItem(item["estado"]))
            self.rec_table.setItem(r, 2, QTableWidgetItem(item["detalle"]))
        self.rec_table.resizeRowsToContents()
