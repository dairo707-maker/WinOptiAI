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
    """TRODAI architectural blueprint canvas (Obsidian Navy #0A0F1D / Crisp White #F8FAFC)."""

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

        pix = QPixmap(w, h)
        is_light = self._theme_mode == "light"
        base_bg = QColor(248, 250, 252, 246) if is_light else QColor(10, 15, 29, 242)
        pix.fill(base_bg)

        p = QPainter(pix)
        # Subtle TRODAI architectural gradient glow in top-right corner
        grad = QLinearGradient(0, 0, w, h)
        if is_light:
            grad.setColorAt(0.0, QColor(255, 255, 255, 45))
            grad.setColorAt(0.55, QColor(238, 242, 247, 15))
            grad.setColorAt(1.0, QColor(59, 130, 246, 12))
        else:
            grad.setColorAt(0.0, QColor(14, 165, 233, 12))
            grad.setColorAt(0.45, QColor(15, 22, 40, 0))
            grad.setColorAt(1.0, QColor(59, 130, 246, 14))
        p.fillRect(0, 0, w, h, grad)
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
            minor_grid = QColor(59, 130, 246, 15)
            major_grid = QColor(37, 99, 235, 26)
            axis_color = QColor(37, 99, 235, 45)
            tick_color = QColor(37, 99, 235, 110)
        else:
            minor_grid = QColor(59, 130, 246, 18)
            major_grid = QColor(14, 165, 233, 28)
            axis_color = QColor(14, 165, 233, 46)
            tick_color = QColor(14, 165, 233, 120)

        step = 24
        for idx, x in enumerate(range(step, rect.width(), step), start=1):
            painter.setPen(QPen(major_grid if idx % 5 == 0 else minor_grid, 1))
            painter.drawLine(x, 0, x, rect.height())
        for idx, y in enumerate(range(step, rect.height(), step), start=1):
            painter.setPen(QPen(major_grid if idx % 5 == 0 else minor_grid, 1))
            painter.drawLine(0, y, rect.width(), y)

        # Architectural blueprint registration seam after sidebar
        painter.setPen(QPen(axis_color, 1))
        painter.drawLine(248, 0, 248, rect.height())

        # Polygonal 0px corner registration ticks
        painter.setPen(QPen(tick_color, 1))
        painter.drawLine(rect.width() - 20, 10, rect.width() - 10, 10)
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


def semaphore_hex(tone: str, theme_mode: str = "dark") -> str:
    """Return high-contrast readable semaphore color (no neon) for TRODAI dark/light modes."""
    dark = theme_mode != "light"
    mapping = {
        "ok": "#34D399" if dark else "#047857",
        "warn": "#F59E0B" if dark else "#B45309",
        "risk": "#F87171" if dark else "#B91C1C",
        "active": "#0EA5E9" if dark else "#2563EB",
        "neutral": "#94A3B8" if dark else "#4A5568",
    }
    return mapping.get(tone, mapping["neutral"])


class SemaphoreDot(QWidget):
    """Polygonal 0px geometric traffic-light indicator (ok / warn / risk / active / neutral)."""

    def __init__(self, tone: str = "neutral", theme_mode: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tone = tone
        self._theme_mode = theme_mode
        self.setFixedSize(11, 11)

    def set_tone(self, tone: str, theme_mode: str | None = None) -> None:
        self._tone = tone
        if theme_mode is not None:
            self._theme_mode = theme_mode
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        c = QColor(semaphore_hex(self._tone, self._theme_mode))
        glow = QColor(c)
        glow.setAlpha(70)
        painter.fillRect(0, 0, 10, 10, glow)
        painter.fillRect(2, 2, 6, 6, c)
        painter.setPen(QPen(c, 1))
        painter.drawRect(0, 0, 9, 9)
        painter.end()


class StatusTag(QLabel):
    """Minimalist TRODAI inline tag badge (0px, 1px border, JetBrains Mono)."""

    TONES = {
        "neutral": ("#94A3B8", "rgba(148, 163, 184, 75)", "rgba(148, 163, 184, 18)"),
        "active": ("#0EA5E9", "rgba(14, 165, 233, 115)", "rgba(14, 165, 233, 24)"),
        "ok": ("#10B981", "rgba(16, 185, 129, 110)", "rgba(16, 185, 129, 22)"),
        "warn": ("#D97706", "rgba(217, 119, 6, 115)", "rgba(217, 119, 6, 22)"),
        "risk": ("#DC2626", "rgba(220, 38, 38, 115)", "rgba(220, 38, 38, 22)"),
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
                font-family: "{MONO_FONT_FAMILY}", "IBM Plex Mono", monospace;
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
    """Clean TRODAI telemetry block with semaphore signal, monospace figure, and tone-colored bar."""

    def __init__(
        self,
        title: str,
        icon_name: str,
        parent: QWidget | None = None,
        compact: bool = False,
        ultra_compact: bool = False,
    ) -> None:
        super().__init__(elevated=False, parent=parent)
        self._icon_name = icon_name
        self._theme_mode = "dark"
        layout = QVBoxLayout(self)
        if ultra_compact:
            layout.setContentsMargins(12, 8, 12, 8)
            layout.setSpacing(3)
        else:
            vpad = 10 if compact else 14
            layout.setContentsMargins(16, vpad, 16, vpad)
            layout.setSpacing(4 if compact else 8)

        header = QHBoxLayout()
        header.setSpacing(6 if ultra_compact else 8)
        self.icon_lbl = QLabel()
        self.icon_lbl.setPixmap(load_svg_pixmap(icon_name, color=get_palette("dark")["text_secondary"], size=13 if ultra_compact else 14))
        header.addWidget(self.icon_lbl)

        self.semaphore = SemaphoreDot("neutral", "dark")
        header.addWidget(self.semaphore)

        self.title_lbl = QLabel(title.upper())
        self.title_lbl.setObjectName("SectionLabel")
        header.addWidget(self.title_lbl)
        header.addStretch()

        self.tag = StatusTag("OK", "neutral")
        header.addWidget(self.tag)
        layout.addLayout(header)

        self.value_lbl = QLabel("--")
        self.value_lbl.setObjectName("MetricValueCompact" if (compact or ultra_compact) else "MetricValue")
        layout.addWidget(self.value_lbl)

        self.sub_lbl = QLabel("Sincronizando")
        self.sub_lbl.setObjectName("PageSubtitle")
        layout.addWidget(self.sub_lbl)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)

    def refresh_theme(self, mode: str) -> None:
        self._theme_mode = mode
        color = get_palette(mode)["text_secondary"]
        self.icon_lbl.setPixmap(load_svg_pixmap(self._icon_name, color=color, size=14))
        self.semaphore.set_tone(self.semaphore._tone, mode)

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
        if self.bar.property("tone") != tone:
            self.bar.setProperty("tone", tone)
            self.bar.style().unpolish(self.bar)
            self.bar.style().polish(self.bar)
        self.semaphore.set_tone(tone, self._theme_mode)
        self.tag.set_tone(tag_text, tone)


class SectionBenefitStrip(GlassPanel):
    """Collapsible 0px architectural guide explaining what each section improves and its safety level."""

    def __init__(self, section_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._section_key = section_key
        self._expanded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 7, 12, 7)
        outer.setSpacing(6)

        hdr = QHBoxLayout()
        hdr.setSpacing(8)
        self.badge = StatusTag("GUIA", "neutral")
        hdr.addWidget(self.badge)

        self.title_lbl = QLabel("")
        self.title_lbl.setObjectName("MonoValue")
        self.title_lbl.setWordWrap(True)
        hdr.addWidget(self.title_lbl, stretch=1)

        self.toggle_btn = QPushButton("Ver que mejora")
        self.toggle_btn.setObjectName("GhostAction")
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._toggle)
        hdr.addWidget(self.toggle_btn)
        outer.addLayout(hdr)

        self.body_widget = QWidget()
        bl = QVBoxLayout(self.body_widget)
        bl.setContentsMargins(0, 2, 0, 2)
        bl.setSpacing(4)

        self.improves_lbl = QLabel("")
        self.improves_lbl.setObjectName("PageSubtitle")
        self.improves_lbl.setWordWrap(True)
        bl.addWidget(self.improves_lbl)

        self.safety_lbl = QLabel("")
        self.safety_lbl.setObjectName("MonoValue")
        self.safety_lbl.setWordWrap(True)
        bl.addWidget(self.safety_lbl)

        self.body_widget.setVisible(False)
        outer.addWidget(self.body_widget)
        self.set_section(section_key)

    def set_section(self, section_key: str) -> None:
        from ..core.help_catalog import SECTION_BENEFITS

        self._section_key = section_key
        data = SECTION_BENEFITS.get(section_key)
        if not data:
            self.setVisible(False)
            return
        self.setVisible(True)
        self.title_lbl.setText(data["title"])
        self.improves_lbl.setText(f"Que mejora: {data['improves']}")
        self.safety_lbl.setText(f"Seguridad: {data['safety']}")

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self.body_widget.setVisible(self._expanded)
        self.toggle_btn.setText("Ocultar" if self._expanded else "Ver que mejora")

    def _toggle(self) -> None:
        self.set_expanded(not self._expanded)
