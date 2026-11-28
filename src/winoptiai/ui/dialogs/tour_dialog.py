"""Interactive 7-step guided tour and new-PC quick system verification dialog."""

from __future__ import annotations

from typing import Callable

from shiboken6 import isValid as qt_is_valid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.onboarding_check import QuickCheckReport, run_new_pc_quick_check
from ...core.safety_guard import QuarantineVault
from ...core.sre_policy import SREPolicyEngine
from ..svg_icons import load_svg_pixmap
from ..theme import get_palette
from ..widgets import FlowLayout, GlassPanel, StatusTag, set_button_role


_TOUR_STEPS: list[dict[str, object]] = [
    {
        "tag": "PASO 1 / 7",
        "tab": 0,
        "title": "Resumen TRODAI, Semaforos y Salud 2x2",
        "subtitle": "Primera vista compacta sin scroll: 4 KPIs, semaforos interactivos y graficas.",
        "bullets": [
            "Cuatro medidores radiales 2x2 (RAM, Disco C:, CPU y Temp. CPU / Mem. Virtual) con estado de salud.",
            "Barra de semaforo clickable para saltar directo a RAM, Disco, Termica, Apps o Inicio.",
            "Curvas locales de 24 h / 7 d (metrics.sqlite), espacio liberado, boton '?' de guia y AI Boost SRE.",
        ],
    },
    {
        "tag": "PASO 2 / 7",
        "tab": 1,
        "title": "Almacenamiento, Treemap Moderno y Boveda",
        "subtitle": "Temporales, duplicados BLAKE3, columna ULTIMO USO y mapa jerarquico opaco.",
        "bullets": [
            "Temporales con Pausa, Guardar Pausa, Reanudacion y casilla tri-estado 'Seleccionar todo'.",
            "Treemap moderno opaco por categoria con ruta navegable (breadcrumbs) y tabla de archivos pesados.",
            "Columna 'ULTIMO USO' cronologica en todos los listados y Cuarentena instantanea con Deshacer.",
        ],
    },
    {
        "tag": "PASO 3 / 7",
        "tab": 2,
        "title": "Procesos e IA Agentica",
        "subtitle": "Consumo en vivo, fecha de ultimo uso y cierre seguro de workers zombis.",
        "bullets": [
            "Medicion real de % CPU, RAM y columna 'ULTIMO USO' por proceso mediante handles psutil.",
            "Deteccion de procesos Node/Python/uv huerfanos cuyo proceso padre ya cerro.",
            "Proteccion estricta para agentes IA, editores de codigo, ventana activa, antivirus y OneDrive.",
        ],
    },
    {
        "tag": "PASO 4 / 7",
        "tab": 3,
        "title": "Termica, BIOS OEM y Salud S.M.A.R.T.",
        "subtitle": "Semaforo termico en vivo, perfiles powercfg /q y diagnostico profundo de disco.",
        "bullets": [
            "Cambia al instante entre Frio/Silencioso, Equilibrado Inteligente o IA Local Maxima (tambien en la bandeja).",
            "Lee salud S.M.A.R.T. NVMe/SSD, eventos Disk/Ntfs/WHEA de 14 dias, TPM, BitLocker y HVCI.",
            "Acciones 1-clic con UAC (CHKDSK, DISM/SFC, WinSxS) protegiendo reinicios pendientes de Windows.",
        ],
    },
    {
        "tag": "PASO 5 / 7",
        "tab": 4,
        "title": "Administrador de Aplicaciones (winget)",
        "subtitle": "Inventario de programas instalados, fecha de ultimo uso, actualizaciones y limpieza.",
        "bullets": [
            "Combina el Registro de Windows con winget para listar versiones, editor, tamano y 'ULTIMO USO'.",
            "Verifica nuevas versiones disponibles y actualiza con 1 clic desde la interfaz via winget.",
            "Desinstalacion protegida (bloquea OS, drivers, antivirus y WinOptiAI) con rescate de residuos en AppData.",
        ],
    },
    {
        "tag": "PASO 6 / 7",
        "tab": 5,
        "title": "Inicio de Windows Inteligente",
        "subtitle": "Sugerencias segun uso real para acelerar el arranque de forma 100% reversible.",
        "bullets": [
            "Analiza claves Run, StartupApproved y carpetas de inicio junto con telemetria BAM, Prefetch y RAM.",
            "Asigna un semaforo inteligente (MANTENER, PAUSAR o DESACTIVAR) segun frecuencia de uso e impacto.",
            "Activa o pausa entradas al instante guardando una copia previa de seguridad (100% reversible).",
        ],
    },
    {
        "tag": "PASO 7 / 7",
        "tab": 0,
        "title": "Prueba Rapida del Sistema (Equipo Nuevo)",
        "subtitle": "Verificacion segura de solo lectura (~3-5 s) del estado real de este computador.",
        "bullets": [],
    },
]


class QuickTourDialog(QDialog):
    """0px guided tour dialog navigating live tabs and running new-PC system verification."""

    def __init__(
        self,
        policy: SREPolicyEngine,
        vault: QuarantineVault,
        run_async: Callable,
        on_switch_tab: Callable[[int], None],
        on_completed: Callable[[QuickCheckReport | None], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.policy = policy
        self.vault = vault
        self.run_async = run_async
        self.on_switch_tab = on_switch_tab
        self.on_completed = on_completed
        self._step_idx = 0
        self._check_running = False
        self._closed = False
        self._completed_notified = False
        self._last_report: QuickCheckReport | None = None

        self.setWindowTitle("Tour Rapido Guiado y Prueba del Equipo")
        self.setMinimumSize(640, 480)
        pal = get_palette(policy.config.theme_mode)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setPixmap(load_svg_pixmap("winoptiai_logo", size=28))  # v0.6.8: logo del producto
        hdr.addWidget(icon_lbl)
        hdr.addSpacing(8)

        tbox = QVBoxLayout()
        tbox.setSpacing(2)
        self.title_lbl = QLabel("")
        self.title_lbl.setObjectName("PageTitle")
        self.sub_lbl = QLabel("")
        self.sub_lbl.setObjectName("PageSubtitle")
        self.sub_lbl.setWordWrap(True)
        tbox.addWidget(self.title_lbl)
        tbox.addWidget(self.sub_lbl)
        hdr.addLayout(tbox, stretch=1)

        self.step_tag = StatusTag("PASO 1 / 7", "active")
        hdr.addWidget(self.step_tag)
        root.addLayout(hdr)

        # Body panel (switches cleanly between tour bullets and Step 5 diagnostic checklist)
        self.body_panel = GlassPanel()
        bp_outer = QVBoxLayout(self.body_panel)
        bp_outer.setContentsMargins(14, 12, 14, 12)
        bp_outer.setSpacing(8)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        bp_outer.addWidget(self.progress_bar)

        self.check_status_lbl = QLabel("")
        self.check_status_lbl.setObjectName("BodyText")
        self.check_status_lbl.setWordWrap(True)
        self.check_status_lbl.setVisible(False)
        bp_outer.addWidget(self.check_status_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        self._body_host = QWidget()
        self._body_layout = QVBoxLayout(self._body_host)
        self._body_layout.setContentsMargins(2, 2, 2, 2)
        self._body_layout.setSpacing(8)
        scroll.setWidget(self._body_host)
        bp_outer.addWidget(scroll, stretch=1)
        root.addWidget(self.body_panel, stretch=1)

        # Footer controls (FlowLayout -> never clipped at 640px)
        footer = FlowLayout(spacing=8)
        self.prev_btn = QPushButton("Anterior")
        self.prev_btn.setObjectName("GhostAction")
        self.prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_btn.clicked.connect(self._go_prev)
        footer.addWidget(self.prev_btn)

        self.recheck_btn = QPushButton("Ejecutar Prueba Rapida")
        self.recheck_btn.setObjectName("GhostAction")
        self.recheck_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recheck_btn.clicked.connect(self._start_quick_check)
        footer.addWidget(self.recheck_btn)

        self.skip_btn = QPushButton("Omitir Tour")
        self.skip_btn.setObjectName("GhostAction")
        self.skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skip_btn.clicked.connect(self._finish_tour)
        footer.addWidget(self.skip_btn)

        self.next_btn = QPushButton("Siguiente")
        self.next_btn.setObjectName("PrimaryAction")
        set_button_role(self.next_btn, "PrimaryAction")
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.clicked.connect(self._go_next)
        footer.addWidget(self.next_btn)
        root.addLayout(footer)

        self._render_step()

    def _clear_body(self) -> None:
        while self._body_layout.count():
            it = self._body_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.deleteLater()

    def _render_step(self) -> None:
        step = _TOUR_STEPS[self._step_idx]
        self.step_tag.set_tone(str(step["tag"]), "active")
        self.title_lbl.setText(str(step["title"]))
        self.sub_lbl.setText(str(step["subtitle"]))

        tab_idx = int(step["tab"])
        try:
            self.on_switch_tab(tab_idx)
        except Exception:  # noqa: BLE001
            pass

        self.prev_btn.setEnabled(self._step_idx > 0)
        is_last = self._step_idx == len(_TOUR_STEPS) - 1
        self.recheck_btn.setVisible(is_last)
        self.next_btn.setText("Finalizar Tour" if is_last else "Siguiente")

        self._clear_body()
        if not is_last:
            self.progress_bar.setVisible(False)
            self.check_status_lbl.setVisible(False)
            for bullet in step["bullets"]:  # type: ignore[attr-defined]
                row = GlassPanel()
                rl = QVBoxLayout(row)
                rl.setContentsMargins(12, 10, 12, 10)
                lbl = QLabel(f"- {bullet}")
                lbl.setObjectName("BodyText")
                lbl.setWordWrap(True)
                rl.addWidget(lbl)
                self._body_layout.addWidget(row)
            self._body_layout.addStretch()
            return

        # Step 5: render report or auto-run on first entry
        if self._last_report is not None:
            self._render_report(self._last_report)
        elif not self._check_running:
            self._start_quick_check()

    def _go_prev(self) -> None:
        if self._step_idx > 0:
            self._step_idx -= 1
            self._render_step()

    def _go_next(self) -> None:
        if self._step_idx < len(_TOUR_STEPS) - 1:
            self._step_idx += 1
            self._render_step()
        else:
            self._finish_tour()

    def _mark_onboarding_done(self, report: QuickCheckReport | None = None) -> None:
        if not self.policy.config.onboarding_completed:
            self.policy.config.onboarding_completed = True
            self.policy.save_config()
        if not self._completed_notified and self.on_completed is not None and report is not None:
            self._completed_notified = True
            self.on_completed(report)

    def _finish_tour(self) -> None:
        self._closed = True
        self._mark_onboarding_done(self._last_report)
        self.accept()

    def reject(self) -> None:
        self._closed = True
        self._mark_onboarding_done(self._last_report)
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._closed = True
        self._mark_onboarding_done(self._last_report)
        super().closeEvent(event)

    def _ui_alive(self) -> bool:
        return (
            not self._closed
            and qt_is_valid(self)
            and qt_is_valid(self.recheck_btn)
            and qt_is_valid(self.progress_bar)
            and qt_is_valid(self.check_status_lbl)
        )

    def _on_check_progress(self, pct: int, stage: str) -> None:
        if not self._ui_alive() or not self.isVisible():
            return
        self.progress_bar.setValue(max(0, min(100, pct)))
        self.check_status_lbl.setText(f"[{pct}%] {stage}")

    def _start_quick_check(self) -> None:
        if self._check_running or not self._ui_alive():
            return
        self._check_running = True
        self.recheck_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(5)
        self.check_status_lbl.setVisible(True)
        self.check_status_lbl.setText("Ejecutando verificacion segura de hardware, sensores y disco...")

        policy = self.policy
        vault = self.vault
        on_completed = self.on_completed

        def _work(progress_cb=None) -> QuickCheckReport:
            return run_new_pc_quick_check(policy, vault, progress_cb=progress_cb)

        def _done(report: QuickCheckReport) -> None:
            if not self._ui_alive():
                if not self._completed_notified and on_completed is not None:
                    self._completed_notified = True
                    on_completed(report)
                return
            self._check_running = False
            self._last_report = report
            self.recheck_btn.setEnabled(True)
            if self._step_idx == len(_TOUR_STEPS) - 1:
                self._render_report(report)

        def _err(err: str) -> None:
            if not self._ui_alive():
                return
            self._check_running = False
            self.recheck_btn.setEnabled(True)
            self.check_status_lbl.setText(f"Aviso durante prueba rapida: {err}")

        self.run_async(
            _work,
            _done,
            "Prueba rapida del equipo",
            notify_on_complete=False,
            progress_ui_cb=self._on_check_progress,
            on_error=_err,
        )

    def _render_report(self, report: QuickCheckReport) -> None:
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(100)
        self.check_status_lbl.setVisible(True)
        self.check_status_lbl.setText(
            f"Equipo: {report.device_line}  |  Verificado: {report.checked_at}"
        )
        self._clear_body()
        for item in report.items:
            card = GlassPanel()
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 8, 12, 8)
            cl.setSpacing(4)

            top = QHBoxLayout()
            cat_lbl = QLabel(item.category)
            cat_lbl.setObjectName("CardTitle")
            tone = "ok" if item.status == "OK" else ("warn" if item.status == "AVISO" else "neutral")
            tag = StatusTag(item.status, tone)
            top.addWidget(cat_lbl)
            top.addStretch()
            top.addWidget(tag)
            cl.addLayout(top)

            sum_lbl = QLabel(item.summary)
            sum_lbl.setObjectName("BodyText")
            sum_lbl.setWordWrap(True)
            cl.addWidget(sum_lbl)

            if item.recommendation:
                rec_lbl = QLabel(f"Sugerencia: {item.recommendation}")
                rec_lbl.setObjectName("PageSubtitle")
                rec_lbl.setWordWrap(True)
                cl.addWidget(rec_lbl)

            self._body_layout.addWidget(card)
        self._body_layout.addStretch()
