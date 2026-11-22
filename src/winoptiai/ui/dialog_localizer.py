"""v0.6.5: botones de dialogos en el idioma elegido y con estilo visible.

Qt pinta los botones estandar de ``QMessageBox`` / ``QDialogButtonBox`` en ingles ("Yes", "No")
y, con el QSS de la app, como texto plano casi invisible. Un filtro de eventos a nivel de
aplicacion los traduce y les asigna roles visuales justo antes de mostrarse, asi que cubre las
30+ confirmaciones existentes (y las futuras) sin tocar cada llamada.

- Afirmativo (Si / Aceptar / Guardar...): ``PrimaryAction``; en avisos de riesgo
  (icono Advertencia/Critico) ``RiskAction`` para que se note que la accion importa.
- Negativo (No / Cancelar / Cerrar...): ``GhostAction``.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox, QPushButton

from .widgets import ROLE_RISK, set_button_role

SB = QMessageBox.StandardButton
DB = QDialogButtonBox.StandardButton

# Clave neutra -> texto por idioma.
_LABELS: dict[str, dict[str, str]] = {
    "es": {
        "yes": "Sí", "no": "No", "ok": "Aceptar", "cancel": "Cancelar", "close": "Cerrar",
        "save": "Guardar", "discard": "Descartar", "retry": "Reintentar", "ignore": "Omitir",
        "abort": "Detener", "apply": "Aplicar", "open": "Abrir", "help": "Ayuda",
        "yes_all": "Sí a todo", "no_all": "No a todo", "reset": "Restablecer",
    },
    "en": {
        "yes": "Yes", "no": "No", "ok": "OK", "cancel": "Cancel", "close": "Close",
        "save": "Save", "discard": "Discard", "retry": "Retry", "ignore": "Ignore",
        "abort": "Abort", "apply": "Apply", "open": "Open", "help": "Help",
        "yes_all": "Yes to all", "no_all": "No to all", "reset": "Reset",
    },
    "pt": {
        "yes": "Sim", "no": "Não", "ok": "OK", "cancel": "Cancelar", "close": "Fechar",
        "save": "Salvar", "discard": "Descartar", "retry": "Tentar de novo", "ignore": "Ignorar",
        "abort": "Interromper", "apply": "Aplicar", "open": "Abrir", "help": "Ajuda",
        "yes_all": "Sim para todos", "no_all": "Não para todos", "reset": "Redefinir",
    },
}

_KEY_BY_VALUE: dict[int, str] = {
    int(SB.Yes.value): "yes", int(SB.No.value): "no", int(SB.Ok.value): "ok",
    int(SB.Cancel.value): "cancel", int(SB.Close.value): "close", int(SB.Save.value): "save",
    int(SB.Discard.value): "discard", int(SB.Retry.value): "retry", int(SB.Ignore.value): "ignore",
    int(SB.Abort.value): "abort", int(SB.Apply.value): "apply", int(SB.Open.value): "open",
    int(SB.Help.value): "help", int(SB.YesToAll.value): "yes_all", int(SB.NoToAll.value): "no_all",
    int(SB.Reset.value): "reset",
}
_AFFIRMATIVE = {"yes", "ok", "save", "apply", "retry", "open", "yes_all"}

_state = {"lang": "es"}


def set_dialog_language(lang: str) -> None:
    _state["lang"] = lang if lang in _LABELS else "es"


def dialog_language() -> str:
    return _state["lang"]


def button_label(key: str, lang: str | None = None) -> str:
    return _LABELS.get(lang or _state["lang"], _LABELS["es"]).get(key, key)


def _style_button(btn: QPushButton, key: str, risky: bool, lang: str) -> None:
    btn.setText(button_label(key, lang))
    if key in _AFFIRMATIVE:
        set_button_role(btn, ROLE_RISK if risky else "PrimaryAction")
    else:
        set_button_role(btn, "GhostAction")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    width = btn.fontMetrics().horizontalAdvance(btn.text()) + 40
    btn.setMinimumWidth(max(96, width))
    btn.setMinimumHeight(32)


def localize_message_box(box: QMessageBox, lang: str | None = None) -> None:
    lang = lang or _state["lang"]
    risky = box.icon() in (QMessageBox.Icon.Warning, QMessageBox.Icon.Critical)
    for btn in box.buttons():
        key = _KEY_BY_VALUE.get(int(box.standardButton(btn).value))
        if key and isinstance(btn, QPushButton):
            _style_button(btn, key, risky, lang)


def localize_button_box(bb: QDialogButtonBox, lang: str | None = None) -> None:
    lang = lang or _state["lang"]
    for btn in bb.buttons():
        key = _KEY_BY_VALUE.get(int(bb.standardButton(btn).value))
        if key and isinstance(btn, QPushButton):
            _style_button(btn, key, False, lang)


class DialogLocalizer(QObject):
    """Filtro global: traduce y da estilo a los botones estandar al mostrarse cada dialogo."""

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Type.Show:
            try:
                if isinstance(obj, QMessageBox):
                    localize_message_box(obj)
                elif isinstance(obj, QDialog):
                    for bb in obj.findChildren(QDialogButtonBox):
                        localize_button_box(bb)
            except RuntimeError:  # objeto C++ ya destruido
                pass
        return False


_installed: list[DialogLocalizer] = []


def install_dialog_localizer(app: QApplication, lang: str) -> DialogLocalizer:
    set_dialog_language(lang)
    if _installed:
        return _installed[0]
    loc = DialogLocalizer(app)
    app.installEventFilter(loc)
    _installed.append(loc)
    return loc
