"""Thermal control, real-time CPU/Temp monitor, pre-op backups, and actionable Hardware Audit."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.i18n import tr
from ...core.safety_guard import PreOpBackupManager
from ...core.sre_policy import SREPolicyEngine
from ...core.telemetry import LiveSystemTelemetry, probe_elevated_temperatures
from ...core.win32_bridge import reveal_in_explorer
from ...thermal_bios.bios_auditor import (
    SERVICING_ACTIONS,
    HardwareAuditReport,
    detect_active_servicing_processes,
    execute_audit_action,
    run_hardware_bios_audit,
)
from ...thermal_bios.thermal_controller import (
    THERMAL_PROFILES,
    apply_thermal_profile,
    restore_default_power_scheme,
)
from ..svg_icons import load_svg_icon
from ...core.help_catalog import TOOLTIPS
from ..widgets import FlowLayout, GlassPanel, SectionBenefitStrip, StatusTag, configure_sortable_table


# Acciones que lanzan una consola PowerShell elevada desacoplada (seguimiento informativo).
DETACHED_CONSOLE_ACTIONS: frozenset[str] = frozenset(
    {"run_chkdsk_scan", "run_sfc_dism", "run_winsxs_cleanup", "optimize_defrag", "optimize_trim"}
)


class ThermalBiosView(QWidget):
    """Real-time CPU/Thermal telemetry + universal hardware audit with backups and reboot flags."""

    audit_log_updated = Signal()

    def __init__(
        self,
        policy: SREPolicyEngine,
        backup_mgr: PreOpBackupManager,
        run_async: Callable,
        notify_cb: Callable[[str], None],
        on_elevated_temps: Callable[[float | None, float | None], None],
        lang: str = "es",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.policy = policy
        self.backup_mgr = backup_mgr
        self.run_async = run_async
        self.notify_cb = notify_cb
        self.on_elevated_temps = on_elevated_temps
        self.lang = lang
        self.profile_buttons: dict[str, QPushButton] = {}
        self.last_report: HardwareAuditReport | None = None
        # v0.5.1: acciones en curso (evita doble clic) y re-render diferido pendiente
        self._running_actions: set[str] = set()
        self._render_pending = False

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
        self.sub_lbl.setWordWrap(True)  # v0.5.6: nunca recortado en ventanas angostas
        tbox.addWidget(self.title_lbl)
        tbox.addWidget(self.sub_lbl)
        header.addLayout(tbox, 1)  # v0.5.6: el titulo usa el espacio libre

        self.audit_btn = QPushButton(" Escanear Hardware y BIOS")
        self.audit_btn.setObjectName("PrimaryAction")
        self.audit_btn.setIcon(load_svg_icon("shield", color="#0B0D10", size=14))
        self.audit_btn.setToolTip(TOOLTIPS["thermal_audit"])
        self.audit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.audit_btn.clicked.connect(self.refresh_audit)
        header.addWidget(self.audit_btn)
        root.addLayout(header)

        self.benefit_strip = SectionBenefitStrip("thermal")
        root.addWidget(self.benefit_strip)

        # Real-Time CPU Frequency / Turbo / Per-Core / Temperature strip
        rt_panel = GlassPanel(elevated=True)
        rt_layout = QHBoxLayout(rt_panel)
        rt_layout.setContentsMargins(14, 10, 14, 10)
        rt_layout.setSpacing(12)

        self.rt_cpu_lbl = QLabel("CPU: --% | Frecuencia: -- GHz | Turbo: --%")
        self.rt_cpu_lbl.setObjectName("MonoValue")
        self.rt_cpu_lbl.setWordWrap(True)  # v0.5.6
        rt_layout.addWidget(self.rt_cpu_lbl, stretch=1)

        self.rt_temp_tag = StatusTag("SENSOR TERMICO", "neutral")
        rt_layout.addWidget(self.rt_temp_tag)

        self.uac_temp_btn = QPushButton("Leer Sensores (UAC)")
        self.uac_temp_btn.setObjectName("GhostAction")
        self.uac_temp_btn.setToolTip(TOOLTIPS["thermal_uac_temp"])
        self.uac_temp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.uac_temp_btn.clicked.connect(self._on_probe_temps)
        rt_layout.addWidget(self.uac_temp_btn)
        root.addWidget(rt_panel)

        # Thermal Profiles Strip (all 3 apply immediately without reboot)
        profiles_row = QHBoxLayout()
        profiles_row.setSpacing(10)
        for key, prof in THERMAL_PROFILES.items():
            card = GlassPanel()
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 12, 14, 12)
            cl.setSpacing(8)

            # v0.5.6: titulo y etiqueta apilados (antes se recortaban en ventanas angostas)
            name_lbl = QLabel(prof.title)
            name_lbl.setStyleSheet("font-size: 13px; font-weight: 600;")
            name_lbl.setWordWrap(True)
            cl.addWidget(name_lbl)
            tag_row = QHBoxLayout()
            tag_row.addWidget(StatusTag(f"EPP {prof.epp_ac}% | SIN REINICIO", "neutral"))
            tag_row.addStretch()
            cl.addLayout(tag_row)

            desc = QLabel(prof.subtitle)
            desc.setObjectName("PageSubtitle")
            desc.setWordWrap(True)
            cl.addWidget(desc)

            btn = QPushButton("Activar Perfil")
            btn.setObjectName("GhostAction")
            btn.setToolTip(TOOLTIPS.get(f"thermal_profile_{key}", prof.subtitle))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self._select_profile(k))
            self.profile_buttons[key] = btn
            cl.addWidget(btn)
            profiles_row.addWidget(card)
        root.addLayout(profiles_row)

        # Hardware inventory summary + backup/restore/pending controls
        hw_panel = GlassPanel()
        hw_outer = QVBoxLayout(hw_panel)
        hw_outer.setContentsMargins(14, 10, 14, 10)
        hw_outer.setSpacing(8)

        self.hw_lbl = QLabel("Escaneando perfil completo de hardware...")
        self.hw_lbl.setObjectName("MonoValue")
        self.hw_lbl.setWordWrap(True)
        hw_outer.addWidget(self.hw_lbl)
        # v0.5.6: acciones en su propia fila (antes comprimian el inventario en ventanas angostas)
        hw_layout = FlowLayout(spacing=8)
        hw_outer.addLayout(hw_layout)

        self.backups_btn = QPushButton("Copias Seguridad")
        self.backups_btn.setObjectName("GhostAction")
        self.backups_btn.setToolTip(TOOLTIPS["thermal_backups"])
        self.backups_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.backups_btn.clicked.connect(lambda: reveal_in_explorer(self.backup_mgr.backups_dir))
        hw_layout.addWidget(self.backups_btn)

        self.reset_pending_btn = QPushButton("Restablecer Pendientes")
        self.reset_pending_btn.setObjectName("RestoreAction")  # v0.5.6
        self.reset_pending_btn.setToolTip(TOOLTIPS["thermal_reset_pending"])
        self.reset_pending_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_pending_btn.clicked.connect(self._on_reset_pending)
        hw_layout.addWidget(self.reset_pending_btn)

        self.reset_pwr_btn = QPushButton("Restaurar Respaldo Energia")
        self.reset_pwr_btn.setObjectName("RestoreAction")  # v0.5.6
        self.reset_pwr_btn.setToolTip(TOOLTIPS["thermal_restore_power"])
        self.reset_pwr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_pwr_btn.clicked.connect(self._on_restore_power)
        hw_layout.addWidget(self.reset_pwr_btn)
        root.addWidget(hw_panel)

        # Sortable Audit Recommendations Table with REBOOT indicator & auto-removal on execution
        self.rec_table = QTableWidget(0, 5)
        self.rec_table.setHorizontalHeaderLabels(
            ["SUBSISTEMA", "ESTADO", "REINICIO", "DIAGNOSTICO", "ACCION AUTOMATICA"]
        )
        configure_sortable_table(self.rec_table)
        self.rec_table.setWordWrap(True)
        hdr = self.rec_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
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

        self.run_async(
            probe_elevated_temperatures,
            _done,
            "Lectura termica UAC",
            on_error=lambda _e: self.uac_temp_btn.setEnabled(True),
        )

    def _highlight_profile_button(self, active_key: str) -> None:
        for key, btn in self.profile_buttons.items():
            is_active = key == active_key
            btn.setText("Perfil Activo" if is_active else "Activar Perfil")
            btn.setProperty("selected", is_active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _select_profile(self, key: str) -> None:
        bdir = self.backup_mgr.backup_power_scheme(f"perfil_{key}")
        self.policy.record_audit_event("backup", "Respaldo energia", f"Copia previa en {bdir.name if bdir else 'local'}")
        ok, msg = apply_thermal_profile(key)
        if ok:
            self.policy.config.active_thermal_profile = key
            self.policy.save_config()
            self._highlight_profile_button(key)
            self.policy.record_audit_event("usuario", "Perfil termico (Sin reinicio)", msg)
        self.audit_log_updated.emit()
        self.notify_cb(f"{msg} (Aplicado en caliente sin reiniciar)")

    def _on_restore_power(self) -> None:
        ok, msg = self.backup_mgr.restore_latest_power_backup()
        if not ok:
            ok, msg = restore_default_power_scheme()
        if ok:
            self.policy.config.active_thermal_profile = "balanced"
            self.policy.save_config()
            self._highlight_profile_button("balanced")
            self.policy.record_audit_event("usuario", "Restauracion energia", msg)
            self.audit_log_updated.emit()
        self.notify_cb(msg)

    def _on_reset_pending(self) -> None:
        self.policy.reset_completed_audits()
        self._schedule_render_recommendations()
        self.notify_cb("Pendientes de auditoria restablecidos.")

    def refresh_audit(self) -> None:
        self.audit_btn.setEnabled(False)
        self.run_async(
            run_hardware_bios_audit,
            self._on_audit_ready,
            "Auditoria universal hardware",
            on_error=lambda _e: self.audit_btn.setEnabled(True),
        )

    def _run_recommendation(self, item: dict[str, str]) -> None:
        """Slot of a cell-widget button: never rebuild the table synchronously from here.

        v0.5.1 (fix 0xc0000005 en shiboken6): el boton emisor vive dentro de ``rec_table``.
        Reconstruir la tabla (``setRowCount``/``setCellWidget``) mientras su senal
        ``clicked`` sigue en la pila de Qt destruia el ``QPushButton`` en C++ y provocaba
        un acceso a memoria liberada. Ahora el respaldo + la accion corren en
        ``run_async`` (sin bloquear el event loop durante UAC/PowerShell) y el re-render
        se difiere con ``QTimer.singleShot(0, ...)``.
        """
        action_id = item.get("action_id", "")
        area = item.get("area", "Auditoria")
        reinicio = item.get("reinicio", "NO")

        if action_id in self._running_actions:
            self.notify_cb(f"La accion '{area}' ya esta en curso.")
            return

        if action_id in SERVICING_ACTIONS:
            active = detect_active_servicing_processes()
            if active:
                self.notify_cb(
                    f"Ya hay una operacion de servicio de Windows en curso ({', '.join(active)}). "
                    f"Espere a que termine antes de lanzar '{area}' para no encolar DISM/SFC/WinSxS."
                )
                return

        if action_id == "open_uefi_bios":
            reply = QMessageBox.question(
                self,
                "Confirmar Reinicio a UEFI BIOS",
                "Esta accion reiniciara el equipo en 10 segundos para ingresar al menu UEFI BIOS.\n"
                "Desea continuar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self.notify_cb("Reinicio a UEFI cancelado por el usuario.")
                return

        self._running_actions.add(action_id)
        self.notify_cb(f"Ejecutando '{area}' en segundo plano (respaldo previo + accion)...")
        backup_mgr = self.backup_mgr

        def _work() -> tuple[bool, str, str]:
            # Worker thread: solo subprocess/ShellExecuteW y escritura en la carpeta Backups propia.
            # Mandatory pre-operation backup before applying system changes
            bdir = backup_mgr.backup_power_scheme(f"audit_{action_id}")
            ok, msg = execute_audit_action(action_id)
            return ok, msg, (bdir.name if bdir else "Backups")

        def _done(res: tuple[bool, str, str]) -> None:
            self._on_recommendation_done(action_id, area, reinicio, res)

        def _failed(err: str) -> None:
            self._running_actions.discard(action_id)
            self.notify_cb(f"No se pudo ejecutar '{area}': {err}")

        self.run_async(_work, _done, f"Auditoria: {area}", notify_on_complete=False, on_error=_failed)

    def _on_recommendation_done(
        self, action_id: str, area: str, reinicio: str, res: tuple[bool, str, str]
    ) -> None:
        """Main-thread completion: config/audit writes stay on the UI thread (thread-safe)."""
        self._running_actions.discard(action_id)
        ok, msg, bdir_name = res
        self.policy.record_audit_event(
            "backup",
            f"Respaldo previo ({area})",
            f"Copia de seguridad guardada en {bdir_name}",
        )
        if ok:
            if action_id == "apply_cool_profile":
                self.policy.config.active_thermal_profile = "cool"
                self._highlight_profile_button("cool")
            elif action_id == "apply_balanced_profile":
                self.policy.config.active_thermal_profile = "balanced"
                self._highlight_profile_button("balanced")

            # Remove completed recommendation from pending list & log in operations history
            self.policy.mark_audit_completed(action_id)
            self.policy.record_audit_event(
                "auditoria",
                f"{area} [Reinicio: {reinicio}]",
                msg,
            )
            self.audit_log_updated.emit()
            self._schedule_render_recommendations()

        detached = ok and action_id in DETACHED_CONSOLE_ACTIONS
        suffix = (
            " | Consola elevada independiente en curso: WinOptiAI sigue disponible; "
            "revise y cierre esa ventana al terminar."
            if detached
            else ""
        )
        self.notify_cb(f"{msg} | Reinicio: {reinicio}{suffix}")

    def _schedule_render_recommendations(self) -> None:
        """Coalesce and defer table rebuilds until the current event's call-stack unwinds."""
        if self._render_pending:
            return
        self._render_pending = True
        QTimer.singleShot(0, self._deferred_render_recommendations)

    def _deferred_render_recommendations(self) -> None:
        self._render_pending = False
        if self.last_report is not None:
            self._render_recommendations(self.last_report)

    def _on_audit_ready(self, report: HardwareAuditReport) -> None:
        self.audit_btn.setEnabled(True)
        self.last_report = report
        tipo = "Portatil" if report.is_laptop else "Escritorio"
        self.hw_lbl.setText(
            f"EQUIPO: {report.manufacturer} {report.model} ({tipo})  |  BIOS: {report.bios_version} ({report.bios_date})\n"
            f"CPU: {report.cpu_name} ({report.cpu_cores})  |  RAM: {report.total_ram_gb:.1f} GB (Umbral SRE: {report.recommended_ram_threshold_gb:.1f} GB)\n"
            f"GPU: {report.gpu_name} ({report.gpu_driver})  |  DISCO: {report.nvme_model} [{report.media_type} - {report.nvme_health}]\n"
            f"SMART: {report.smart_summary} (Evt14d: {report.disk_events_count})  |  {report.security_posture}"
        )
        self._render_recommendations(report)

    def _render_recommendations(self, report: HardwareAuditReport) -> None:
        completed = set(self.policy.config.completed_audit_actions)
        pending = [r for r in report.recommendations if r.get("action_id", "") not in completed]

        self.rec_table.setSortingEnabled(False)
        self._release_cell_widgets()
        self.rec_table.setRowCount(len(pending))
        for r, item in enumerate(pending):
            self.rec_table.setItem(r, 0, QTableWidgetItem(item["area"]))
            self.rec_table.setItem(r, 1, QTableWidgetItem(item["estado"]))
            self.rec_table.setItem(r, 2, QTableWidgetItem(item.get("reinicio", "NO (inmediato)")))
            self.rec_table.setItem(r, 3, QTableWidgetItem(item["detalle"]))

            action_label = item.get("action_label", "Ejecutar")
            btn = QPushButton(action_label)
            btn.setObjectName("GhostAction")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setEnabled(item.get("action_id", "") not in self._running_actions)
            btn.clicked.connect(lambda _=False, rec=dict(item): self._run_recommendation(rec))
            self.rec_table.setCellWidget(r, 4, btn)
        self.rec_table.setSortingEnabled(True)
        self.rec_table.resizeRowsToContents()

    def _release_cell_widgets(self) -> None:
        """Detach old action buttons safely: disconnect, hide and deleteLater (never immediate delete).

        Se desconecta la senal (sin lambdas colgantes hacia filas ya inexistentes), se oculta
        y se retira con ``removeCellWidget`` (que internamente usa ``deleteLater``), de modo
        que ningun ``QPushButton`` se destruye mientras una emision siga en la pila.
        """
        col = 4
        for r in range(self.rec_table.rowCount()):
            w = self.rec_table.cellWidget(r, col)
            if w is None:
                continue
            try:
                w.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            w.hide()
            self.rec_table.removeCellWidget(r, col)
