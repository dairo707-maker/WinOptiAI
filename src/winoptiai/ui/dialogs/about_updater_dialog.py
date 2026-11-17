"""About & Self-Updater dialog with active-task warning, download % bar, and detached launch."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ... import __version__
from ...core.i18n import tr
from ...core.updater import (
    REPO_WEB_URL,
    ReleaseInfo,
    check_for_updates,
    download_and_launch_update,
)
from ..svg_icons import load_svg_pixmap
from ..theme import get_palette
from ..widgets import FlowLayout, GlassPanel, StatusTag
from ..workers import AsyncTask


class AboutUpdaterDialog(QDialog):
    """0px architectural About dialog with Dairo's credits, active-task check, and % updater."""

    def __init__(
        self,
        lang: str,
        theme_mode: str,
        run_async: Callable,
        hardware_summary: str,
        active_tasks_fn: Callable[[], list[AsyncTask]] | None = None,
        parent: QWidget | None = None,
        on_open_diagnostics: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.lang = lang
        self.theme_mode = theme_mode
        self.run_async = run_async
        self.active_tasks_fn = active_tasks_fn
        self.latest_release: ReleaseInfo | None = None

        self.setWindowTitle(tr("about_title", lang))
        # v0.5.6: tamano minimo (no fijo) para que los botones nunca se recorten con escalado de Windows
        self.setMinimumSize(570, 470)

        p = get_palette(theme_mode)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(load_svg_pixmap("brand", color=p["text_primary"], size=26))
        hdr.addWidget(icon)
        hdr.addSpacing(8)

        tbox = QVBoxLayout()
        tbox.setSpacing(2)
        title = QLabel(f"WinOptiAI v{__version__}")
        title.setObjectName("PageTitle")
        author = QLabel(tr("about_author", lang))
        author.setObjectName("PageSubtitle")
        tbox.addWidget(title)
        tbox.addWidget(author)
        hdr.addLayout(tbox)
        hdr.addStretch()
        self.version_tag = StatusTag(f"V{__version__}", "active")
        hdr.addWidget(self.version_tag)
        root.addLayout(hdr)

        # Info & Credits Card
        info_panel = GlassPanel()
        il = QVBoxLayout(info_panel)
        il.setContentsMargins(14, 12, 14, 12)
        il.setSpacing(6)
        meta = QLabel(
            f"Autor / Creador: Dairo (dairo707-maker)\n"
            f"Licencia: MIT Open Source\n"
            f"Repositorio: {REPO_WEB_URL}\n"
            f"Perfil detectado: {hardware_summary or 'Analizando equipo...'}"
        )
        meta.setObjectName("MonoValue")
        meta.setWordWrap(True)
        il.addWidget(meta)
        root.addWidget(info_panel)

        # Release notes / Update status + Progress bar
        self.status_lbl = QLabel("Pulse 'Buscar Actualizaciones' para consultar GitHub Releases.")
        self.status_lbl.setObjectName("PageSubtitle")
        root.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        self.notes_box = QPlainTextEdit()
        self.notes_box.setReadOnly(True)
        self.notes_box.setPlaceholderText("Notas de la ultima version disponible en GitHub...")
        root.addWidget(self.notes_box, stretch=1)

        # Actions row (v0.5.6: FlowLayout -> pasan a otra fila en vez de recortarse)
        actions = FlowLayout(spacing=8)
        repo_btn = QPushButton("Abrir GitHub")
        repo_btn.setObjectName("GhostAction")
        repo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        repo_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_WEB_URL)))
        actions.addWidget(repo_btn)

        if on_open_diagnostics is not None:
            diag_btn = QPushButton("Diagnostico")
            diag_btn.setObjectName("GhostAction")
            diag_btn.setToolTip("Ver o copiar crash.log y cierres inesperados detectados")
            diag_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            diag_btn.clicked.connect(on_open_diagnostics)
            actions.addWidget(diag_btn)

        self.check_btn = QPushButton(tr("about_check_updates", lang))
        self.check_btn.setObjectName("GhostAction")
        self.check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_btn.clicked.connect(self._on_check)
        actions.addWidget(self.check_btn)

        self.install_btn = QPushButton(tr("about_install_update", lang))
        self.install_btn.setObjectName("PrimaryAction")
        self.install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_btn.setVisible(False)
        self.install_btn.clicked.connect(self._on_install_update)
        actions.addWidget(self.install_btn)
        root.addLayout(actions)

    def _on_check(self) -> None:
        self.check_btn.setEnabled(False)
        self.status_lbl.setText("Consultando GitHub Releases...")
        self.run_async(lambda: check_for_updates(__version__), self._on_check_done, "Buscar actualizacion")

    def _on_check_done(self, result: tuple[bool, ReleaseInfo | None, str]) -> None:
        self.check_btn.setEnabled(True)
        ok, info, msg = result
        self.status_lbl.setText(msg)
        if not ok or info is None:
            return

        self.latest_release = info
        self.notes_box.setPlainText(f"Release {info.tag} ({info.html_url})\n\n{info.notes}")
        if info.update_available:
            self.version_tag.set_tone(f"NUEVA {info.tag}", "ok")
            self.install_btn.setVisible(bool(info.setup_url))
        else:
            self.version_tag.set_tone(f"AL DIA {info.tag}", "active")
            self.install_btn.setVisible(False)

    def _on_install_update(self) -> None:
        if not self.latest_release:
            return

        # Warn explicitly if any background tasks are currently running, showing exact %
        if self.active_tasks_fn is not None:
            running = self.active_tasks_fn()
            if running:
                lines = "\n".join(
                    f"  - {t.title}: {t.percent}% ({t.stage})" for t in running
                )
                reply = QMessageBox.warning(
                    self,
                    "Tareas en ejecucion detectadas",
                    "Tienes estas tareas activas en este momento:\n\n"
                    f"{lines}\n\n"
                    "Si actualizas ahora, se cerrara la aplicacion y estas tareas quedaran incompletas.\n"
                    "Deseas cancelar las tareas y actualizar ahora?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    self.status_lbl.setText("Actualizacion pospuesta hasta que terminen tus tareas activas.")
                    return

        self.install_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(2)
        self.status_lbl.setText("Preparando descarga de actualizacion...")

        def _dl(progress_cb=None) -> tuple[bool, str]:
            assert self.latest_release is not None
            return download_and_launch_update(self.latest_release, progress_cb=progress_cb)

        def _on_progress(pct: int, stage: str) -> None:
            self.progress_bar.setValue(pct)
            self.status_lbl.setText(f"[{pct}%] {stage}")

        def _done(res: tuple[bool, str]) -> None:
            ok, msg = res
            self.status_lbl.setText(msg)
            if ok:
                self.progress_bar.setValue(100)
                parent_win = self.parent()
                if parent_win is not None and hasattr(parent_win, "_quit_app"):
                    parent_win._quit_app()
                else:
                    QApplication.quit()
            else:
                self.install_btn.setEnabled(True)
                self.check_btn.setEnabled(True)

        # Pass optional progress callback hook if supported by MainWindow._run_async
        self.run_async(_dl, _done, "Descarga actualizacion", progress_ui_cb=_on_progress)
