"""Main Obsidian Acrylic window with fluid two-phase startup and 4 clean views."""

from __future__ import annotations

import psutil
from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..ai_optimizer.process_manager import get_memory_snapshot, run_ai_boost
from ..core.safety_guard import QuarantineVault
from ..core.sre_policy import SREPolicyEngine
from ..core.win32_bridge import apply_obsidian_acrylic
from ..thermal_bios.bios_auditor import run_hardware_bios_audit
from ..thermal_bios.thermal_controller import THERMAL_PROFILES, apply_thermal_profile
from .svg_icons import load_svg_icon, load_svg_pixmap
from .system_tray import WinOptiTray
from .theme import PALETTE
from .views.overview_view import OverviewView
from .views.processes_view import ProcessesView
from .views.storage_view import StorageView
from .views.thermal_bios_view import ThermalBiosView
from .widgets import StatusTag
from .workers import AsyncTask


class MainWindow(QMainWindow):
    """Primary desktop shell engineered for instant first paint and zero visual clutter."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"WinOptiAI {__version__}")
        self.resize(1120, 720)
        self.setMinimumSize(960, 620)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.pool = QThreadPool.globalInstance()
        self._active_workers: list[AsyncTask] = []
        self.vault = QuarantineVault()
        self.policy = SREPolicyEngine()
        self._disk_free_gb = 0.0
        self._disk_total_gb = 0.0
        self._force_quit = False

        # Phase 1: Instant minimal shell construction
        root_canvas = QWidget()
        root_canvas.setObjectName("RootCanvas")
        self.setCentralWidget(root_canvas)

        main_layout = QHBoxLayout(root_canvas)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar (clean monochrome, 0px borders)
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)

        brand_box = QWidget()
        brand_layout = QHBoxLayout(brand_box)
        brand_layout.setContentsMargins(16, 18, 16, 18)
        brand_layout.setSpacing(10)
        brand_icon = QLabel()
        brand_icon.setPixmap(load_svg_pixmap("brand", color="#E2E7ED", size=18))
        brand_layout.addWidget(brand_icon)

        brand_title = QLabel("WinOptiAI")
        brand_title.setStyleSheet("font-size: 14px; font-weight: 600; letter-spacing: 0.2px;")
        brand_layout.addWidget(brand_title)
        brand_layout.addStretch()
        brand_layout.addWidget(StatusTag(f"v{__version__}", "neutral"))
        sb_layout.addWidget(brand_box)

        self.nav_buttons: list[QPushButton] = []
        nav_items = [
            ("overview", "Resumen"),
            ("storage", "Almacenamiento"),
            ("process", "Procesos e IA"),
            ("thermal", "Termica y BIOS"),
        ]
        for idx, (icon_name, label) in enumerate(nav_items):
            btn = QPushButton(f"  {label}")
            btn.setObjectName("NavButton")
            btn.setIcon(load_svg_icon(icon_name, color="#D8E0EA", size=15))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, i=idx: self._switch_tab(i))
            self.nav_buttons.append(btn)
            sb_layout.addWidget(btn)

        sb_layout.addStretch()

        # Quiet bottom status indicator inside sidebar
        footer = QWidget()
        f_layout = QVBoxLayout(footer)
        f_layout.setContentsMargins(16, 12, 16, 14)
        f_layout.setSpacing(6)
        self.status_lbl = QLabel("Sistema listo")
        self.status_lbl.setObjectName("PageSubtitle")
        self.status_lbl.setWordWrap(True)
        f_layout.addWidget(self.status_lbl)
        sb_layout.addWidget(footer)

        main_layout.addWidget(sidebar)

        # Stacked Views
        self.stack = QStackedWidget()
        self.overview_view = OverviewView()
        self.overview_view.trigger_ai_boost.connect(lambda: self._execute_ai_boost("usuario"))
        self.storage_view = StorageView(self.vault, self.policy, self._run_async, self._set_status)
        self.processes_view = ProcessesView(
            self.policy,
            self._run_async,
            lambda: self._execute_ai_boost("usuario"),
            self._set_status,
        )
        self.thermal_view = ThermalBiosView(self.policy, self._run_async, self._set_status)

        self.stack.addWidget(self.overview_view)
        self.stack.addWidget(self.storage_view)
        self.stack.addWidget(self.processes_view)
        self.stack.addWidget(self.thermal_view)
        main_layout.addWidget(self.stack, stretch=1)

        # System Tray
        self.tray = WinOptiTray(
            self,
            on_show=self._restore_from_tray,
            on_boost=lambda: self._execute_ai_boost("usuario"),
            on_thermal=self._tray_thermal,
            on_quit=self._quit_app,
        )
        self.tray.show()

        self._switch_tab(0)

        # Telemetry timer
        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.timeout.connect(self._sample_telemetry)
        self.telemetry_timer.start(2000)

        # Phase 2: Defer heavy hardware & process checks until after first frame paints
        QTimer.singleShot(80, self._phase2_warmup)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_obsidian_acrylic(int(self.winId()))

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._force_quit:
            event.ignore()
            self.hide()
            self.telemetry_timer.setInterval(10000)
            return
        self.telemetry_timer.stop()
        self.tray.hide()
        self.pool.waitForDone(3000)
        event.accept()

    def _restore_from_tray(self) -> None:
        self.telemetry_timer.setInterval(2000)
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _quit_app(self) -> None:
        self._force_quit = True
        QApplication.quit()

    def _switch_tab(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setProperty("active", i == index)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if index == 2:
            self.processes_view.refresh_all()

    def _set_status(self, message: str) -> None:
        self.status_lbl.setText(message)

    def _run_async(self, fn, callback) -> None:
        worker = AsyncTask(fn)
        self._active_workers.append(worker)

        def _cleanup_and_emit(result) -> None:
            if worker in self._active_workers:
                self._active_workers.remove(worker)
            callback(result)

        def _cleanup_on_err(err: str) -> None:
            if worker in self._active_workers:
                self._active_workers.remove(worker)
            self._set_status(f"Aviso: {err}")

        worker.signals.finished.connect(_cleanup_and_emit)
        worker.signals.error.connect(_cleanup_on_err)
        self.pool.start(worker)

    def _phase2_warmup(self) -> None:
        self._refresh_disk_stats()
        self._sample_telemetry()
        self.overview_view.set_audit_rows(self.policy.read_recent_audit())
        self.thermal_view.refresh_audit()

    def _refresh_disk_stats(self) -> None:
        try:
            usage = psutil.disk_usage("C:\\")
            self._disk_free_gb = round(usage.free / (1024**3), 2)
            self._disk_total_gb = round(usage.total / (1024**3), 2)
        except OSError:
            pass

    def _sample_telemetry(self) -> None:
        ram = get_memory_snapshot()
        cpu_pct = psutil.cpu_percent(interval=None)
        if self._disk_total_gb == 0.0:
            self._refresh_disk_stats()

        prof = THERMAL_PROFILES.get(self.policy.config.active_thermal_profile)
        thermal_label = prof.title if prof else "Equilibrado"

        self.overview_view.update_telemetry(
            ram=ram,
            cpu_pct=cpu_pct,
            disk_free_gb=self._disk_free_gb,
            disk_total_gb=self._disk_total_gb,
            sre_active=self.policy.config.auto_ram_relief_enabled,
            threshold_gb=self.policy.config.ram_threshold_gb,
            thermal_label=thermal_label,
        )

        # Evaluate SRE automatic RAM guardrail
        if self.policy.evaluate_ram_pressure(ram["free_gb"]):
            self._execute_ai_boost("sre_auto")

    def _execute_ai_boost(self, actor: str) -> None:
        self.overview_view.boost_btn.setEnabled(False)
        self._set_status("Optimizando Working Set y EcoQoS...")

        def _work() -> dict[str, float | int]:
            return run_ai_boost(
                trim_heavy_apps=True,
                apply_ecoqos=self.policy.config.auto_ecoqos_background_browsers,
            )

        def _done(res: dict[str, float | int]) -> None:
            self.overview_view.boost_btn.setEnabled(True)
            msg = (
                f"RAM libre: {res['free_before_gb']:.2f} -> {res['free_after_gb']:.2f} GB "
                f"(+{res['freed_mb']:.0f} MB, {res['trimmed_processes']} procesos compactados, "
                f"{res['ecoqos_applied']} en EcoQoS)"
            )
            self.policy.record_audit_event(actor, "AI Boost", msg, float(res["freed_mb"]))
            self.overview_view.set_audit_rows(self.policy.read_recent_audit())
            self._set_status(msg)
            self._sample_telemetry()
            if actor == "sre_auto":
                self.tray.showMessage("WinOptiAI Guardia SRE", msg)

        self._run_async(_work, _done)

    def _tray_thermal(self, key: str) -> None:
        ok, msg = apply_thermal_profile(key)
        if ok:
            self.policy.config.active_thermal_profile = key
            self.policy.save_config()
            self.thermal_view._highlight_profile_button(key)
            self.policy.record_audit_event("tray", "Perfil termico", msg)
            self.overview_view.set_audit_rows(self.policy.read_recent_audit())
        self._set_status(msg)
        self.tray.showMessage("WinOptiAI Termica", msg)
