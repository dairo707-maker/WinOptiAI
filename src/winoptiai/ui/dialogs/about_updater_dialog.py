"""About & Self-Updater dialog with author credits and GitHub Release SHA-256 update flow."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
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
from ..widgets import GlassPanel, StatusTag


class AboutUpdaterDialog(QDialog):
    """0px architectural About dialog with Dairo's credits and verified GitHub self-updater."""

    def __init__(
        self,
        lang: str,
        theme_mode: str,
        run_async: Callable,
        hardware_summary: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.lang = lang
        self.theme_mode = theme_mode
        self.run_async = run_async
        self.latest_release: ReleaseInfo | None = None

        self.setWindowTitle(tr("about_title", lang))
        self.setFixedSize(560, 440)

        p = get_palette(theme_mode)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

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

        # Release notes / Update status
        self.status_lbl = QLabel("Pulse 'Buscar Actualizaciones' para consultar GitHub Releases.")
        self.status_lbl.setObjectName("PageSubtitle")
        root.addWidget(self.status_lbl)

        self.notes_box = QPlainTextEdit()
        self.notes_box.setReadOnly(True)
        self.notes_box.setPlaceholderText("Notas de la ultima version disponible en GitHub...")
        root.addWidget(self.notes_box, stretch=1)

        # Actions row
        actions = QHBoxLayout()
        repo_btn = QPushButton("Abrir GitHub")
        repo_btn.setObjectName("GhostAction")
        repo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        repo_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_WEB_URL)))
        actions.addWidget(repo_btn)

        actions.addStretch()
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
        self.run_async(lambda: check_for_updates(__version__), self._on_check_done)

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
        self.install_btn.setEnabled(False)
        self.status_lbl.setText("Descargando instalador y verificando SHA-256...")

        def _dl() -> tuple[bool, str]:
            assert self.latest_release is not None
            return download_and_launch_update(self.latest_release)

        def _done(res: tuple[bool, str]) -> None:
            ok, msg = res
            self.status_lbl.setText(msg)
            if ok:
                QApplication.quit()
            else:
                self.install_btn.setEnabled(True)

        self.run_async(_dl, _done)
