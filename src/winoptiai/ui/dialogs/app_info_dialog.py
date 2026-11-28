"""v0.6.9: ficha "Informacion de la app" (clic derecho en Aplicaciones).

Muestra que es la app (descripcion oficial del catalogo winget o, sin red, la descripcion interna
del .exe que Windows muestra en Propiedades), quien la publica, version, tamano, fechas, uso y
carpeta. La descripcion se completa en segundo plano: la ventana abre al instante.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...apps.app_manager import InstalledApp, retired_reason, upgrade_block_reason
from ...core.usage_telemetry import format_app_last_used
from ..app_icons import app_icon
from ..theme import format_bytes
from ..widgets import FlowLayout, set_button_role


def _fmt_date(ts: float) -> str:
    return time.strftime("%d/%m/%Y", time.localtime(ts)) if ts and ts > 0 else "--"


class AppInfoDialog(QDialog):
    def __init__(self, app: InstalledApp, theme_mode: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(f"Informacion de la app - {app.name}")
        self.setMinimumSize(560, 440)
        self._homepage = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        hdr = QHBoxLayout()
        hdr.setSpacing(12)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(app_icon(app, float(self.devicePixelRatioF() or 1.0)).pixmap(QSize(32, 32)))
        hdr.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignTop)
        tbox = QVBoxLayout()
        tbox.setSpacing(2)
        title = QLabel(app.name)
        title.setObjectName("PageTitle")
        title.setWordWrap(True)
        self.publisher_lbl = QLabel(app.publisher or "Editor no registrado")
        self.publisher_lbl.setObjectName("PageSubtitle")
        tbox.addWidget(title)
        tbox.addWidget(self.publisher_lbl)
        hdr.addLayout(tbox, stretch=1)
        root.addLayout(hdr)

        what = QLabel("QUE ES")
        what.setObjectName("SectionLabel")
        root.addWidget(what)
        self.desc_lbl = QLabel("Buscando la descripcion oficial...")
        self.desc_lbl.setObjectName("BodyText")
        self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.desc_lbl)

        retired = retired_reason(app)
        block = upgrade_block_reason(app)
        if retired or app.upgrade_note or (app.available_version and block):
            note = QLabel(retired or app.upgrade_note or block)
            note.setObjectName("Caption")
            note.setWordWrap(True)
            root.addWidget(note)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        loc = (app.install_location or "").strip().strip('"')
        rows = [
            ("Version instalada", app.version or "--"),
            ("Nueva version", app.available_version or "Al dia o sin revisar"),
            ("Tamano", format_bytes(app.size_bytes) if app.size_bytes > 0 else "--"),
            ("Instalada", _fmt_date(app.install_date_ts)),
            ("Ultimo uso", format_app_last_used(app.last_used_ts, app.install_date_ts, time.time())),
            ("Para", "Todos los usuarios" if app.scope == "Sistema" else "Solo este usuario"),
            ("Identificador winget", app.winget_id or "No esta en el catalogo winget"),
            ("Carpeta", loc or "No registrada"),
        ]
        self.extra_rows: dict[str, QLabel] = {}
        for r, (k, v) in enumerate(rows):
            kl = QLabel(k)
            kl.setObjectName("Caption")
            vl = QLabel(v)
            vl.setWordWrap(True)
            vl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if k in ("Carpeta", "Identificador winget"):
                vl.setObjectName("MonoValue")
            grid.addWidget(kl, r, 0, alignment=Qt.AlignmentFlag.AlignTop)
            grid.addWidget(vl, r, 1)
        self.license_key = QLabel("Licencia")
        self.license_key.setObjectName("Caption")
        self.license_val = QLabel("--")
        grid.addWidget(self.license_key, len(rows), 0)
        grid.addWidget(self.license_val, len(rows), 1)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)
        root.addStretch()

        btns = FlowLayout(spacing=8)
        self.folder_btn = QPushButton("Abrir carpeta")
        set_button_role(self.folder_btn, "GhostAction")
        self.folder_btn.setEnabled(bool(loc))
        self.folder_btn.clicked.connect(lambda: self._open_folder(loc))
        btns.addWidget(self.folder_btn)
        self.web_btn = QPushButton("Pagina oficial")
        set_button_role(self.web_btn, "GhostAction")
        self.web_btn.setEnabled(False)
        self.web_btn.clicked.connect(self._open_homepage)
        btns.addWidget(self.web_btn)
        close_btn = QPushButton("Cerrar")
        set_button_role(close_btn, "PrimaryAction")
        close_btn.clicked.connect(self.close)
        btns.addWidget(close_btn)
        holder = QWidget()
        holder.setLayout(btns)
        root.addWidget(holder)

    # ------------------------------------------------------------------ datos en segundo plano
    def set_details(self, local: dict, online: dict) -> None:
        desc = (online.get("description") or online.get("short_description") or "").strip()
        source = "catalogo oficial winget" if desc else ""
        if not desc and local.get("description"):
            product = local.get("product", "")
            desc = local["description"] if not product or product in local["description"] else f"{local['description']} ({product})"
            source = "descripcion interna del programa"
        if desc:
            self.desc_lbl.setText(f"{desc}\n\nFuente: {source}.")
        else:
            self.desc_lbl.setText(
                "Esta app no trae descripcion oficial (no esta en el catalogo winget y su programa "
                "no la incluye). Revisa el editor y la carpeta para identificarla."
            )
        publisher = online.get("publisher") or local.get("publisher")
        if publisher and not self.app.publisher:
            self.publisher_lbl.setText(publisher)
        if online.get("license"):
            self.license_val.setText(online["license"])
        hp = online.get("homepage", "")
        if hp.lower().startswith("https://"):
            self._homepage = hp
            self.web_btn.setEnabled(True)
            self.web_btn.setToolTip(hp)

    def _open_homepage(self) -> None:
        if self._homepage.lower().startswith("https://"):
            QDesktopServices.openUrl(QUrl(self._homepage))

    @staticmethod
    def _open_folder(loc: str) -> None:
        from ...core.win32_bridge import reveal_in_explorer

        if loc:
            reveal_in_explorer(loc)
