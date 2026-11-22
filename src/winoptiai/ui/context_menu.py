"""v0.6.5: menu de clic derecho en todas las tablas con las MISMAS acciones de cada apartado.

El menu se construye en el momento a partir de los botones reales de la vista, asi nunca se
desincroniza: muestra el texto completo del boton, su icono y su estado (desactivado si el
boton lo esta), y al elegir una opcion se pulsa ese boton. En Almacenamiento, donde los botones
cambian de texto segun el modo, el menu cambia con ellos.

v0.6.5 (decision del propietario): el menu muestra SOLO lo que aplica a lo seleccionado. Las
acciones generales ("Actualizar todas", "Escanear"...) ya estan arriba y no se repiten, y una
accion que no aplica (boton desactivado, app sin nueva version, protegida...) no aparece.
Orden: acciones sobre la seleccion -> utilidades (Explorador, copiar...).
"""

from __future__ import annotations

from typing import Callable, Iterable, Sequence

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractItemView, QApplication, QMenu, QPushButton, QWidget

# (texto, accion, habilitada)
Extra = tuple[str, Callable[[], None], bool]
ButtonsArg = Sequence[QPushButton] | Callable[[], Sequence[QPushButton]]
ExtrasArg = Callable[[], Iterable[Extra | None]] | None


def _full_text(btn: QPushButton) -> str:
    variants = getattr(btn, "variants", None)
    if callable(variants):
        try:
            vals = variants()
            if vals:
                return str(vals[0]).strip()
        except Exception:  # noqa: BLE001
            pass
    return (btn.text() or "").replace("&", "").strip()


def _resolve(arg: ButtonsArg | None) -> list[QPushButton]:
    if arg is None:
        return []
    items = arg() if callable(arg) else arg
    out: list[QPushButton] = []
    for b in items:
        try:
            if b is not None and not b.isHidden() and _full_text(b):
                out.append(b)
        except RuntimeError:  # boton destruido
            continue
    return out


def build_action_menu(
    parent: QWidget,
    row_buttons: ButtonsArg | None = None,
    general_buttons: ButtonsArg | None = None,
    extras: ExtrasArg = None,
) -> QMenu:
    """Menu con las acciones vigentes (se puede probar sin mostrarlo)."""
    menu = QMenu(parent)
    sections: list[list[QAction]] = []

    def _btn_actions(buttons: list[QPushButton]) -> list[QAction]:
        acts: list[QAction] = []
        for b in buttons:
            if not b.isEnabled():
                continue  # no aplica ahora: no se muestra
            act = QAction(b.icon(), _full_text(b), menu)
            tip = b.toolTip()
            if tip:
                act.setToolTip(tip)
            act.triggered.connect(lambda _c=False, _b=b: _b.click())
            acts.append(act)
        return acts

    sections.append(_btn_actions(_resolve(row_buttons)))
    extra_acts: list[QAction] = []
    if extras is not None:
        for ex in extras() or []:
            if ex is None:  # separador entre acciones y utilidades
                if extra_acts:
                    sections.append(extra_acts)
                    extra_acts = []
                continue
            text, fn, enabled = ex
            if not enabled:
                continue  # no aplica a la seleccion: no se muestra
            act = QAction(text, menu)
            act.triggered.connect(lambda _c=False, _f=fn: _f())
            extra_acts.append(act)
    sections.append(extra_acts)
    sections.append(_btn_actions(_resolve(general_buttons)))

    first = True
    for acts in sections:
        if not acts:
            continue
        if not first:
            menu.addSeparator()
        first = False
        for a in acts:
            menu.addAction(a)
    menu.setToolTipsVisible(True)
    return menu


def _select_under_cursor(view: QAbstractItemView, pos: QPoint) -> bool:
    idx = view.indexAt(pos)
    if not idx.isValid():
        return False
    sel = view.selectionModel()
    if sel is not None and not sel.isSelected(idx):
        view.setCurrentIndex(idx)  # respeta la seleccion multiple si el clic cae dentro de ella
    return True


def copy_text(text: str) -> None:
    QApplication.clipboard().setText(text or "")


def install_action_menu(
    view: QAbstractItemView,
    row_buttons: ButtonsArg | None = None,
    general_buttons: ButtonsArg | None = None,
    extras: ExtrasArg = None,
) -> None:
    """Conectar el menu contextual a una tabla/arbol (reemplaza un menu previo, si lo habia)."""
    view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    import warnings

    with warnings.catch_warnings():  # sin menu previo PySide avisa "Failed to disconnect": es normal
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            view.customContextMenuRequested.disconnect()
        except (RuntimeError, TypeError):
            pass

    def _show(pos: QPoint) -> None:
        if not _select_under_cursor(view, pos):
            return  # fuera de una fila no hay nada seleccionado sobre que actuar
        menu = build_action_menu(view, row_buttons, general_buttons, extras)
        if menu.actions():
            menu.exec(view.viewport().mapToGlobal(pos))

    view.customContextMenuRequested.connect(_show)


def row_text(view) -> str:
    """Texto de la fila actual de una QTableWidget (celdas separadas por tabulador)."""
    try:
        r = view.currentRow()
        if r < 0:
            return ""
        cells = []
        for c in range(view.columnCount()):
            it = view.item(r, c)
            cells.append(it.text() if it is not None else "")
        return "\t".join(cells).strip()
    except Exception:  # noqa: BLE001
        return ""


def copy_row_extra(view) -> Extra:
    return ("Copiar fila", lambda: copy_text(row_text(view)), True)
