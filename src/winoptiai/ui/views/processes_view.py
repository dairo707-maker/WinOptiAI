"""Processes & Agentic AI view: active app tasks, live OS processes (sortable), EcoQoS, MCP zombies."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...ai_optimizer.process_manager import (
    ProcessEntry,
    ZombieWorker,
    apply_manual_process_ecoqos,
    apply_manual_process_io_priority,
    detect_orphan_ai_workers,
    list_top_processes,
    terminate_zombie_worker,
)
from ...core.i18n import tr
from ...core.sre_policy import SREPolicyEngine
from ...core.usage_telemetry import format_last_used_time
from ..svg_icons import load_svg_icon
from ..context_menu import copy_row_extra, copy_text, install_action_menu
from ...core.help_catalog import TOOLTIPS
from ..widgets import (
    FlowLayout,
    GlassPanel,
    NumericTableItem,
    SectionBenefitStrip,
    StatusTag,
    apply_table_tooltips,
    configure_interactive_columns,
    configure_sortable_table,
)


class ProcessesView(QWidget):
    """Sortable active process monitor, live app task monitor, and SRE toggles."""

    def __init__(
        self,
        policy: SREPolicyEngine,
        run_async: Callable,
        boost_cb: Callable[[], None],
        notify_cb: Callable[[str], None],
        lang: str = "es",
        parent: QWidget | None = None,
        *,
        focus_cb: Callable[[], None] | None = None,
        standby_cb: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.policy = policy
        self.run_async = run_async
        self.boost_cb = boost_cb
        self.notify_cb = notify_cb
        self.focus_cb = focus_cb
        self.standby_cb = standby_cb
        self.lang = lang
        self.zombies: list[ZombieWorker] = []
        self._entries: list[ProcessEntry] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        # Header + 1 primary action
        header = QHBoxLayout()
        tbox = QVBoxLayout()
        tbox.setSpacing(3)
        self.title_lbl = QLabel(tr("proc_title", lang))
        self.title_lbl.setObjectName("PageTitle")
        self.sub_lbl = QLabel(tr("proc_sub", lang))
        self.sub_lbl.setObjectName("PageSubtitle")
        self.sub_lbl.setWordWrap(True)  # v0.5.6: nunca recortado en ventanas angostas
        tbox.addWidget(self.title_lbl)
        tbox.addWidget(self.sub_lbl)
        header.addLayout(tbox, 1)  # v0.5.6: el titulo usa el espacio libre

        self.boost_btn = QPushButton(" Compactar RAM y EcoQoS")
        self.boost_btn.setObjectName("PrimaryAction")
        self.boost_btn.setIcon(load_svg_icon("process", color="#0B0D10", size=14))
        self.boost_btn.setToolTip(TOOLTIPS["proc_boost"])
        self.boost_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boost_btn.clicked.connect(self.boost_cb)
        header.addWidget(self.boost_btn)
        root.addLayout(header)

        self.benefit_strip = SectionBenefitStrip("processes")
        root.addWidget(self.benefit_strip)

        # Active WinOptiAI Tasks + SRE Toggles + Manual Perf Controls (FlowLayout: never clips)
        sre_panel = GlassPanel()
        sre_layout = FlowLayout(sre_panel, spacing=10)
        sre_layout.setContentsMargins(14, 10, 14, 10)

        self.auto_ram_chk = QCheckBox(
            f"Alivio SRE si RAM libre < {self.policy.config.ram_threshold_gb:.1f} GB (5m)"
        )
        self.auto_ram_chk.setChecked(self.policy.config.auto_ram_relief_enabled)
        self.auto_ram_chk.setToolTip(TOOLTIPS["proc_auto_ram"])
        self.auto_ram_chk.toggled.connect(self._save_policy_toggles)
        sre_layout.addWidget(self.auto_ram_chk)

        self.ecoqos_chk = QCheckBox("EcoQoS en segundo plano")
        self.ecoqos_chk.setChecked(self.policy.config.auto_ecoqos_background_browsers)
        self.ecoqos_chk.setToolTip(TOOLTIPS["proc_ecoqos"])
        self.ecoqos_chk.toggled.connect(self._save_policy_toggles)
        sre_layout.addWidget(self.ecoqos_chk)

        self.active_task_tag = StatusTag("0 TAREAS APP", "neutral")
        sre_layout.addWidget(self.active_task_tag)

        self.focus_btn = QPushButton("Modo Enfoque (IA)")
        self.focus_btn.setObjectName("GhostAction")
        self.focus_btn.setCheckable(True)
        self.focus_btn.setToolTip(TOOLTIPS["proc_focus"])
        self.focus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.focus_btn.clicked.connect(lambda: self.focus_cb() if self.focus_cb else None)
        sre_layout.addWidget(self.focus_btn)

        self.standby_btn = QPushButton("Purgar Standby (UAC)")
        self.standby_btn.setObjectName("GhostAction")
        self.standby_btn.setToolTip(TOOLTIPS["proc_standby"])
        self.standby_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.standby_btn.clicked.connect(lambda: self.standby_cb() if self.standby_cb else self._purge_standby_fallback())
        sre_layout.addWidget(self.standby_btn)

        self.manual_eco_btn = QPushButton("EcoQoS Sel.")
        self.manual_eco_btn.setObjectName("GhostAction")
        self.manual_eco_btn.setToolTip(TOOLTIPS["proc_ecoqos_manual"])
        self.manual_eco_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.manual_eco_btn.clicked.connect(self._toggle_selected_ecoqos)
        sre_layout.addWidget(self.manual_eco_btn)

        self.manual_io_btn = QPushButton("E/S Baja Sel.")
        self.manual_io_btn.setObjectName("GhostAction")
        self.manual_io_btn.setToolTip(TOOLTIPS["proc_iolow_manual"])
        self.manual_io_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.manual_io_btn.clicked.connect(self._toggle_selected_io_low)
        sre_layout.addWidget(self.manual_io_btn)

        self.refresh_btn = QPushButton("Actualizar")
        self.refresh_btn.setObjectName("GhostAction")
        self.refresh_btn.setToolTip(TOOLTIPS["proc_refresh"])
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.refresh_all)
        sre_layout.addWidget(self.refresh_btn)
        root.addWidget(sre_panel)

        # Active top processes table (sortable by PID, Name, Class, CPU%, E/S MB/s, RAM, EcoQoS/IO, Last Used)
        self.proc_table = QTableWidget(0, 8)
        self.proc_table.setHorizontalHeaderLabels(
            ["PID", "PROCESO", "CLASIFICACION", "CPU (%)", "E/S MB/s", "RAM (MB)", "ECOQOS / E/S", "ULTIMO USO"]
        )
        configure_sortable_table(self.proc_table)
        configure_interactive_columns(
            self.proc_table,
            [78, 220, 155, 86, 102, 100, 132, 128],
            policy=self.policy,
            storage_key="proc_table",
        )
        self.proc_table.setMinimumHeight(170)  # v0.6.9: nunca aplastada por el panel inferior
        root.addWidget(self.proc_table, stretch=3)

        # Orphan AI / MCP workers panel
        z_panel = GlassPanel()
        z_layout = QVBoxLayout(z_panel)
        z_layout.setContentsMargins(14, 12, 14, 12)
        z_layout.setSpacing(8)

        z_hdr = QHBoxLayout()
        z_lbl = QLabel("CAZADOR DE WORKERS MCP / NODE / PYTHON HUERFANOS")
        z_lbl.setObjectName("SectionLabel")
        z_hdr.addWidget(z_lbl)
        z_hdr.addStretch()
        self.zombie_tag = StatusTag("0 DETECTADOS", "neutral")
        z_hdr.addWidget(self.zombie_tag)
        self.kill_zombie_btn = QPushButton("Cerrar Zombi Seleccionado")
        self.kill_zombie_btn.setObjectName("RiskAction")  # v0.5.6: cierra procesos
        self.kill_zombie_btn.setToolTip(TOOLTIPS["proc_kill_zombie"])
        self.kill_zombie_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.kill_zombie_btn.clicked.connect(self._kill_selected_zombie)
        z_hdr.addWidget(self.kill_zombie_btn)
        # v0.6.9: pestanas "Apps en segundo plano" (como Android) + cazador de workers IA
        self.bottom_tabs = QTabWidget()
        self.bottom_tabs.setDocumentMode(True)
        bg_page = QWidget()
        bg_l = QVBoxLayout(bg_page)
        bg_l.setContentsMargins(0, 8, 0, 0)
        bg_l.setSpacing(8)
        bg_hdr = QHBoxLayout()
        bg_hint = QLabel("Programas sin ventana que gastan memoria o CPU. Puedes cerrarlos sin perder trabajo.")
        bg_hint.setObjectName("Caption")
        bg_hint.setWordWrap(True)
        bg_hdr.addWidget(bg_hint, stretch=1)
        self.bg_tag = StatusTag("SIN REVISAR", "neutral")
        bg_hdr.addWidget(self.bg_tag)
        self.bg_scan_btn = QPushButton("Buscar")
        self.bg_scan_btn.setObjectName("GhostAction")
        self.bg_scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bg_scan_btn.clicked.connect(self.refresh_background_apps)
        bg_hdr.addWidget(self.bg_scan_btn)
        self.bg_close_btn = QPushButton("Cerrar seleccionadas")
        self.bg_close_btn.setObjectName("RiskAction")
        self.bg_close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bg_close_btn.clicked.connect(self._close_selected_bg_apps)
        bg_hdr.addWidget(self.bg_close_btn)
        bg_l.addLayout(bg_hdr)
        self.bg_table = QTableWidget(0, 5)
        self.bg_table.setHorizontalHeaderLabels(["APP", "PROCESOS", "RAM (MB)", "CPU %", "AL CERRAR"])
        configure_sortable_table(self.bg_table)
        self.bg_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        configure_interactive_columns(self.bg_table, [300, 92, 100, 80, 380], policy=self.policy, storage_key="bg_apps_table")
        self.bg_table.setMinimumHeight(70)
        bg_l.addWidget(self.bg_table)
        self.bg_apps: list = []
        install_action_menu(self.bg_table, extras=self._bg_menu_extras)

        zombie_page = QWidget()
        zl = QVBoxLayout(zombie_page)
        zl.setContentsMargins(0, 8, 0, 0)
        zl.setSpacing(8)
        zl.addLayout(z_hdr)

        self.zombie_table = QTableWidget(0, 4)
        self.zombie_table.setHorizontalHeaderLabels(["PID", "PROCESO", "RAM (MB)", "COMANDO"])
        configure_sortable_table(self.zombie_table)
        configure_interactive_columns(
            self.zombie_table,
            [78, 180, 105, 500],
            policy=self.policy,
            storage_key="zombie_table",
        )
        self.zombie_table.setMinimumHeight(70)
        zl.addWidget(self.zombie_table)
        self.bottom_tabs.addTab(bg_page, "Apps en segundo plano")
        self.bottom_tabs.addTab(zombie_page, "Workers IA huerfanos")
        z_layout.addWidget(self.bottom_tabs)
        # v0.6.5: clic derecho = mismas acciones del apartado
        install_action_menu(self.proc_table, extras=lambda: self._proc_menu_extras(self.proc_table))
        install_action_menu(
            self.zombie_table,
            row_buttons=[self.kill_zombie_btn],
            extras=lambda: self._proc_menu_extras(self.zombie_table),
        )
        root.addWidget(z_panel, stretch=2)

    def apply_language_and_theme(self, lang: str, icon_inverted: str) -> None:
        self.lang = lang
        self.title_lbl.setText(tr("proc_title", lang))
        self.sub_lbl.setText(tr("proc_sub", lang))
        self.boost_btn.setIcon(load_svg_icon("process", color=icon_inverted, size=14))

    def set_active_tasks(self, task_names: list[str]) -> None:
        if task_names:
            self.active_task_tag.set_tone(f"{len(task_names)} ACTIVAS", "active")  # v0.5.6: sin texto cortado
            self.active_task_tag.setToolTip("\n".join(task_names))
        else:
            self.active_task_tag.set_tone("0 TAREAS APP", "neutral")

    def _save_policy_toggles(self) -> None:
        self.policy.config.auto_ram_relief_enabled = self.auto_ram_chk.isChecked()
        self.policy.config.auto_ecoqos_background_browsers = self.ecoqos_chk.isChecked()
        self.policy.save_config()

    def refresh_all(self) -> None:
        self.run_async(lambda: list_top_processes(45), self._render_processes, "Escaneo procesos")
        self.run_async(detect_orphan_ai_workers, self._render_zombies, "Cazador MCP")
        self.refresh_background_apps()

    # ------------------------------------------------------------------ v0.6.9: segundo plano
    def refresh_background_apps(self) -> None:
        from ...ai_optimizer.background_apps import list_closable_background_apps

        self.bg_scan_btn.setEnabled(False)

        def _err(_e: str) -> None:
            self.bg_scan_btn.setEnabled(True)

        self.run_async(list_closable_background_apps, self._render_bg_apps, "Apps en segundo plano",
                       notify_on_complete=False, on_error=_err)

    def _render_bg_apps(self, apps: list) -> None:
        from ...ai_optimizer.background_apps import caution_note

        self.bg_scan_btn.setEnabled(True)
        self.bg_apps = list(apps)
        total = sum(a.ram_mb for a in apps)
        self.bg_tag.set_tone(f"{len(apps)} APPS · {total:.0f} MB" if apps else "NADA QUE CERRAR", "warn" if apps else "ok")
        self.bg_table.setSortingEnabled(False)
        self.bg_table.setRowCount(len(apps))
        for r, a in enumerate(apps):
            name_item = QTableWidgetItem(a.display)
            name_item.setData(Qt.ItemDataRole.UserRole + 1, r)
            name_item.setToolTip(a.exe or a.display)
            self.bg_table.setItem(r, 0, name_item)
            self.bg_table.setItem(r, 1, NumericTableItem(str(len(a.pids)), len(a.pids)))
            self.bg_table.setItem(r, 2, NumericTableItem(f"{a.ram_mb:.0f}", a.ram_mb))
            self.bg_table.setItem(r, 3, NumericTableItem(f"{a.cpu_pct:.1f}", a.cpu_pct))
            self.bg_table.setItem(r, 4, QTableWidgetItem(caution_note(a.name)))
        apply_table_tooltips(self.bg_table)
        self.bg_table.setSortingEnabled(True)

    def _selected_bg_apps(self) -> list:
        rows = sorted({i.row() for i in self.bg_table.selectedIndexes()})
        out = []
        for r in rows:
            it = self.bg_table.item(r, 0)
            idx = it.data(Qt.ItemDataRole.UserRole + 1) if it else None
            if isinstance(idx, int) and 0 <= idx < len(self.bg_apps):
                out.append(self.bg_apps[idx])
        return out

    def _bg_menu_extras(self):
        from ...core.win32_bridge import reveal_in_explorer

        sel = self._selected_bg_apps()
        if not sel:
            return []
        first = sel[0]
        label = f"Cerrar {first.display}" if len(sel) == 1 else f"Cerrar {len(sel)} apps"
        return [
            (label, self._close_selected_bg_apps, True),
            None,
            ("Abrir ubicacion del archivo", lambda: reveal_in_explorer(first.exe), len(sel) == 1 and bool(first.exe)),
            ("Copiar nombre", lambda: copy_text(", ".join(a.display for a in sel)), True),
        ]

    def _close_selected_bg_apps(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        from ...ai_optimizer.background_apps import caution_note, close_background_app

        sel = self._selected_bg_apps()
        if not sel:
            self.notify_cb("Selecciona una o varias apps de la lista (Ctrl o Mayus para varias).")
            return
        lines = "\n".join(f"- {a.display} (~{a.ram_mb:.0f} MB): {caution_note(a.name)}" for a in sel[:8])
        ans = QMessageBox.question(self, "Cerrar apps en segundo plano", f"Se cerraran:\n\n{lines}\n\nContinuar?")
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.bg_close_btn.setEnabled(False)

        def _work(subtask_cb=None):
            res = []
            for a in sel:
                if subtask_cb:
                    subtask_cb(a.name, label=a.display, state="running", pct=30)
                ok, msg = close_background_app(a)
                if subtask_cb:
                    subtask_cb(a.name, state="ok" if ok else "error", detail=msg)
                res.append((a, ok, msg))
            return res

        def _done(res) -> None:
            self.bg_close_btn.setEnabled(True)
            ok_n = sum(1 for _a, ok, _m in res if ok)
            freed = sum(a.ram_mb for a, ok, _m in res if ok)
            for _a, ok, m in res:
                self.policy.record_audit_event("usuario", "Cerrar app en segundo plano" if ok else "Cerrar app (fallo)", m)
            self.notify_cb(f"{ok_n} de {len(res)} app(s) cerradas · ~{freed:.0f} MB liberados.")
            self.refresh_background_apps()

        def _err(_e: str) -> None:
            self.bg_close_btn.setEnabled(True)

        self.run_async(_work, _done, "Cerrar apps en segundo plano", notify_on_complete=False, on_error=_err)

    def set_focus_mode_active(self, active: bool) -> None:
        self.focus_btn.blockSignals(True)
        self.focus_btn.setChecked(bool(active))
        self.focus_btn.setText("Enfoque: ON (Revertir)" if active else "Modo Enfoque (IA)")
        self.focus_btn.setProperty("selected", bool(active))
        self.focus_btn.style().unpolish(self.focus_btn)
        self.focus_btn.style().polish(self.focus_btn)
        self.focus_btn.blockSignals(False)

    def _purge_standby_fallback(self) -> None:
        from ...core.win32_bridge import purge_standby_memory_list

        self.standby_btn.setEnabled(False)
        self.run_async(
            lambda: purge_standby_memory_list(allow_uac=True),
            lambda res: (self.standby_btn.setEnabled(True), self.notify_cb(res[1])),
            "Purgar Standby RAM",
            notify_on_complete=False,
            on_error=lambda _e: self.standby_btn.setEnabled(True),
        )

    def _selected_entry(self) -> ProcessEntry | None:
        r = self.proc_table.currentRow()
        if r < 0:
            return None
        it = self.proc_table.item(r, 0)
        if it is None:
            return None
        try:
            pid = int(it.text())
        except ValueError:
            return None
        return next((e for e in self._entries if e.pid == pid), None)

    def _toggle_selected_ecoqos(self) -> None:
        ent = self._selected_entry()
        if ent is None:
            self.notify_cb("Selecciona un proceso en la tabla primero.")
            return
        ok, msg = apply_manual_process_ecoqos(ent.pid, ent.name, not ent.ecoqos_active)
        self.notify_cb(msg)
        if ok:
            self.refresh_all()

    def _toggle_selected_io_low(self) -> None:
        ent = self._selected_entry()
        if ent is None:
            self.notify_cb("Selecciona un proceso en la tabla primero.")
            return
        ok, msg = apply_manual_process_io_priority(ent.pid, ent.name, not ent.io_low)
        self.notify_cb(msg)
        if ok:
            self.refresh_all()

    def _render_processes(self, entries: list[ProcessEntry]) -> None:
        self._entries = list(entries)
        self.proc_table.setSortingEnabled(False)
        self.proc_table.setRowCount(len(entries))
        for r, item in enumerate(entries):
            ts = float(getattr(item, "started_ts", 0.0))
            self.proc_table.setItem(r, 0, NumericTableItem(str(item.pid), item.pid))
            self.proc_table.setItem(r, 1, QTableWidgetItem(item.name))
            self.proc_table.setItem(r, 2, QTableWidgetItem(item.role))
            self.proc_table.setItem(r, 3, NumericTableItem(f"{item.cpu_pct:.1f}", item.cpu_pct))
            io_rate = float(getattr(item, "io_mb_s", 0.0))
            self.proc_table.setItem(r, 4, NumericTableItem(f"{io_rate:.2f}", io_rate))
            self.proc_table.setItem(r, 5, NumericTableItem(f"{item.ram_mb:.1f}", item.ram_mb))
            if not item.ecoqos_eligible:
                st_txt = "PROTEGIDO"
            elif item.ecoqos_active and item.io_low:
                st_txt = "ECO + I/O BAJA"
            elif item.ecoqos_active:
                st_txt = "ECO ACTIVO"
            elif item.io_low:
                st_txt = "E/S BAJA"
            else:
                st_txt = "ELEGIBLE"
            self.proc_table.setItem(r, 6, QTableWidgetItem(st_txt))
            self.proc_table.setItem(r, 7, NumericTableItem(format_last_used_time(ts), ts))
        apply_table_tooltips(self.proc_table)
        self.proc_table.setSortingEnabled(True)

    def _render_zombies(self, items: list[ZombieWorker]) -> None:
        self.zombies = items
        self.zombie_table.setSortingEnabled(False)
        self.zombie_table.setRowCount(len(items))
        self.zombie_tag.set_tone(f"{len(items)} DETECTADOS", "warn" if items else "ok")
        for r, z in enumerate(items):
            pid_item = NumericTableItem(str(z.pid), z.pid)
            pid_item.setData(Qt.ItemDataRole.UserRole + 1, r)
            self.zombie_table.setItem(r, 0, pid_item)
            self.zombie_table.setItem(r, 1, QTableWidgetItem(z.name))
            self.zombie_table.setItem(r, 2, NumericTableItem(f"{z.ram_mb:.1f}", z.ram_mb))
            self.zombie_table.setItem(r, 3, QTableWidgetItem(z.cmdline))
        apply_table_tooltips(self.zombie_table)
        self.zombie_table.setSortingEnabled(True)

    def _proc_menu_extras(self, table):
        from ...core.win32_bridge import reveal_in_explorer

        r = table.currentRow()
        pid_item = table.item(r, 0) if r >= 0 else None
        name_item = table.item(r, 1) if r >= 0 else None
        if pid_item is None:
            return []
        exe = ""
        try:
            import psutil

            exe = psutil.Process(int(pid_item.text())).exe()
        except Exception:  # noqa: BLE001 - proceso cerrado o sin permiso
            exe = ""
        extras_list: list = []
        if table is self.proc_table:
            ent = self._selected_entry()
            if ent is not None and ent.ecoqos_eligible:
                extras_list.append((
                    "Quitar EcoQoS" if ent.ecoqos_active else "Aplicar EcoQoS",
                    self._toggle_selected_ecoqos,
                    True,
                ))
                extras_list.append((
                    "Prioridad E/S Normal" if ent.io_low else "Prioridad E/S Baja",
                    self._toggle_selected_io_low,
                    True,
                ))
        extras_list.extend([
            ("Abrir ubicacion del archivo", lambda: reveal_in_explorer(exe), bool(exe)),
            ("Copiar nombre", lambda: copy_text(name_item.text() if name_item else ""), name_item is not None),
            ("Copiar PID", lambda: copy_text(pid_item.text()), True),
            copy_row_extra(table),
        ])
        return extras_list

    def _kill_selected_zombie(self) -> None:
        rows = sorted({idx.row() for idx in self.zombie_table.selectedIndexes()})
        if not rows:
            self.notify_cb("Seleccione un worker huerfano en la tabla inferior.")
            return
        item0 = self.zombie_table.item(rows[0], 0)
        if item0 is None:
            return
        orig_idx = item0.data(Qt.ItemDataRole.UserRole + 1)
        if orig_idx is None or orig_idx >= len(self.zombies):
            return
        target = self.zombies[orig_idx]
        ok, msg = terminate_zombie_worker(target.pid)
        if ok:
            self.policy.record_audit_event("usuario", "Cierre worker MCP", msg, target.ram_mb)
        self.notify_cb(msg)
        self.refresh_all()
