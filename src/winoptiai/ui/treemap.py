"""Mapa jerarquico (treemap) de carpetas, estilo Obsidian Acrylic (v0.5.4).

- Rectangulos rectos con lineas hairline de 1 px y tonos monocromo (sin colores saturados).
- Dos niveles visibles: cada subcarpeta muestra en su interior sus propias subcarpetas.
- Clic: entrar en la carpeta. Boton "Subir": volver. Doble clic / menu: abrir en el Explorador.
- El espacio de los archivos sueltos de la carpeta actual se dibuja como bloque propio.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QMenu, QToolTip, QWidget

from ..storage.tree_analyzer import FolderNode
from .theme import format_bytes

MIN_LABEL_W = 70.0
MIN_LABEL_H = 34.0
MAX_TILES = 60


@dataclass
class Tile:
    rect: QRectF
    node: FolderNode | None  # None = archivos sueltos de la carpeta actual
    depth: int
    label: str
    size: int


def squarify(sizes: list[float], rect: QRectF) -> list[QRectF]:
    """Algoritmo squarified (Bruls et al.): rectangulos lo mas cuadrados posible."""
    out: list[QRectF] = []
    vals = [s for s in sizes if s > 0]
    if not vals or rect.width() <= 0 or rect.height() <= 0:
        return [QRectF() for _ in sizes]
    total = float(sum(vals))
    scale = rect.width() * rect.height() / total
    areas = [s * scale for s in sizes]
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    i = 0
    n = len(areas)

    def _worst(row: list[float], side: float) -> float:
        s = sum(row)
        if s <= 0 or side <= 0:
            return float("inf")
        return max(max(side * side * r / (s * s), (s * s) / (side * side * r)) for r in row if r > 0)

    while i < n:
        if areas[i] <= 0:
            out.append(QRectF())
            i += 1
            continue
        side = min(w, h)
        row = [areas[i]]
        j = i + 1
        while j < n and areas[j] > 0 and _worst(row + [areas[j]], side) <= _worst(row, side):
            row.append(areas[j])
            j += 1
        s = sum(row)
        if w >= h:  # columna a la izquierda
            col_w = s / h if h else 0
            yy = y
            for a in row:
                hh = a / col_w if col_w else 0
                out.append(QRectF(x, yy, col_w, hh))
                yy += hh
            x += col_w
            w -= col_w
        else:  # fila arriba
            row_h = s / w if w else 0
            xx = x
            for a in row:
                ww = a / row_h if row_h else 0
                out.append(QRectF(xx, y, ww, row_h))
                xx += ww
            y += row_h
            h -= row_h
        i = j
    return out


class TreemapWidget(QWidget):
    """Treemap navegable de un arbol ``FolderNode``."""

    path_changed = Signal(str)
    reveal_requested = Signal(str)

    def __init__(self, palette_fn: Callable[[], dict[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette_fn = palette_fn
        self._root: FolderNode | None = None
        self._stack: list[FolderNode] = []
        self._tiles: list[Tile] = []
        self._hover: Tile | None = None
        self.setMouseTracking(True)
        self.setMinimumHeight(260)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

    # ------------------------------------------------------------------ data
    def set_root(self, root: FolderNode | None) -> None:
        self._root = root
        self._stack = [root] if root is not None else []
        self._relayout()

    @property
    def current(self) -> FolderNode | None:
        return self._stack[-1] if self._stack else None

    def can_go_up(self) -> bool:
        return len(self._stack) > 1

    def go_up(self) -> None:
        if self.can_go_up():
            self._stack.pop()
            self._relayout()

    def enter(self, node: FolderNode) -> None:
        if node.children:
            self._stack.append(node)
            self._relayout()

    def breadcrumb(self) -> str:
        return " / ".join(n.name for n in self._stack)

    # ------------------------------------------------------------------ layout
    def _entries(self, node: FolderNode) -> list[tuple[FolderNode | None, int, str]]:
        kids = [c for c in node.children if c.size_bytes > 0][:MAX_TILES]
        entries: list[tuple[FolderNode | None, int, str]] = [(c, c.size_bytes, c.name) for c in kids]
        loose = node.size_bytes - sum(c.size_bytes for c in node.children)
        if loose > node.size_bytes * 0.005 and loose > 0:
            entries.append((None, loose, "(archivos en esta carpeta)"))
        entries.sort(key=lambda e: e[1], reverse=True)
        return entries

    def _relayout(self) -> None:
        self._tiles = []
        self._hover = None
        cur = self.current
        if cur is not None and self.width() > 4 and self.height() > 4:
            area = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            entries = self._entries(cur)
            rects = squarify([float(e[1]) for e in entries], area)
            for (node, size, label), r in zip(entries, rects):
                if r.isEmpty():
                    continue
                self._tiles.append(Tile(r, node, 1, label, size))
                # segundo nivel dentro del bloque (sin texto si no cabe)
                if node is not None and node.children and r.width() > 60 and r.height() > 50:
                    inner = r.adjusted(3, 18, -3, -3)
                    sub = self._entries(node)
                    for (snode, ssize, slabel), sr in zip(sub, squarify([float(e[1]) for e in sub], inner)):
                        if not sr.isEmpty():
                            self._tiles.append(Tile(sr, snode, 2, slabel, ssize))
        self.path_changed.emit(self.breadcrumb())
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    # ------------------------------------------------------------------ hit testing
    def tile_at(self, pos: QPoint) -> Tile | None:
        hit: Tile | None = None
        for t in self._tiles:  # los de nivel 2 se agregan despues -> ganan
            if t.rect.contains(pos.x(), pos.y()):
                hit = t
        return hit

    def _top_level_of(self, tile: Tile) -> Tile | None:
        if tile.depth == 1:
            return tile
        for t in self._tiles:
            if t.depth == 1 and t.rect.contains(tile.rect.center()):
                return t
        return None

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        pal = self._palette_fn()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        dark = QColor(pal.get("text_primary", "#F3EFE6")).lightness() > 128
        base = QColor(pal.get("text_primary", "#F3EFE6"))
        line = QColor(pal.get("text_muted", "#8C867A"))
        line.setAlpha(150)
        txt = QColor(pal.get("text_primary", "#F3EFE6"))
        muted = QColor(pal.get("text_muted", "#8C867A"))

        if not self._tiles:
            p.setPen(muted)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Analice una carpeta para ver el mapa jerarquico.")
            p.end()
            return

        total = max(1, self.current.size_bytes if self.current else 1)
        mono = QFont("IBM Plex Mono", 8)
        ui = QFont("Instrument Sans", 9)
        fm_ui = QFontMetrics(ui)
        level1 = [t for t in self._tiles if t.depth == 1]
        for idx, t in enumerate(self._tiles):
            fill = QColor(base)
            if t.depth == 1:
                share = t.size / total
                # tono monocromo mas intenso cuanto mas pesa (acotado para que el texto siga legible)
                fill.setAlpha(int(16 + 42 * min(1.0, share * 2.5)) if dark else int(12 + 38 * min(1.0, share * 2.5)))
                if t.node is None:
                    fill.setAlpha(10)
            else:
                fill.setAlpha(14 if (idx % 2) else 22)
            if self._hover is not None and (t is self._hover):
                fill.setAlpha(min(255, fill.alpha() + 45))
            p.fillRect(t.rect, fill)
            pen = QPen(line if t.depth == 1 else QColor(line.red(), line.green(), line.blue(), 70))
            pen.setWidth(1)
            p.setPen(pen)
            p.drawRect(t.rect.adjusted(0, 0, -1, -1))

        fm_mono = QFontMetrics(mono)
        for t in level1:
            r = t.rect
            if r.width() < MIN_LABEL_W or r.height() < MIN_LABEL_H * 0.6:
                continue
            stat_txt = f"{format_bytes(t.size)}  {t.size * 100.0 / total:.1f}%"
            stat_w = fm_mono.horizontalAdvance(stat_txt) + 10
            nested = t.node is not None and t.node.children and r.height() > 50
            # Encabezado: nombre a la izquierda y peso a la derecha si cabe en la misma linea.
            same_line = nested and r.width() > stat_w + 80
            name_w = int(r.width() - 10 - (stat_w if same_line else 0))
            p.setFont(ui)
            p.setPen(txt)
            name = fm_ui.elidedText(t.label, Qt.TextElideMode.ElideRight, max(10, name_w))
            p.drawText(QRectF(r.x() + 5, r.y() + 2, name_w, 15), Qt.AlignmentFlag.AlignLeft, name)
            p.setFont(mono)
            p.setPen(muted)
            if same_line:
                p.drawText(QRectF(r.right() - stat_w, r.y() + 3, stat_w - 5, 14), Qt.AlignmentFlag.AlignRight, stat_txt)
            elif r.height() >= MIN_LABEL_H and not nested:
                p.drawText(QRectF(r.x() + 5, r.y() + 17, r.width() - 10, 14), Qt.AlignmentFlag.AlignLeft, stat_txt)

        # Etiquetas del segundo nivel cuando el bloque es suficientemente grande.
        small_ui = QFont("Instrument Sans", 8)
        fm_small = QFontMetrics(small_ui)
        for t in self._tiles:
            r = t.rect
            if t.depth != 2 or r.width() < 90 or r.height() < 32:
                continue
            p.setFont(small_ui)
            p.setPen(muted)
            p.drawText(
                QRectF(r.x() + 4, r.y() + 2, r.width() - 8, 13),
                Qt.AlignmentFlag.AlignLeft,
                fm_small.elidedText(t.label, Qt.TextElideMode.ElideRight, int(r.width() - 8)),
            )
            p.setFont(mono)
            p.drawText(QRectF(r.x() + 4, r.y() + 15, r.width() - 8, 13), Qt.AlignmentFlag.AlignLeft, format_bytes(t.size))
        p.end()

    # ------------------------------------------------------------------ interaction
    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        t = self.tile_at(event.position().toPoint())
        if t is not self._hover:
            self._hover = t
            self.update()
        if t is not None:
            total = max(1, self.current.size_bytes if self.current else 1)
            where = str(t.node.path) if t.node is not None else str(self.current.path if self.current else "")
            hint = "Clic: entrar | Doble clic: Explorador" if (t.node and t.node.children) else "Doble clic: Explorador"
            QToolTip.showText(
                event.globalPosition().toPoint(),
                f"{t.label}\n{format_bytes(t.size)} ({t.size * 100.0 / total:.1f}% de la vista)\n{where}\n{hint}",
                self,
            )
        else:
            QToolTip.hideText()

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._hover = None
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        t = self.tile_at(event.position().toPoint())
        if t is None or t.node is None:
            return
        # entrar en el bloque de primer nivel (o en el sub-bloque si tiene hijos)
        top = self._top_level_of(t)
        if top is not None and top.node is not None and top.node.children:
            self.enter(top.node)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        t = self.tile_at(event.position().toPoint())
        path = self._path_of(t)
        if path:
            self.reveal_requested.emit(path)

    def _path_of(self, t: Tile | None) -> str:
        if t is None:
            return ""
        if t.node is not None:
            return str(t.node.path)
        return str(self.current.path) if self.current else ""

    def _show_menu(self, pos: QPoint) -> None:
        t = self.tile_at(pos)
        menu = QMenu(self)
        path = self._path_of(t) or (str(self.current.path) if self.current else "")
        if path:
            act = QAction("Ver en el Explorador de Windows", menu)
            act.triggered.connect(lambda: self.reveal_requested.emit(path))
            menu.addAction(act)
        if t is not None and t.node is not None and t.node.children:
            act_in = QAction("Entrar en esta carpeta", menu)
            node = t.node
            act_in.triggered.connect(lambda: self.enter(node))
            menu.addAction(act_in)
        if self.can_go_up():
            act_up = QAction("Subir un nivel", menu)
            act_up.triggered.connect(self.go_up)
            menu.addAction(act_up)
        if not menu.isEmpty():
            menu.exec(self.mapToGlobal(pos))
