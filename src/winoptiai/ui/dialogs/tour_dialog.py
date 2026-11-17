"""Interactive 5-step guided tour and new-PC quick system verification dialog."""

from __future__ import annotations

from typing import Callable

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
        "tag": "PASO 1 / 5",
        "tab": 0,
        "title": "Resumen, Telemetria y Guardia SRE",
        "subtitle": "Monitoreo ligero de RAM, frecuencia CPU, temperatura y liberacion segura.",
        "bullets": [
            "Graficos locales de las ultimas 24 horas o 7 dias sin saturar el disco (metrics.sqlite).",
            "Guardia SRE automatico: calibra su umbral segun la RAM real del equipo y usa histeresis de 300 s.",
            "AI Boost: compacta RAM inactiva y activa EcoQoS sin tocar nunca tu ventana activa ni tu IDE.",
        ],
    },
    {
        "tag": "PASO 2 / 5",
        "tab": 1,
        "title": "Almacenamiento, OneDrive y Boveda",
        "subtitle": "Limpieza masiva con respaldo en Cuarentena, mapa de carpetas y proteccion de programas.",
        "bullets": [
            "Temporales con Pausa, Guardar Pausa y Reanudacion entre reinicios; casilla 'Seleccionar todo' por listado.",
            "Duplicados BLAKE3 protege instalaciones (AppData, Program Files, .venv, drivers) y re-verifica antes de hardlink.",
            "Cuarentena instantanea (Supr o arrastrar archivos) con Deshacer y auto-purga segura a los 30 dias.",
        ],
    },
    {
        "tag": "PASO 3 / 5",
        "tab": 2,
        "title": "Procesos e IA Agentica",
        "subtitle": "Control en tiempo real del consumo % CPU y workers huerfanos.",
        "bullets": [
            "Medicion real de % CPU por proceso mediante cache de handles psutil.",
            "Deteccion de procesos Node/Python/uv huerfanos cuyo proceso padre ya cerro.",
            "Proteccion estricta para agentes IA, editores de codigo, antivirus y OneDrive.",
        ],
    },
    {
        "tag": "PASO 4 / 5",
        "tab": 3,
        "title": "Termica, BIOS OEM y Salud S.M.A.R.T.",
        "subtitle": "Perfiles energeticos verificados con powercfg /q y diagnostico profundo de disco.",
        "bullets": [
            "Cambia al instante entre Frio/Silencioso, Equilibrado Inteligente o IA Local Maxima (tambien con check en la bandeja).",
            "Lee salud S.M.A.R.T. NVMe/SSD, eventos Disk/Ntfs/WHEA de 14 dias, TPM, BitLocker y HVCI.",
            "Acciones 1-clic con UAC (CHKDSK, DISM/SFC, WinSxS) con guardia previa si Windows tiene reinicio pendiente.",
        ],
    },
    {
        "tag": "PASO 5 / 5",
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
        icon_lbl.setPixmap(load_svg_pixmap("brand", color=pal["text_primary"], size=24))
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

        self.step_tag = StatusTag("PASO 1 / 5", "active")
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
        self.check_status_lbl.setObjectName("MonoValue")
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
                lbl.setObjectName("MonoValue")
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

    def _finish_tour(self) -> None:
        self.policy.config.onboarding_completed = True
        self.policy.save_config()
        if self.on_completed is not None:
            self.on_completed(self._last_report)
        self.accept()

    def _on_check_progress(self, pct: int, stage: str) -> None:
        if not self.isVisible():
            return
        self.progress_bar.setValue(max(0, min(100, pct)))
        self.check_status_lbl.setText(f"[{pct}%] {stage}")

    def _start_quick_check(self) -> None:
        if self._check_running:
            return
        self._check_running = True
        self.recheck_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(5)
        self.check_status_lbl.setVisible(True)
        self.check_status_lbl.setText("Ejecutando verificacion segura de hardware, sensores y disco...")

        def _work(progress_cb=None) -> QuickCheckReport:
            return run_new_pc_quick_check(self.policy, self.vault, progress_cb=progress_cb)

        def _done(report: QuickCheckReport) -> None:
            self._check_running = False
            self._last_report = report
            self.recheck_btn.setEnabled(True)
            if self._step_idx == len(_TOUR_STEPS) - 1:
                self._render_report(report)

        def _err(err: str) -> None:
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
            sum_lbl.setObjectName("MonoValue")
            sum_lbl.setWordWrap(True)
            cl.addWidget(sum_lbl)

            if item.recommendation:
                rec_lbl = QLabel(f"Sugerencia: {item.recommendation}")
                rec_lbl.setObjectName("PageSubtitle")
                rec_lbl.setWordWrap(True)
                cl.addWidget(rec_lbl)

            self._body_layout.addWidget(card)
        self._body_layout.addStretch()
