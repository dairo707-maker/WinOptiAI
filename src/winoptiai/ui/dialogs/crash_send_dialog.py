"""Aviso tipo Windows "WinOptiAI se cerro inesperadamente" con envio opcional por correo (v0.6.9; antes GitHub)."""

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
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.crash_guard import CrashGuard
from ...core.crash_reporter import (
    KIND_CRASH,
    build_issue_title,
    REPORT_EMAIL,
    build_mailto_url,
    build_report_markdown,
    save_report_file,
)
from ..widgets import StatusTag


class CrashSendDialog(QDialog):
    """Pregunta si enviar el informe. Muestra el texto exacto (anonimizado) antes de enviarlo."""

    def __init__(
        self,
        guard: CrashGuard,
        kind: str = KIND_CRASH,
        error_type: str = "",
        error_text: str = "",
        auto_restarted: bool = False,
        on_decision: Callable[[bool], None] | None = None,
        open_url: Callable[[str], bool] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.guard = guard
        self.kind = kind
        self.on_decision = on_decision
        self._open_url = open_url or (lambda url: QDesktopServices.openUrl(QUrl(url)))
        self.sent = False
        self.saved_path = None
        self.issue_title = build_issue_title(guard, kind, error_type)
        self.report_text = build_report_markdown(guard, kind, error_text, auto_restarted)

        crash = kind == KIND_CRASH
        self.setWindowTitle("WinOptiAI")
        self.resize(620, 300)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        title = QLabel("WinOptiAI se cerro inesperadamente" if crash else "WinOptiAI encontro un error inesperado")
        title.setObjectName("PageTitle")
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(StatusTag("CIERRE INESPERADO" if crash else "ERROR", "risk"), 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(hdr)

        intro = (
            "Lamentamos el inconveniente. "
            if crash
            else "La aplicacion sigue abierta, pero una operacion fallo. "
        )
        msg = QLabel(
            intro
            + "¿Desea enviar un informe de error para ayudar a diagnosticar el problema?\n"
            "Se abrira su programa de correo con el informe ya escrito para el equipo de WinOptiAI: usted lo "
            "revisa y pulsa Enviar. No necesita cuenta de GitHub ni de ningun otro sitio. "
            "Su usuario de Windows, el nombre del equipo y los correos se reemplazaron por marcadores."
        )
        msg.setWordWrap(True)
        msg.setObjectName("PageSubtitle")
        root.addWidget(msg)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setObjectName("MonoValue")
        self.details.setPlainText(self.report_text)
        self.details.setVisible(False)
        root.addWidget(self.details, stretch=1)

        actions = QHBoxLayout()
        self.details_btn = QPushButton("Ver informe")
        self.details_btn.setObjectName("GhostAction")
        self.details_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.details_btn.clicked.connect(self._toggle_details)
        actions.addWidget(self.details_btn)
        actions.addStretch()

        self.skip_btn = QPushButton("No enviar")
        self.skip_btn.setObjectName("GhostAction")
        self.skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skip_btn.clicked.connect(self._skip)
        actions.addWidget(self.skip_btn)

        self.send_btn = QPushButton("Enviar informe")
        self.send_btn.setObjectName("PrimaryAction")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setDefault(True)
        self.send_btn.clicked.connect(self._send)
        actions.addWidget(self.send_btn)
        root.addLayout(actions)

        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("PageSubtitle")
        self.status_lbl.setWordWrap(True)
        root.addWidget(self.status_lbl)

    def _toggle_details(self) -> None:
        show = not self.details.isVisible()
        self.details.setVisible(show)
        self.details_btn.setText("Ocultar informe" if show else "Ver informe")
        if show and self.height() < 520:
            self.resize(self.width(), 560)

    def _skip(self) -> None:
        if self.on_decision is not None:
            self.on_decision(False)
        self.reject()

    def _send(self) -> None:
        clip = QApplication.clipboard()
        if clip is not None:
            clip.setText(self.report_text)
        # Respaldo en disco por si el portapapeles se pierde (y para adjuntarlo al correo).
        self.saved_path = save_report_file(self.report_text, self.guard.app_dir)
        url, truncated = build_mailto_url(self.issue_title, self.report_text)
        opened = bool(self._open_url(url))
        self.sent = opened
        if self.on_decision is not None:
            self.on_decision(opened)
        where = f"\nCopia guardada en: {self.saved_path}" if self.saved_path else ""
        if opened:
            QMessageBox.information(
                self,
                "Informe listo en su correo",
                "Se abrio su programa de correo con el informe.\n\n"
                + (
                    "1. El informe es largo: pegue el texto completo con Ctrl+V debajo de la nota final "
                    "(ya esta en su portapapeles) o adjunte el archivo guardado.\n2. Pulse Enviar."
                    if truncated
                    else "1. Revise el texto.\n2. Pulse Enviar."
                )
                + where,
            )
            self.accept()
            return
        self.status_lbl.setText(
            "No hay un programa de correo configurado. El informe quedo copiado en el portapapeles: "
            f"envielo desde su correo web (Gmail, Outlook) a {REPORT_EMAIL}." + where.replace("\n", " ")
        )
