"""Reusable minimalist Obsidian/Alabaster Acrylic UI components (strictly 0px corners)."""

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class FlowLayout(QLayout):
    """v0.5.6: fila que pasa los botones a la linea siguiente cuando no caben (nunca los recorta)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m: QMargins = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = eff.x(), eff.y(), 0
        for item in self._items:
            w = item.widget()
            if w is not None and w.isHidden():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + self._spacing
            if next_x - self._spacing > eff.right() + 1 and line_h > 0:
                x = eff.x()
                y += line_h + self._spacing
                next_x = x + hint.width() + self._spacing
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


class AdaptiveButton(QPushButton):
    """v0.5.6: boton que muestra la variante de texto mas larga que cabe (nunca texto cortado).

    ``set_variants(["Elevar Admin (UAC)", "Admin"])``: con poco espacio usa la version corta y
    deja la completa en el tooltip. ``minimumSizeHint`` corresponde a la variante mas corta.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._variants: list[str] = [text] if text else []
        self._base_tip = ""
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def set_variants(self, variants: list[str]) -> None:
        clean = [v for v in variants if v]
        if not clean:
            return
        if clean != self._variants:
            self._variants = clean
            self.updateGeometry()
        self._pick()

    def setText(self, text: str) -> None:  # noqa: N802
        """Un texto fijo equivale a una sola variante (mantiene el comportamiento de QPushButton)."""
        self.set_variants([text])

    def setToolTip(self, tip: str) -> None:  # noqa: N802
        self._base_tip = tip
        super().setToolTip(tip)

    def variants(self) -> list[str]:
        return list(self._variants)

    def _padding(self) -> int:
        cur = super().text()
        return max(0, super().sizeHint().width() - self.fontMetrics().horizontalAdvance(cur))

    def hint_for(self, text: str) -> int:
        return self.fontMetrics().horizontalAdvance(text) + self._padding()

    def sizeHint(self) -> QSize:  # noqa: N802
        base = super().sizeHint()
        if self._variants:
            base.setWidth(self.hint_for(self._variants[0]))
        return base

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        base = super().sizeHint()
        if self._variants:
            base.setWidth(self.hint_for(self._variants[-1]))
        return base

    def _pick(self) -> None:
        if not self._variants:
            return
        avail = self.width()
        chosen = self._variants[-1]
        for v in self._variants:
            if self.hint_for(v) <= avail + 1:
                chosen = v
                break
        if super().text() != chosen:
            super().setText(chosen)
        full = self._variants[0]
        tip = self._base_tip or (full if chosen != full else "")
        if chosen != full and full not in tip:
            tip = f"{full}\n{tip}" if tip else full
        QPushButton.setToolTip(self, tip)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._pick()


# v0.5.6: roles visuales de las acciones especificas de cada pestana (ver theme.py).
ROLE_RESTORE = "RestoreAction"  # devolver / restablecer (reversible, tono salvia)
ROLE_MOVE = "MoveAction"  # mover a Cuarentena / Papelera / liberar espacio (reversible, tono ambar)
ROLE_RISK = "RiskAction"  # eliminar definitivo / cerrar procesos (tono oxido)


def set_button_role(btn: QPushButton, role: str) -> None:
    """Asignar un rol visual (objectName del QSS) y repintar el boton."""
    if btn.objectName() == role:
        return
    btn.setObjectName(role)
    btn.style().unpolish(btn)
    btn.style().polish(btn)
    btn.updateGeometry()


def find_clipped_buttons(root: QWidget) -> list[tuple[str, int, int]]:
    """Botones visibles cuyo texto actual no cabe en su ancho (auditoria visual y pruebas)."""
    out: list[tuple[str, int, int]] = []
    for b in root.findChildren(QPushButton):
        if not b.isVisibleTo(root) or not b.text().strip():
            continue
        need = b.hint_for(b.text()) if isinstance(b, AdaptiveButton) else b.sizeHint().width()
        if b.width() + 1 < need:
            out.append((b.text().strip(), b.width(), need))
    return out


class NotebookCanvas(QWidget):
    """Stationery desk notebook paper canvas with crumpled paper texture & pencil grid."""

    def __init__(self, theme_mode: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("RootCanvas")
        self._theme_mode = theme_mode
        self._paper_cache: dict[tuple[str, int, int], QPixmap] = {}

    def set_theme_mode(self, mode: str) -> None:
        self._theme_mode = mode
        self.update()

    def _get_paper_pixmap(self, width: int, height: int) -> QPixmap:
        w = max(320, width)
        h = max(240, height)
        key = (self._theme_mode, w, h)
        if key in self._paper_cache:
            return self._paper_cache[key]

        import random

        pix = QPixmap(w, h)
        is_light = self._theme_mode == "light"
        base_bg = QColor(244, 239, 228, 240) if is_light else QColor(23, 23, 21, 232)
        pix.fill(base_bg)

        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rng = random.Random(202603)

        # Subtle multi-faceted paper creases (shadow + paper-ridge highlight gradients)
        for _ in range(18):
            cx = rng.uniform(0, w)
            cy = rng.uniform(0, h)
            dx = rng.uniform(110, 320)
            dy = rng.uniform(-160, 160)
            nx = -dy * 0.18
            ny = dx * 0.18

            grad = QLinearGradient(cx, cy, cx + nx, cy + ny)
            if is_light:
                grad.setColorAt(0.0, QColor(125, 114, 94, 0))
                grad.setColorAt(0.42, QColor(125, 114, 94, 18))
                grad.setColorAt(0.50, QColor(255, 253, 247, 36))
                grad.setColorAt(0.62, QColor(125, 114, 94, 12))
                grad.setColorAt(1.0, QColor(125, 114, 94, 0))
            else:
                grad.setColorAt(0.0, QColor(0, 0, 0, 0))
                grad.setColorAt(0.42, QColor(0, 0, 0, 34))
                grad.setColorAt(0.50, QColor(236, 230, 216, 13))
                grad.setColorAt(0.62, QColor(0, 0, 0, 22))
                grad.setColorAt(1.0, QColor(0, 0, 0, 0))

            poly = QPolygonF(
                [
                    QPointF(cx - dx, cy - dy),
                    QPointF(cx + dx, cy + dy),
                    QPointF(cx + dx + nx, cy + dy + ny),
                    QPointF(cx - dx + nx, cy - dy + ny),
                ]
            )
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawPolygon(poly)

            # Fine crisp fold ridge line
            ridge_color = QColor(115, 104, 86, 20) if is_light else QColor(235, 228, 212, 14)
            p.setPen(QPen(ridge_color, 1))
            p.drawLine(QPointF(cx - dx * 0.7, cy - dy * 0.7), QPointF(cx + dx * 0.7, cy + dy * 0.7))

        # Organic paper fiber flecks
        fiber_color = QColor(110, 102, 88, 20) if is_light else QColor(225, 218, 204, 14)
        p.setPen(QPen(fiber_color, 1))
        for _ in range(420):
            fx = rng.randint(0, w)
            fy = rng.randint(0, h)
            p.drawLine(fx, fy, fx + rng.randint(-3, 3), fy + rng.randint(-2, 2))

        p.end()
        if len(self._paper_cache) > 6:
            self._paper_cache.clear()
        self._paper_cache[key] = pix
        return pix

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        rect = self.rect()

        painter.drawPixmap(0, 0, self._get_paper_pixmap(rect.width(), rect.height()))

        if self._theme_mode == "light":
            minor_grid = QColor(126, 118, 102, 34)
            major_grid = QColor(112, 104, 88, 54)
            margin_color = QColor(172, 84, 74, 74)
            tick_color = QColor(58, 54, 48, 85)
        else:
            minor_grid = QColor(228, 222, 208, 18)
            major_grid = QColor(228, 222, 208, 32)
            margin_color = QColor(196, 128, 116, 48)
            tick_color = QColor(228, 222, 208, 70)

        step = 24
        for idx, x in enumerate(range(step, rect.width(), step), start=1):
            painter.setPen(QPen(major_grid if idx % 5 == 0 else minor_grid, 1))
            painter.drawLine(x, 0, x, rect.height())
        for idx, y in enumerate(range(step, rect.height(), step), start=1):
            painter.setPen(QPen(major_grid if idx % 5 == 0 else minor_grid, 1))
            painter.drawLine(0, y, rect.width(), y)

        # Double stationery notebook vertical margin line after sidebar
        painter.setPen(QPen(margin_color, 1))
        painter.drawLine(252, 0, 252, rect.height())
        painter.drawLine(256, 0, 256, rect.height())

        # Architectural corner registration ticks
        painter.setPen(QPen(tick_color, 1))
        painter.drawLine(rect.width() - 18, 10, rect.width() - 8, 10)
        painter.drawLine(rect.width() - 10, 10, rect.width() - 10, 20)
        painter.end()
        super().paintEvent(event)


class NumericTableItem(QTableWidgetItem):
    """Table item sorting by numeric UserRole key instead of lexicographical text."""

    def __init__(self, display_text: str, sort_value: float | int) -> None:
        super().__init__(display_text)
        self.setData(Qt.ItemDataRole.UserRole, float(sort_value))

    def __lt__(self, other: QTableWidgetItem) -> bool:
        a = self.data(Qt.ItemDataRole.UserRole)
        b = other.data(Qt.ItemDataRole.UserRole)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return float(a) < float(b)
        # v0.5.2: NUNCA llamar super().__lt__(): en PySide6 vuelve a despachar al override de
        # Python y entra en recursion infinita -> desbordamiento de pila 0xc0000005 en shiboken6.
        return _text_key(self.text()) < _text_key(other.text())


def _text_key(text: str) -> str:
    return (text or "").casefold()


class NumericTreeItem(QTreeWidgetItem):
    """Tree item sorting numerically on columns that store UserRole byte/count values."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        col = tree.sortColumn() if tree is not None else 0
        a = self.data(col, Qt.ItemDataRole.UserRole)
        b = other.data(col, Qt.ItemDataRole.UserRole)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return float(a) < float(b)
        # v0.5.2: comparacion textual propia (ver NumericTableItem); super().__lt__ recursaba
        # al ordenar por la columna CARPETA (sin UserRole) y cerraba la app (crash 17:37).
        return _text_key(self.text(col)) < _text_key(other.text(col))


def configure_sortable_table(table: QTableWidget) -> None:
    """Apply consistent non-editable row-selection and clickable column sorting."""
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(True)
    table.setSortingEnabled(True)
    table.horizontalHeader().setSortIndicatorShown(True)

from .svg_icons import load_svg_pixmap
from .theme import MONO_FONT_FAMILY, get_palette


class GlassPanel(QFrame):
    """Translucent 0px rectangular container with 1px hairline border."""

    def __init__(self, elevated: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GlassPanelElevated" if elevated else "GlassPanel")


class StatusTag(QLabel):
    """Minimalist custom inline tag badge (0px, 1px hairline border, IBM Plex Mono)."""

    TONES = {
        "neutral": ("#9BA3AE", "rgba(155, 163, 174, 65)", "rgba(155, 163, 174, 16)"),
        "active": ("#94A3B8", "rgba(148, 163, 184, 95)", "rgba(148, 163, 184, 24)"),
        "ok": ("#3D8B68", "rgba(61, 139, 104, 90)", "rgba(61, 139, 104, 20)"),
        "warn": ("#B47B2B", "rgba(180, 123, 43, 95)", "rgba(180, 123, 43, 20)"),
        "risk": ("#B44C4C", "rgba(180, 76, 76, 95)", "rgba(180, 76, 76, 22)"),
    }

    def __init__(self, text: str, tone: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(text.upper(), parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_tone(text, tone)

    def set_tone(self, text: str, tone: str = "neutral") -> None:
        self.setText(text.upper())
        fg, border, bg = self.TONES.get(tone, self.TONES["neutral"])
        self.setStyleSheet(
            f"""
            QLabel {{
                font-family: "{MONO_FONT_FAMILY}", monospace;
                font-size: 9px;
                font-weight: 500;
                letter-spacing: 0.9px;
                color: {fg};
                border: 1px solid {border};
                background-color: {bg};
                padding: 2px 6px;
            }}
            """
        )


class SharpMetricCell(GlassPanel):
    """Single clean telemetry block with icon, micro-label, monospace figure, and 3px bar."""

    def __init__(
        self,
        title: str,
        icon_name: str,
        parent: QWidget | None = None,
        compact: bool = False,
    ) -> None:
        super().__init__(elevated=False, parent=parent)
        self._icon_name = icon_name
        layout = QVBoxLayout(self)
        # v0.5.7: modo compacto (Resumen) para dejar altura al historial grafico.
        vpad = 10 if compact else 14
        layout.setContentsMargins(16, vpad, 16, vpad)
        layout.setSpacing(4 if compact else 8)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.icon_lbl = QLabel()
        self.icon_lbl.setPixmap(load_svg_pixmap(icon_name, color=get_palette("dark")["text_secondary"], size=14))
        header.addWidget(self.icon_lbl)

        self.title_lbl = QLabel(title.upper())
        self.title_lbl.setObjectName("SectionLabel")
        header.addWidget(self.title_lbl)
        header.addStretch()

        self.tag = StatusTag("LECTURA", "neutral")
        header.addWidget(self.tag)
        layout.addLayout(header)

        self.value_lbl = QLabel("--")
        self.value_lbl.setObjectName("MetricValueCompact" if compact else "MetricValue")
        layout.addWidget(self.value_lbl)

        self.sub_lbl = QLabel("Sincronizando telemetria")
        self.sub_lbl.setObjectName("PageSubtitle")
        layout.addWidget(self.sub_lbl)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)

    def refresh_theme(self, mode: str) -> None:
        color = get_palette(mode)["text_secondary"]
        self.icon_lbl.setPixmap(load_svg_pixmap(self._icon_name, color=color, size=14))

    def set_title(self, title: str) -> None:
        self.title_lbl.setText(title.upper())

    def update_metric(
        self,
        value_text: str,
        subtitle: str,
        percent: int,
        tag_text: str,
        tone: str = "neutral",
    ) -> None:
        self.value_lbl.setText(value_text)
        self.sub_lbl.setText(subtitle)
        self.bar.setValue(max(0, min(100, percent)))
        self.tag.set_tone(tag_text, tone)
