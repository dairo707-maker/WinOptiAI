"""Animaciones sobrias y aviso "Deshacer" (v0.5.9), estilo Obsidian Acrylic.

- Duraciones cortas (150-450 ms), sin rebotes ni colores saturados.
- Respetan "Mostrar animaciones en Windows" (``win32_bridge.animations_enabled``): si esta
  apagado, el efecto final se aplica de inmediato.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QModelIndex,
    QPoint,
    QPropertyAnimation,
    QRect,
    QTimer,
    QVariantAnimation,
    Qt,
)
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QWidget,
)

from ..core.win32_bridge import animations_enabled

_ANIMS_ENABLED: bool | None = None


def anims_on() -> bool:
    global _ANIMS_ENABLED
    if _ANIMS_ENABLED is None:
        _ANIMS_ENABLED = animations_enabled()
    return _ANIMS_ENABLED


def set_animations_enabled(value: bool | None) -> None:
    """Forzar (pruebas) o volver a leer (None) la preferencia de animaciones."""
    global _ANIMS_ENABLED
    _ANIMS_ENABLED = value


def _keep(owner: QWidget, anim) -> None:
    """Mantener viva la animacion mientras corre (sin fugas)."""
    store = owner.property("_winopti_anims") or []
    store = [a for a in store if a.state() != QVariantAnimation.State.Stopped]
    store.append(anim)
    owner.setProperty("_winopti_anims", store)


def fade_out_table_rows(
    table: QTableWidget, rows: list[int], color: str, on_done: Callable[[], None], duration: int = 260
) -> None:
    """Desvanecer filas (tinte que se apaga) y luego ejecutar ``on_done`` (normalmente re-render)."""
    rows = sorted({r for r in rows if 0 <= r < table.rowCount()})
    if not rows or not anims_on():
        on_done()
        return
    base = QColor(color)
    anim = QVariantAnimation(table)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _step(t: float) -> None:
        c = QColor(base)
        c.setAlpha(int(110 * (1.0 - float(t))))
        for r in rows:
            for col in range(table.columnCount()):
                it = table.item(r, col)
                if it is not None:
                    it.setBackground(c)
                    fg = it.foreground().color()
                    fg.setAlpha(max(40, int(255 * (1.0 - float(t)))))
                    it.setForeground(fg)

    anim.valueChanged.connect(_step)
    anim.finished.connect(on_done)
    _keep(table, anim)
    anim.start()


def pulse_widget(widget: QWidget, color: str, duration: int = 650) -> None:
    """Pulso breve de borde/fondo (p. ej. pestana Boveda al recibir algo)."""
    if widget is None or not anims_on():
        return
    base = QColor(color)
    original = widget.styleSheet()
    anim = QVariantAnimation(widget)
    anim.setDuration(duration)
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.setEasingCurve(QEasingCurve.Type.OutQuad)

    def _step(t: float) -> None:
        a = int(150 * float(t))
        widget.setStyleSheet(
            f"{original}\nQPushButton {{ border: 1px solid rgba({base.red()}, {base.green()}, {base.blue()}, {max(a, 0)});"
            f" background-color: rgba({base.red()}, {base.green()}, {base.blue()}, {int(a / 4)}); }}"
        )

    anim.valueChanged.connect(_step)
    anim.finished.connect(lambda: widget.setStyleSheet(original))
    _keep(widget, anim)
    anim.start()


class UndoToast(QFrame):
    """Aviso breve abajo a la derecha: "Movido a Cuarentena: X · Deshacer" (desliza y se desvanece)."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("GlassPanelElevated")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 8, 8)
        lay.setSpacing(10)
        self.label = QLabel("")
        self.label.setObjectName("BodyText")
        lay.addWidget(self.label)
        self.undo_btn = QPushButton("Deshacer")
        self.undo_btn.setObjectName("RestoreAction")
        self.undo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.undo_btn.clicked.connect(self._on_undo)
        lay.addWidget(self.undo_btn)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._on_undo_cb: Callable[[], None] | None = None
        self.hide()

    def show_message(self, text: str, on_undo: Callable[[], None] | None, timeout_ms: int = 7000) -> None:
        self._on_undo_cb = on_undo
        self.label.setText(text)
        self.undo_btn.setVisible(on_undo is not None)
        self.adjustSize()
        parent = self.parentWidget()
        end = QPoint(max(8, parent.width() - self.width() - 24), max(8, parent.height() - self.height() - 20))
        self.raise_()
        self.show()
        self._effect.setOpacity(1.0)
        if anims_on():
            start = QPoint(end.x(), end.y() + 18)
            self.move(start)
            anim = QPropertyAnimation(self, b"pos", self)
            anim.setDuration(220)
            anim.setStartValue(start)
            anim.setEndValue(end)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            _keep(self, anim)
            anim.start()
        else:
            self.move(end)
        self._timer.start(timeout_ms)

    def _on_undo(self) -> None:
        cb = self._on_undo_cb
        self._on_undo_cb = None
        self.dismiss()
        if cb is not None:
            cb()

    def dismiss(self) -> None:
        self._timer.stop()
        if not self.isVisible():
            return
        if not anims_on():
            self.hide()
            return
        anim = QPropertyAnimation(self._effect, b"opacity", self)
        anim.setDuration(180)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(self.hide)
        _keep(self, anim)
        anim.start()


def set_badge_text(btn: QAbstractButton, base: str, count: int) -> None:
    btn.setText(f"{base} ({count})" if count > 0 else base)


class TrashColumnDelegate(QStyledItemDelegate):
    """Icono de caneca pintado al final de la celda; un clic envia esa fila a Cuarentena.

    Sin widgets por celda (``setCellWidget`` provoco cierres en versiones anteriores): el icono
    se dibuja con el delegado y el clic se detecta en ``editorEvent``.
    """

    ICON = 16
    PAD = 8

    def __init__(
        self,
        icon_fn: Callable[[], QIcon],
        enabled_fn: Callable[[QModelIndex], bool],
        on_click: Callable[[QModelIndex], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_fn = icon_fn
        self._enabled_fn = enabled_fn
        self._on_click = on_click

    def icon_rect(self, option_rect: QRect) -> QRect:
        s = self.ICON
        return QRect(option_rect.right() - s - self.PAD, option_rect.center().y() - s // 2, s, s)

    def paint(self, painter, option: QStyleOptionViewItem, index: QModelIndex) -> None:  # noqa: D401
        enabled = self._enabled_fn(index)
        if enabled:
            opt = QStyleOptionViewItem(option)
            opt.rect = option.rect.adjusted(0, 0, -(self.ICON + self.PAD * 2), 0)
            super().paint(painter, opt, index)
            hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
            pm = self._icon_fn().pixmap(self.ICON, self.ICON)
            painter.save()
            painter.setOpacity(1.0 if hover else 0.55)
            painter.drawPixmap(self.icon_rect(option.rect), pm)
            painter.restore()
        else:
            super().paint(painter, option, index)

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and self._enabled_fn(index)
            and self.icon_rect(option.rect).contains(event.position().toPoint())
        ):
            self._on_click(index)
            return True
        return super().editorEvent(event, model, option, index)
