"""Mapa jerarquico (treemap) moderno TRODAI de alta opacidad y navegacion fluida.

- Fondo solido opaco (Obsidian Navy #0A0F1D en oscuro, Slate #EEF2F7 en claro) para eliminar
  la transparencia lavada sobre la grilla.
- Paleta arquitectonica de alta opacidad por categoria dominante y peso.
- Cabeceras de carpeta definidas en el primer nivel, borde 2px TRODAI Cyan/Blue en hover y
  ruta interactiva navegable (stack_nodes / jump_to_depth).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEasingCurve, QPoint, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QMenu, QToolTip, QWidget

from ..core.usage_telemetry import format_last_used
from ..storage.tree_analyzer import FolderNode
from .theme import MONO_FONT_FAMILY, UI_FONT_FAMILY, format_bytes

MIN_LABEL_W = 68.0
MIN_LABEL_H = 34.0
MAX_TILES = 60

# (fill_dark, border_dark, fill_light, border_light, legend_label)
_CATEGORY_STYLE: dict[str, tuple[str, str, str, str, str]] = {
    "Video": ("#15375C", "#0EA5E9", "#BFDBFE", "#2563EB", "Video"),
    "Modelos IA / Binarios": ("#232959", "#6366F1", "#C7D2FE", "#4F46E5", "IA / Bin"),
    "Documentos": ("#123E38", "#10B981", "#A7F3D0", "#059669", "Docs"),
    "Datos y Codigo": ("#16403B", "#14B8A6", "#99F6E4", "#0D9488", "Datos / Code"),
    "Archivos Comprimidos": ("#453013", "#F59E0B", "#FDE68A", "#D97706", "Comprimidos"),
    "Instaladores y Ejecutables": ("#462A16", "#FB923C", "#FED7AA", "#EA580C", "Instaladores"),
    "Imagenes": ("#47212C", "#F43F5E", "#FECDD3", "#E11D48", "Imagenes"),
    "Audio": ("#3C234B", "#A855F7", "#E9D5FF", "#9333EA", "Audio"),
    "Correo (Outlook)": ("#1E3A5F", "#38BDF8", "#BAE6FD", "#0284C7", "Correo"),
    "Maquinas virtuales": ("#3A2449", "#8B5CF6", "#DDD6FE", "#7C3AED", "VM / ISO"),
    "Registros y temporales": ("#333845", "#94A3B8", "#E2E8F0", "#64748B", "Logs / Temp"),
    "Otros": ("#17233E", "#3B82F6", "#CBD5E1", "#475569", "Otros"),
}

LEGEND_ITEMS: list[tuple[str, str]] = [
    ("Video", "Video"),
    ("Modelos IA / Binarios", "IA / Binarios"),
    ("Documentos", "Documentos"),
    ("Archivos Comprimidos", "Comprimidos"),
    ("Imagenes", "Imagenes"),
    ("Otros", "Otros / Mixto"),
]


def treemap_category_colors(category: str, dark: bool) -> tuple[QColor, QColor]:
    """Return high-opacity architectural (fill, border) QColors for a semantic category."""
    style = _CATEGORY_STYLE.get(category, _CATEGORY_STYLE["Otros"])
    fill_hex = style[0] if dark else style[2]
    border_hex = style[1] if dark else style[3]
    fill = QColor(fill_hex)
    fill.setAlpha(242)
    border = QColor(border_hex)
    border.setAlpha(210)
    return fill, border


@dataclass
class Tile:
    rect: QRectF
    node: FolderNode | None  # None = archivos sueltos de la carpeta actual
    depth: int
    label: str
    size: int
    category: str = "Otros"
    last_used_ts: float = 0.0


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
    """Treemap navegable de alta opacidad y estetica TRODAI sobre ``FolderNode``."""

    path_changed = Signal(str)
    reveal_requested = Signal(str)

    def __init__(self, palette_fn: Callable[[], dict[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette_fn = palette_fn
        self._root: FolderNode | None = None
        self._stack: list[FolderNode] = []
        self._tiles: list[Tile] = []
        self._hover: Tile | None = None
        self._zoom_from: QRectF | None = None
        self._zoom_t = 1.0
        self._zoom_anim = None
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

    def stack_nodes(self) -> list[FolderNode]:
        return list(self._stack)

    def _path_of(self, tile: Tile) -> str:
        """Resolve the filesystem path string associated with a treemap tile."""
        if tile.node is not None:
            return str(tile.node.path)
        return str(self.current.path) if self.current is not None else ""

    def can_go_up(self) -> bool:
        return len(self._stack) > 1

    def go_up(self) -> None:
        if self.can_go_up():
            self._stack.pop()
            self._relayout()

    def jump_to_depth(self, depth_idx: int) -> None:
        """Jump directly to an ancestor folder in the active drill-down stack."""
        if 0 <= depth_idx < len(self._stack) - 1:
            self._stack = self._stack[: depth_idx + 1]
            self._relayout()

    def enter(self, node: FolderNode) -> None:
        if node.children:
            start = next((t.rect for t in self._tiles if t.depth == 1 and t.node is node), None)
            self._stack.append(node)
            self._relayout()
            self._animate_zoom(start)

    def _animate_zoom(self, start: QRectF | None) -> None:
        """Acercamiento breve (180 ms) desde el bloque pulsado hasta toda el area."""
        from .fx import anims_on

        if start is None or start.isEmpty() or not anims_on():
            return
        self._zoom_from = QRectF(start)
        anim = QVariantAnimation(self)
        anim.setDuration(180)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._on_zoom_step)
        anim.finished.connect(self._end_zoom)
        self._zoom_anim = anim
        anim.start()

    def _on_zoom_step(self, t: float) -> None:
        self._zoom_t = float(t)
        self.update()

    def _end_zoom(self) -> None:
        self._zoom_from = None
        self._zoom_t = 1.0
        self.update()

    def breadcrumb(self) -> str:
        return " / ".join(n.name for n in self._stack)

    # ------------------------------------------------------------------ layout
    def _entries(self, node: FolderNode) -> list[tuple[FolderNode | None, int, str, str, float]]:
        kids = [c for c in node.children if c.size_bytes > 0][:MAX_TILES]
        entries: list[tuple[FolderNode | None, int, str, str, float]] = [
            (
                c,
                c.size_bytes,
                c.name,
                getattr(c, "dominant_category", "Otros"),
                float(getattr(c, "last_used_ts", 0.0)),
            )
            for c in kids
        ]
        loose = node.size_bytes - sum(c.size_bytes for c in node.children)
        if loose > node.size_bytes * 0.005 and loose > 0:
            entries.append(
                (
                    None,
                    loose,
                    "(archivos en esta carpeta)",
                    getattr(node, "dominant_category", "Otros"),
                    float(getattr(node, "last_used_ts", 0.0)),
                )
            )
        entries.sort(key=lambda e: e[1], reverse=True)
        return entries

    def _relayout(self) -> None:
        self._tiles = []
        self._hover = None
        cur = self.current
        if cur is not None and self.width() > 4 and self.height() > 4:
            area = QRectF(self.rect()).adjusted(4, 4, -4, -4)
            entries = self._entries(cur)
            rects = squarify([float(e[1]) for e in entries], area)
            for (node, size, label, cat, ts), raw_r in zip(entries, rects):
                r = raw_r.adjusted(1.5, 1.5, -1.5, -1.5)
                if r.width() <= 1 or r.height() <= 1:
                    continue
                self._tiles.append(Tile(r, node, 1, label, size, cat, ts))
                if node is not None and node.children and r.width() > 68 and r.height() > 54:
                    inner = r.adjusted(4, 22, -4, -4)
                    sub = self._entries(node)
                    for (snode, ssize, slabel, scat, sts), sr_raw in zip(sub, squarify([float(e[1]) for e in sub], inner)):
                        sr = sr_raw.adjusted(1.0, 1.0, -1.0, -1.0)
                        if sr.width() > 1 and sr.height() > 1:
                            self._tiles.append(Tile(sr, snode, 2, slabel, ssize, scat, sts))
        self.path_changed.emit(self.breadcrumb())
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    # ------------------------------------------------------------------ hit testing
    def tile_at(self, pos: QPoint) -> Tile | None:
        hit: Tile | None = None
        for t in self._tiles:  # nivel 2 se agrega despues -> gana si existe
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
        dark = pal.get("mode", "dark") != "light"

        # Fondo solido opaco propio para eliminar la transparencia lavada sobre la grilla
        canvas_bg = QColor("#0A0F1D" if dark else "#EEF2F7")
        canvas_border = QColor(pal.get("border_strong", "#33415F"))
        p.fillRect(self.rect(), canvas_bg)
        p.setPen(QPen(canvas_border, 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

        txt = QColor("#F8FAFC" if dark else "#0A0F1D")
        muted = QColor("#CBD5E1" if dark else "#334155")
        accent = QColor(pal.get("accent", "#0EA5E9"))

        if not self._tiles:
            p.setPen(muted)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Analice una carpeta para ver el mapa jerarquico.")
            p.end()
            return

        if self._zoom_from is not None and self._zoom_t < 1.0:
            full = QRectF(self.rect())
            t = self._zoom_t
            target = QRectF(
                self._zoom_from.x() + (full.x() - self._zoom_from.x()) * t,
                self._zoom_from.y() + (full.y() - self._zoom_from.y()) * t,
                self._zoom_from.width() + (full.width() - self._zoom_from.width()) * t,
                self._zoom_from.height() + (full.height() - self._zoom_from.height()) * t,
            )
            p.translate(target.x(), target.y())
            p.scale(target.width() / max(1.0, full.width()), target.height() / max(1.0, full.height()))

        total = max(1, self.current.size_bytes if self.current else 1)
        mono = QFont(MONO_FONT_FAMILY, 8)
        ui = QFont(UI_FONT_FAMILY, 9, QFont.Weight.DemiBold)
        fm_ui = QFontMetrics(ui)
        fm_mono = QFontMetrics(mono)
        level1 = [t for t in self._tiles if t.depth == 1]

        hovered_top = self._top_level_of(self._hover) if self._hover is not None else None

        # Nivel 1: bloques opacos por categoria + peso, con barra de cabecera definida
        for t in level1:
            base_fill, base_border = treemap_category_colors(t.category, dark)
            share = min(1.0, (t.size / total) * 2.2)
            fill = base_fill.lighter(112 + int(10 * share)) if dark else base_fill.darker(102 + int(6 * share))
            fill.setAlpha(248)
            if t.node is None:
                fill = QColor("#141D33" if dark else "#E2E8F0")
                fill.setAlpha(238)
            is_top_hover = hovered_top is t and self._hover is t
            if hovered_top is t:
                fill = fill.lighter(118) if dark else fill.darker(107)
            p.fillRect(t.rect, fill)

            nested = t.node is not None and bool(t.node.children) and t.rect.width() > 68 and t.rect.height() > 54
            if nested:
                hdr_rect = QRectF(t.rect.x(), t.rect.y(), t.rect.width(), 20.0)
                hdr_fill = fill.lighter(120) if dark else fill.darker(108)
                hdr_fill.setAlpha(255)
                p.fillRect(hdr_rect, hdr_fill)

            border_col = accent if is_top_hover else base_border
            p.setPen(QPen(border_col, 2 if is_top_hover else 1))
            p.drawRect(t.rect.adjusted(0, 0, -1, -1))

        # Nivel 2: subcarpetas nitidas y legibles dentro del bloque padre
        for idx, t in enumerate(self._tiles):
            if t.depth != 2:
                continue
            sub_fill, sub_border = treemap_category_colors(t.category, dark)
            shade = sub_fill.lighter(126 if (idx % 2 == 0) else 114) if dark else sub_fill.lighter(110 if (idx % 2 == 0) else 104)
            shade.setAlpha(232)
            if t is self._hover:
                shade = shade.lighter(122) if dark else shade.darker(110)
            p.fillRect(t.rect, shade)
            sub_border.setAlpha(220 if t is self._hover else 135)
            p.setPen(QPen(accent if t is self._hover else sub_border, 2 if t is self._hover else 1))
            p.drawRect(t.rect.adjusted(0, 0, -1, -1))

        # Textos nivel 1
        for t in level1:
            r = t.rect
            if r.width() < MIN_LABEL_W or r.height() < MIN_LABEL_H * 0.65:
                continue
            stat_txt = f"{format_bytes(t.size)} · {t.size * 100.0 / total:.1f}%"
            stat_w = fm_mono.horizontalAdvance(stat_txt) + 12
            nested = t.node is not None and bool(t.node.children) and r.width() > 68 and r.height() > 54
            same_line = nested and r.width() > stat_w + 85
            name_w = int(r.width() - 12 - (stat_w if same_line else 0))
            p.setFont(ui)
            p.setPen(txt)
            name = fm_ui.elidedText(t.label, Qt.TextElideMode.ElideRight, max(10, name_w))
            p.drawText(QRectF(r.x() + 6, r.y() + 2, name_w, 16), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
            p.setFont(mono)
            p.setPen(muted)
            if same_line:
                p.drawText(QRectF(r.right() - stat_w, r.y() + 2, stat_w - 6, 16), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, stat_txt)
            elif r.height() >= MIN_LABEL_H and not nested:
                p.drawText(QRectF(r.x() + 6, r.y() + 19, r.width() - 12, 14), Qt.AlignmentFlag.AlignLeft, stat_txt)

        # Textos nivel 2
        small_ui = QFont(UI_FONT_FAMILY, 8, QFont.Weight.Medium)
        fm_small = QFontMetrics(small_ui)
        for t in self._tiles:
            r = t.rect
            if t.depth != 2 or r.width() < 84 or r.height() < 32:
                continue
            p.setFont(small_ui)
            p.setPen(txt)
            p.drawText(
                QRectF(r.x() + 5, r.y() + 2, r.width() - 10, 14),
                Qt.AlignmentFlag.AlignLeft,
                fm_small.elidedText(t.label, Qt.TextElideMode.ElideRight, int(r.width() - 10)),
            )
            p.setFont(mono)
            p.setPen(muted)
            p.drawText(QRectF(r.x() + 5, r.y() + 16, r.width() - 10, 13), Qt.AlignmentFlag.AlignLeft, format_bytes(t.size))
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
            used_txt = format_last_used(t.last_used_ts) if t.last_used_ts else "Sin registro"
            QToolTip.showText(
                event.globalPosition().toPoint(),
                f"{t.label} [{t.category}]\n"
                f"{format_bytes(t.size)} ({t.size * 100.0 / total:.1f}% de la vista) | Ultimo uso: {used_txt}\n"
                f"{where}\n{hint}",
                self,
            )
        else:
            QToolTip.hideText()

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._hover is not None:
            self._hover = None
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.BackButton:
            self.go_up()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            t = self.tile_at(event.position().toPoint())
            top = self._top_level_of(t) if t is not None else None
            if top is not None and top.node is not None and top.node.children:
                self.enter(top.node)
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            t = self.tile_at(event.position().toPoint())
            target = (
                t.node.path
                if (t and t.node is not None)
                else (self.current.path if self.current is not None else None)
            )
            if target is not None:
                self.reveal_requested.emit(str(target))
                return
        super().mouseDoubleClickEvent(event)

    def _show_menu(self, pos: QPoint) -> None:
        t = self.tile_at(pos)
        menu = QMenu(self)
        if t is not None and t.node is not None and t.node.children:
            act_in = QAction(f"Entrar en '{t.label}'", menu)
            act_in.triggered.connect(lambda _=False, n=t.node: self.enter(n))
            menu.addAction(act_in)
        if self.can_go_up():
            act_up = QAction("Subir un nivel", menu)
            act_up.triggered.connect(self.go_up)
            menu.addAction(act_up)
        target = (
            t.node.path
            if (t and t.node is not None)
            else (self.current.path if self.current is not None else None)
        )
        if target is not None:
            act_exp = QAction("Ver en el Explorador de Windows", menu)
            act_exp.triggered.connect(lambda _=False, p=str(target): self.reveal_requested.emit(p))
            menu.addAction(act_exp)
        if menu.actions():
            menu.exec(self.mapToGlobal(pos))
