"""v0.6.9: previsualizador interno de archivos (como en la version Android).

Imagenes, texto/codigo/CSV/JSON/registros, PDF (QtPdf) y audio/video (QtMultimedia), sin salir
de WinOptiAI. Regla inviolable: NUNCA se abre un archivo que solo esta en la nube (OneDrive Files
On-Demand), para no descargarlo; tampoco rutas de red.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..theme import format_bytes
from ..widgets import set_button_role

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".ico", ".svg", ".tif", ".tiff"}
TEXT_EXT = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".xml", ".log", ".ini", ".cfg", ".yaml", ".yml", ".toml",
    ".py", ".r", ".do", ".sql", ".js", ".ts", ".html", ".css", ".bat", ".ps1", ".sh", ".tex", ".bib",
}
PDF_EXT = {".pdf"}
MEDIA_EXT = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".mp3", ".wav", ".m4a", ".aac",
             ".flac", ".ogg", ".wma", ".opus"}
VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v"}
TEXT_LIMIT = 256 * 1024


def preview_kind(path: str) -> str:
    """'image' | 'text' | 'pdf' | 'media' | '' (sin vista previa interna)."""
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in TEXT_EXT:
        return "text"
    if ext in PDF_EXT:
        return "pdf"
    if ext in MEDIA_EXT:
        return "media"
    return ""


def can_preview(path: str) -> tuple[bool, str]:
    """(se puede, motivo). Nunca archivos solo-nube ni rutas de red."""
    from ...apps.app_manager import is_local_disk_path
    from ...core.win32_bridge import is_cloud_only_file

    if not path or not preview_kind(path):
        return False, "Este tipo de archivo no tiene vista previa interna."
    if not is_local_disk_path(path):
        return False, "Solo se previsualizan archivos de discos locales."
    if not os.path.isfile(path):
        return False, "El archivo ya no existe."
    if is_cloud_only_file(path):
        return False, "El archivo esta solo en la nube (OneDrive): abrirlo lo descargaria."
    return True, ""


class FilePreviewDialog(QDialog):
    def __init__(self, path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self._player = None
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(f"Vista previa - {os.path.basename(path)}")
        self.setMinimumSize(640, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        info = QLabel(f"{os.path.basename(path)}  ·  {format_bytes(size)}")
        info.setObjectName("CardTitle")
        root.addWidget(info)
        loc = QLabel(path)
        loc.setObjectName("MonoValue")
        loc.setWordWrap(True)
        loc.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(loc)

        ok, reason = can_preview(path)
        if not ok:
            msg = QLabel(reason)
            msg.setObjectName("BodyText")
            msg.setWordWrap(True)
            root.addWidget(msg, stretch=1)
        else:
            kind = preview_kind(path)
            builder = {"image": self._image, "text": self._text, "pdf": self._pdf, "media": self._media}[kind]
            try:
                root.addWidget(builder(), stretch=1)
            except Exception as exc:  # noqa: BLE001 - un formato raro nunca debe romper la app
                err = QLabel(f"No se pudo mostrar la vista previa: {exc}")
                err.setWordWrap(True)
                root.addWidget(err, stretch=1)

        btns = QHBoxLayout()
        btns.addStretch()
        reveal = QPushButton("Ver en el Explorador")
        set_button_role(reveal, "GhostAction")
        reveal.clicked.connect(self._reveal)
        btns.addWidget(reveal)
        close = QPushButton("Cerrar")
        set_button_role(close, "PrimaryAction")
        close.clicked.connect(self.close)
        btns.addWidget(close)
        root.addLayout(btns)

    # ------------------------------------------------------------------ tipos
    def _image(self) -> QWidget:
        pm = QPixmap(self.path)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if pm.isNull():
            lbl.setText("Imagen no compatible.")
        else:
            lbl.setPixmap(pm.scaled(900, 640, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(lbl)
        return area

    def _text(self) -> QWidget:
        with open(self.path, "rb") as fh:
            raw = fh.read(TEXT_LIMIT)
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        box = QPlainTextEdit()
        box.setReadOnly(True)
        box.setObjectName("MonoValue")
        suffix = "\n\n[... vista previa limitada a 256 KB ...]" if len(raw) >= TEXT_LIMIT else ""
        box.setPlainText(text + suffix)
        return box

    def _pdf(self) -> QWidget:
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView

        self._pdf_doc = QPdfDocument(self)
        self._pdf_doc.load(self.path)
        view = QPdfView(self)
        view.setDocument(self._pdf_doc)
        view.setPageMode(QPdfView.PageMode.MultiPage)
        view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        return view

    def _media(self) -> QWidget:
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        if Path(self.path).suffix.lower() in VIDEO_EXT:
            from PySide6.QtMultimediaWidgets import QVideoWidget

            video = QVideoWidget()
            video.setMinimumHeight(300)
            self._player.setVideoOutput(video)
            lay.addWidget(video, stretch=1)
        else:
            note = QLabel("Audio")
            note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(note, stretch=1)
        ctl = QHBoxLayout()
        play = QPushButton("Reproducir / Pausar")
        set_button_role(play, "GhostAction")
        play.clicked.connect(self._toggle_play)
        ctl.addWidget(play)
        self._pos = QSlider(Qt.Orientation.Horizontal)
        self._pos.sliderMoved.connect(lambda v: self._player.setPosition(int(v)))
        self._player.durationChanged.connect(lambda d: self._pos.setRange(0, int(d)))
        self._player.positionChanged.connect(lambda p: self._pos.blockSignals(True) or self._pos.setValue(int(p)) or self._pos.blockSignals(False))
        ctl.addWidget(self._pos, stretch=1)
        lay.addLayout(ctl)
        self._player.setSource(QUrl.fromLocalFile(self.path))
        return holder

    def _toggle_play(self) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        if self._player is None:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _reveal(self) -> None:
        from ...core.win32_bridge import reveal_in_explorer

        reveal_in_explorer(self.path)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._player is not None:
            try:
                self._player.stop()
            except RuntimeError:
                pass
        super().closeEvent(event)


def open_preview(path: str, parent: QWidget | None = None) -> bool:
    ok, _reason = can_preview(path)
    dlg = FilePreviewDialog(path, parent)
    dlg.show()
    return ok
