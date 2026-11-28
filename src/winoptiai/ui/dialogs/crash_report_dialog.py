"""0px diagnostic viewer for crash.log / dirty-exit post-mortem (v0.5.1)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
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

from ...core.crash_guard import CrashGuard
from ...core.crash_reporter import KIND_CRASH, KIND_ERROR
from ...core.win32_bridge import reveal_in_explorer
from ..widgets import StatusTag


class CrashReportDialog(QDialog):
    """Read-only diagnostic text with Copy and Open crash.log actions."""

    def __init__(self, guard: CrashGuard, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.guard = guard
        self.setWindowTitle("Diagnostico de Cierres Inesperados")
        self.resize(640, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        lbl = QLabel("DIAGNOSTICO POST-MORTEM LOCAL")
        lbl.setObjectName("SectionLabel")
        hdr.addWidget(lbl)
        hdr.addStretch()
        prev = guard.previous_session
        dirty = bool(prev and prev.dirty)
        hdr.addWidget(StatusTag("CIERRE INESPERADO" if dirty else "SESION PREVIA LIMPIA", "risk" if dirty else "ok"))
        root.addLayout(hdr)

        path_lbl = QLabel(str(guard.crash_log_path))
        path_lbl.setObjectName("MonoValue")
        path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(path_lbl)

        self.text_box = QPlainTextEdit()
        self.text_box.setReadOnly(True)
        self.text_box.setObjectName("MonoValue")
        self.text_box.setPlainText(guard.build_diagnostic_text())
        root.addWidget(self.text_box, stretch=1)

        actions = QHBoxLayout()
        open_btn = QPushButton("Abrir crash.log")
        open_btn.setObjectName("GhostAction")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.clicked.connect(self._open_log)
        actions.addWidget(open_btn)
        send_btn = QPushButton("Enviar por correo")  # v0.6.9: sin cuenta de GitHub
        send_btn.setObjectName("GhostAction")
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        send_btn.clicked.connect(self._send_report)
        actions.addWidget(send_btn)
        actions.addStretch()

        copy_btn = QPushButton("Copiar Diagnostico")
        copy_btn.setObjectName("PrimaryAction")
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.clicked.connect(self._copy)
        actions.addWidget(copy_btn)
        root.addLayout(actions)

        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("PageSubtitle")
        root.addWidget(self.status_lbl)

    def _copy(self) -> None:
        clip = QApplication.clipboard()
        if clip is not None:
            clip.setText(self.text_box.toPlainText())
            self.status_lbl.setText("Diagnostico copiado al portapapeles.")

    def _send_report(self) -> None:
        # v0.5.3: mismo flujo que el aviso automatico (texto anonimizado, revision previa).
        from .crash_send_dialog import CrashSendDialog

        prev = self.guard.previous_session
        kind = KIND_CRASH if (prev and prev.dirty) else KIND_ERROR
        dlg = CrashSendDialog(self.guard, kind=kind, error_type="reporte manual", parent=self)
        dlg.exec()

    def _open_log(self) -> None:
        path = self.guard.crash_log_path
        if not path.exists():
            self.status_lbl.setText("crash.log aun no existe (no se han registrado fallos).")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            reveal_in_explorer(path)
