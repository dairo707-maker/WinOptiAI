"""Smart Windows Startup Apps view: usage-based semaphore suggestions & 100% reversible toggling."""

from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...apps.startup_manager import StartupItem, scan_startup_items, set_startup_item_enabled
from ...core.help_catalog import TOOLTIPS
from ...core.i18n import tr
from ...core.safety_guard import PreOpBackupManager
from ...core.sre_policy import SREPolicyEngine
from ...core.usage_telemetry import format_last_used
from ..svg_icons import load_svg_icon
from ..context_menu import copy_row_extra, copy_text, install_action_menu
from ..widgets import (
    ROLE_MOVE,
    ROLE_RESTORE,
    FlowLayout,
    GlassPanel,
    NumericTableItem,
    SectionBenefitStrip,
    SemaphoreDot,
    apply_table_tooltips,
    configure_interactive_columns,
    configure_sortable_table,
    semaphore_hex,
    set_button_role,
)


class StartupView(QWidget):
    """Analyze Windows startup items with smart semaphore advice and reversible disable/enable."""

    summary_changed = Signal(str, str)  # (semaphore_text, tone)

    def __init__(
        self,
        backup_mgr: PreOpBackupManager,
        policy: SREPolicyEngine,
        run_async: Callable,
        notify_cb: Callable[[str], None],
        lang: str = "es",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.backup_mgr = backup_mgr
        self.policy = policy
        self.run_async = run_async
        self.notify_cb = notify_cb
        self.lang = lang
        self.items: list[StartupItem] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(10)

        header = QHBoxLayout()
        tbox = QVBoxLayout()
        tbox.setSpacing(2)
        self.title_lbl = QLabel(tr("startup_title", lang))
        self.title_lbl.setObjectName("PageTitle")
        self.sub_lbl = QLabel(tr("startup_sub", lang))
        self.sub_lbl.setObjectName("PageSubtitle")
        self.sub_lbl.setWordWrap(True)
        tbox.addWidget(self.title_lbl)
        tbox.addWidget(self.sub_lbl)
        header.addLayout(tbox, stretch=1)

        self.scan_btn = QPushButton(" Analizar Inicio")
        self.scan_btn.setObjectName("PrimaryAction")
        self.scan_btn.setIcon(load_svg_icon("startup", color="#0A0F1D", size=14))
        self.scan_btn.setToolTip(TOOLTIPS["startup_scan"])
        self.scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_btn.clicked.connect(self.refresh_startup)
        header.addWidget(self.scan_btn)
        root.addLayout(header)

        self.benefit_strip = SectionBenefitStrip("startup")
        root.addWidget(self.benefit_strip)

        actions = FlowLayout(spacing=6)
        self.smart_btn = QPushButton("Aplicar Sugerencias Seguras")
        set_button_role(self.smart_btn, ROLE_MOVE)
        self.smart_btn.setToolTip(TOOLTIPS["startup_apply_smart"])
        self.smart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.smart_btn.clicked.connect(self._on_apply_smart)
        actions.addWidget(self.smart_btn)

        self.disable_btn = QPushButton("Desactivar")
        set_button_role(self.disable_btn, ROLE_MOVE)
        self.disable_btn.setToolTip(TOOLTIPS["startup_disable"])
        self.disable_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.disable_btn.clicked.connect(lambda: self._toggle_selected(False))
        actions.addWidget(self.disable_btn)

        self.enable_btn = QPushButton("Reactivar")
        set_button_role(self.enable_btn, ROLE_RESTORE)
        self.enable_btn.setToolTip(TOOLTIPS["startup_enable"])
        self.enable_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.enable_btn.clicked.connect(lambda: self._toggle_selected(True))
        actions.addWidget(self.enable_btn)

        self.filter_combo = QComboBox()
        self.filter_combo.addItem("Todas", "all")
        self.filter_combo.addItem("Activas al inicio", "enabled")
        self.filter_combo.addItem("Sugeridas: Desactivar", "DESACTIVAR")
        self.filter_combo.addItem("Sugeridas: Pausar", "PAUSAR")
        self.filter_combo.currentIndexChanged.connect(lambda _i: self._render_items())
        actions.addWidget(self.filter_combo)
        root.addLayout(actions)

        summary = GlassPanel()
        sl = QHBoxLayout(summary)
        sl.setContentsMargins(12, 8, 12, 8)
        sl.setSpacing(8)
        self.sem_dot = SemaphoreDot("neutral", self.policy.config.theme_mode)
        sl.addWidget(self.sem_dot)
        self.summary_lbl = QLabel("Haz clic en 'Analizar Inicio' para evaluar programas de arranque.")
        self.summary_lbl.setObjectName("BodyText")
        self.summary_lbl.setWordWrap(True)
        sl.addWidget(self.summary_lbl, stretch=1)
        root.addWidget(summary)

        self.startup_table = QTableWidget(0, 7)
        self.startup_table.setHorizontalHeaderLabels(
            ["SEMAFORO", "APLICACION", "ESTADO", "ORIGEN", "RAM EST.", "ULTIMO USO", "MOTIVO INTELIGENTE"]
        )
        configure_sortable_table(self.startup_table)
        self.startup_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        configure_interactive_columns(
            self.startup_table,
            [115, 220, 100, 120, 96, 122, 340],
            policy=self.policy,
            storage_key="startup_table",
        )
        root.addWidget(self.startup_table, stretch=1)
        # v0.6.5: clic derecho = mismas acciones del apartado
        install_action_menu(self.startup_table, extras=self._row_menu_extras)

    def apply_language_and_theme(self, lang: str, icon_inverted: str, theme_mode: str = "dark") -> None:
        self.lang = lang
        self.title_lbl.setText(tr("startup_title", lang))
        self.sub_lbl.setText(tr("startup_sub", lang))
        self.scan_btn.setIcon(load_svg_icon("startup", color=icon_inverted, size=14))
        self.sem_dot.set_tone(self.sem_dot._tone, theme_mode)
        self._render_items()

    def refresh_startup(self) -> None:
        self.scan_btn.setEnabled(False)
        self.summary_lbl.setText("Analizando entradas de inicio y frecuencia real de uso...")

        def _done(items: list[StartupItem]) -> None:
            self.scan_btn.setEnabled(True)
            self.items = items
            self._render_items()

        self.run_async(
            scan_startup_items,
            _done,
            "Analisis inicio Windows",
            notify_on_complete=False,
            on_error=lambda _e: self.scan_btn.setEnabled(True),
        )

    def _row_menu_extras(self):
        items = self._selected_items()
        if not items:
            return []
        it = items[0]
        single = len(items) == 1
        n_on = sum(1 for i in items if i.enabled)
        n_off = len(items) - n_on
        return [
            ("Desactivar" if n_on <= 1 else f"Desactivar {n_on}", lambda: self._toggle_selected(False),
             n_on > 0 and self.disable_btn.isEnabled()),
            ("Reactivar" if n_off <= 1 else f"Reactivar {n_off}", lambda: self._toggle_selected(True),
             n_off > 0 and self.enable_btn.isEnabled()),
            ("Copiar comando", lambda: copy_text(it.command), single and bool(it.command)),
            copy_row_extra(self.startup_table) if single else None,
        ]

    def _selected_items(self) -> list[StartupItem]:
        rows = sorted({idx.row() for idx in self.startup_table.selectedIndexes()})
        out: list[StartupItem] = []
        for r in rows:
            it = self.startup_table.item(r, 0)
            orig = it.data(Qt.ItemDataRole.UserRole + 1) if it is not None else None
            if isinstance(orig, int) and 0 <= orig < len(self.items):
                out.append(self.items[orig])
        return out

    def _toggle_selected(self, enable: bool) -> None:
        targets = self._selected_items()
        if not targets:
            self.notify_cb("Selecciona una o mas entradas de inicio en la tabla.")
            return
        self._apply_toggle_batch(targets, enable)

    def _on_apply_smart(self) -> None:
        targets = [it for it in self.items if it.enabled and it.recommendation == "DESACTIVAR" and not it.protected]
        if not targets:
            self.notify_cb("No hay entradas activas recomendadas para desactivar.")
            return
        ram_sum = sum(t.ram_mb for t in targets)
        preview = "\n".join(f"- {t.name}: {t.reason}" for t in targets[:8])
        if len(targets) > 8:
            preview += f"\n... (+{len(targets) - 8} mas)"
        reply = QMessageBox.question(
            self,
            "Aplicar Sugerencias Seguras",
            f"Se desactivaran de forma 100% reversible {len(targets)} entradas (~{ram_sum:.0f} MB RAM):\n\n"
            f"{preview}\n\nDeseas continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._apply_toggle_batch(targets, False)

    def _apply_toggle_batch(self, targets: list[StartupItem], enable: bool) -> None:
        ok_cnt = 0
        last_msg = ""
        for it in targets:
            ok, msg = set_startup_item_enabled(it, enable, backup_mgr=self.backup_mgr)
            last_msg = msg
            if ok:
                ok_cnt += 1
        if ok_cnt > 0:
            action = "Reactivar Inicio" if enable else "Desactivar Inicio"
            self.policy.record_audit_event("usuario", action, f"{ok_cnt} entrada(s) actualizadas")
        self.notify_cb(last_msg if len(targets) == 1 else f"{ok_cnt} de {len(targets)} entradas actualizadas.")
        self._render_items()

    def _render_items(self) -> None:
        now = time.time()
        mode = self.policy.config.theme_mode
        flt = str(self.filter_combo.currentData() or "all")

        visible: list[tuple[int, StartupItem]] = []
        active_cnt = 0
        disable_sug = 0
        active_ram = 0.0
        for idx, it in enumerate(self.items):
            if it.enabled:
                active_cnt += 1
                active_ram += it.ram_mb
                if it.recommendation == "DESACTIVAR" and not it.protected:
                    disable_sug += 1
            if flt == "enabled" and not it.enabled:
                continue
            if flt in ("DESACTIVAR", "PAUSAR") and it.recommendation != flt:
                continue
            visible.append((idx, it))

        self.startup_table.setSortingEnabled(False)
        self.startup_table.setRowCount(len(visible))
        for r, (orig_idx, it) in enumerate(visible):
            c0 = QTableWidgetItem(it.recommendation)
            c0.setData(Qt.ItemDataRole.UserRole + 1, orig_idx)
            c0.setForeground(QColor(semaphore_hex(it.rec_tone, mode)))
            self.startup_table.setItem(r, 0, c0)
            self.startup_table.setItem(r, 1, QTableWidgetItem(it.name))

            st_txt = "ACTIVA" if it.enabled else "PAUSADA"
            st_item = QTableWidgetItem(st_txt)
            st_item.setForeground(QColor(semaphore_hex("ok" if it.enabled else "neutral", mode)))
            self.startup_table.setItem(r, 2, st_item)

            self.startup_table.setItem(r, 3, QTableWidgetItem(it.scope))
            self.startup_table.setItem(
                r, 4, NumericTableItem(f"{it.ram_mb:.0f} MB" if it.ram_mb > 0 else "--", it.ram_mb)
            )
            self.startup_table.setItem(r, 5, NumericTableItem(format_last_used(it.last_used_ts, now), it.last_used_ts))
            r_it = QTableWidgetItem(it.reason)
            r_it.setToolTip(f"{it.reason}\nComando: {it.command}")
            self.startup_table.setItem(r, 6, r_it)
        apply_table_tooltips(self.startup_table)
        self.startup_table.setSortingEnabled(True)

        if self.items:
            self.summary_lbl.setText(
                f"Activas al inicio: {active_cnt} de {len(self.items)}  |  "
                f"RAM activa: {active_ram:.0f} MB  |  Desactivar sugerido: {disable_sug}"
            )
            sem_tone = "risk" if disable_sug >= 3 else ("warn" if disable_sug >= 1 else "ok")
            sem_txt = f"{disable_sug} opt." if disable_sug > 0 else "Limpio"
            self.sem_dot.set_tone(sem_tone, mode)
            self.summary_changed.emit(sem_txt, sem_tone)
        else:
            self.sem_dot.set_tone("neutral", mode)
