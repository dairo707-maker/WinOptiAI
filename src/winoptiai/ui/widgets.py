"""Reusable minimalist Obsidian/Alabaster Acrylic UI components (strictly 0px corners)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEasingCurve, QEvent, QMargins, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLayoutItem,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .svg_icons import load_svg_pixmap
from .theme import MONO_FONT_FAMILY, UI_FONT_FAMILY, get_palette

if TYPE_CHECKING:
    from ..core.sre_policy import SREPolicyEngine


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
    """Apply consistent non-editable row-selection, pixel scroll, eliding, and column sorting."""
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(True)
    table.setSortingEnabled(True)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.horizontalHeader().setSortIndicatorShown(True)
    table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)


def _header_labels_of(view: QTableWidget | QTreeWidget, count: int) -> list[str]:
    labels: list[str] = []
    if isinstance(view, QTableWidget):
        for i in range(count):
            it = view.horizontalHeaderItem(i)
            labels.append(it.text() if it is not None else "")
    else:
        it = view.headerItem()
        for i in range(count):
            labels.append(it.text(i) if it is not None else "")
    return labels


def _auto_fit_column(view: QTableWidget | QTreeWidget, col: int) -> None:
    hdr = view.horizontalHeader() if isinstance(view, QTableWidget) else view.header()
    if col < 0 or col >= hdr.count():
        return
    mins: list[int] = list(getattr(hdr, "_winopti_col_mins", []))
    col_min = mins[col] if col < len(mins) else 64
    fm = QFontMetrics(view.font())
    best = col_min
    if isinstance(view, QTableWidget):
        limit = min(view.rowCount(), 300)
        for r in range(limit):
            it = view.item(r, col)
            if it is not None:
                txt = it.text()
                if txt:
                    best = max(best, fm.horizontalAdvance(txt) + 28)
    else:
        # Measure top-level rows and first-level children for tree views (indentation on col 0).
        indent = 32 if col == 0 else 0
        for i in range(min(view.topLevelItemCount(), 200)):
            it = view.topLevelItem(i)
            if it is not None:
                txt = it.text(col)
                if txt:
                    best = max(best, fm.horizontalAdvance(txt) + 28 + indent)
                if it.isExpanded():
                    for c_i in range(min(it.childCount(), 100)):
                        ch = it.child(c_i)
                        if ch is not None and ch.text(col):
                            best = max(best, fm.horizontalAdvance(ch.text(col)) + 28 + indent + 20)
    hdr.resizeSection(col, max(col_min, min(best, 620)))


def configure_interactive_columns(
    view: QTableWidget | QTreeWidget,
    default_widths: list[int],
    *,
    policy: SREPolicyEngine | None = None,
    storage_key: str = "",
    min_widths: list[int] | None = None,
) -> None:
    """Enable manual dragging + horizontal scroll + header safety minimums + optional width persistence."""
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    if isinstance(view, QTreeWidget):
        view.setTextElideMode(Qt.TextElideMode.ElideRight)

    hdr = view.horizontalHeader() if isinstance(view, QTableWidget) else view.header()
    count = hdr.count()
    if count <= 0:
        return

    hdr.setStretchLastSection(False)
    hdr.setMinimumSectionSize(54)

    fm_hdr = QFontMetrics(hdr.font())
    mono_hdr_font = QFont(MONO_FONT_FAMILY)
    mono_hdr_font.setPixelSize(11)
    fm_mono = QFontMetrics(mono_hdr_font)
    labels = _header_labels_of(view, count)

    col_mins: list[int] = []
    for i in range(count):
        lbl = labels[i]
        adv = max(fm_hdr.horizontalAdvance(lbl), fm_mono.horizontalAdvance(lbl))
        hdr_min = adv + int(len(lbl) * 1.1) + 38
        floor_w = min_widths[i] if min_widths and i < len(min_widths) else 64
        col_mins.append(max(hdr_min, floor_w))

    pending_timer = getattr(hdr, "_winopti_save_timer", None)
    if pending_timer is not None:
        pending_timer.stop()

    hdr._winopti_restoring = True
    try:
        hdr._winopti_storage_key = storage_key
        hdr._winopti_policy = policy
        hdr._winopti_col_mins = col_mins

        saved = policy.get_table_widths(storage_key) if (policy is not None and storage_key) else None
        for i in range(count):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            col_min = col_mins[i]
            if saved is not None and len(saved) == count:
                w = max(col_min, min(int(saved[i]), 1600))
            else:
                base_w = default_widths[i] if i < len(default_widths) else 120
                w = max(base_w, col_min)
            hdr.resizeSection(i, w)
    finally:
        hdr._winopti_restoring = False

    if not getattr(hdr, "_winopti_interactive_wired", False):
        save_timer = QTimer(hdr)
        save_timer.setSingleShot(True)
        save_timer.setInterval(350)

        def _flush_save() -> None:
            pol = getattr(hdr, "_winopti_policy", None)
            skey = str(getattr(hdr, "_winopti_storage_key", "") or "")
            if pol is None or not skey or hdr.count() <= 0:
                return
            pol.set_table_widths(skey, [hdr.sectionSize(idx) for idx in range(hdr.count())])

        def _on_resized(_logical: int, _old: int, _new: int) -> None:
            if getattr(hdr, "_winopti_restoring", False):
                return
            save_timer.start()

        save_timer.timeout.connect(_flush_save)
        hdr.sectionResized.connect(_on_resized)
        hdr.sectionHandleDoubleClicked.connect(lambda idx: _auto_fit_column(view, idx))
        hdr._winopti_save_timer = save_timer
        hdr._winopti_save_fn = _flush_save
        hdr._winopti_interactive_wired = True


def flush_column_width_saves(view: QTableWidget | QTreeWidget) -> None:
    """Flush any pending debounced column-width save immediately (useful in tests)."""
    hdr = view.horizontalHeader() if isinstance(view, QTableWidget) else view.header()
    timer = getattr(hdr, "_winopti_save_timer", None)
    fn = getattr(hdr, "_winopti_save_fn", None)
    if timer is not None:
        timer.stop()
    if callable(fn):
        fn()


def apply_table_tooltips(table: QTableWidget) -> None:
    """Attach full-text hover tooltips to table cells that lack an explicit custom tooltip."""
    rows = table.rowCount()
    cols = table.columnCount()
    for r in range(rows):
        for c in range(cols):
            it = table.item(r, c)
            if it is not None and it.text() and not it.toolTip():
                it.setToolTip(it.text())


def _apply_tree_item_tooltips(item: QTreeWidgetItem, cols: int) -> None:
    for c in range(cols):
        txt = item.text(c)
        if txt and not item.toolTip(c):
            item.setToolTip(c, txt)
    for idx in range(item.childCount()):
        ch = item.child(idx)
        if ch is not None:
            _apply_tree_item_tooltips(ch, cols)


def apply_tree_tooltips(tree: QTreeWidget) -> None:
    """Attach full-text hover tooltips to loaded tree items that lack custom tooltips."""
    cols = tree.columnCount()
    for i in range(tree.topLevelItemCount()):
        it = tree.topLevelItem(i)
        if it is not None:
            _apply_tree_item_tooltips(it, cols)


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
    """100% opaque solid flat technical 0px status badge (zero transparency)."""

    _SOLID_THEMES: dict[str, dict[str, tuple[str, str, str]]] = {
        "dark": {
            "neutral": ("#161E2E", "#2A364B", "#CBD5E1"),
            "active": ("#1A2438", "#334155", "#E2E8F0"),
            "ok": ("#152E28", "#2B6A5A", "#6EE7B7"),
            "warn": ("#352814", "#78561F", "#FCD34D"),
            "risk": ("#3A191E", "#7F2933", "#FCA5A5"),
        },
        "light": {
            "neutral": ("#EEF2F6", "#CBD5E1", "#334155"),
            "active": ("#E2E8F0", "#CBD5E1", "#0F172A"),
            "ok": ("#DCFCE7", "#86EFAC", "#166534"),
            "warn": ("#FEF3C7", "#FCD34D", "#92400E"),
            "risk": ("#FEE2E2", "#FCA5A5", "#991B1B"),
        },
    }

    def __init__(
        self,
        text: str,
        tone: str = "neutral",
        parent: QWidget | None = None,
        theme_mode: str = "dark",
    ) -> None:
        super().__init__(text.upper(), parent)
        self._tone = tone
        self._mode = "light" if theme_mode == "light" else "dark"
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_tone(text, tone, theme_mode=self._mode)

    def apply_theme(self, theme_mode: str) -> None:
        norm = "light" if theme_mode == "light" else "dark"
        if norm != self._mode:
            self._mode = norm
            self.set_tone(self.text(), self._tone, theme_mode=norm)

    def set_tone(self, text: str, tone: str = "neutral", theme_mode: str | None = None) -> None:
        if theme_mode is not None:
            self._mode = "light" if theme_mode == "light" else "dark"
        self._tone = tone
        self.setText(text.upper())
        palette = self._SOLID_THEMES[self._mode]
        fg_default = palette["neutral"]
        bg, border, fg = palette.get(tone, fg_default)
        sig = (self._mode, bg, border, fg)
        if getattr(self, "_last_tag_sig", None) != sig:
            self._last_tag_sig = sig
            self.setStyleSheet(
                f"QLabel {{"
                f' font-family: "{MONO_FONT_FAMILY}", "IBM Plex Mono", monospace;'
                f" font-size: 8.5px; font-weight: 500; letter-spacing: 0.5px;"
                f" color: {fg}; border: 1px solid {border};"
                f" background-color: {bg}; padding: 2px 6px;"
                f" }}"
            )
        self.adjustSize()


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
            layout.setContentsMargins(10, 7, 10, 7)
            layout.setSpacing(3)
        else:
            vpad = 10 if compact else 14
            layout.setContentsMargins(16, vpad, 16, vpad)
            layout.setSpacing(4 if compact else 8)

        header = QHBoxLayout()
        header.setSpacing(4 if ultra_compact else 8)
        self.icon_lbl = QLabel()
        self.icon_lbl.setPixmap(load_svg_pixmap(icon_name, color=get_palette("dark")["text_secondary"], size=13 if ultra_compact else 14))
        self.icon_lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        header.addWidget(self.icon_lbl)

        self.semaphore = SemaphoreDot("neutral", "dark")
        header.addWidget(self.semaphore)

        self.title_lbl = QLabel(title.upper())
        self.title_lbl.setObjectName("SectionLabel")
        header.addWidget(self.title_lbl, stretch=1)

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
        self.tag.apply_theme(mode)

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
        self.title_lbl = QLabel("")
        self.title_lbl.setObjectName("CardTitle")
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
        self.improves_lbl.setObjectName("BodyText")
        self.improves_lbl.setWordWrap(True)
        bl.addWidget(self.improves_lbl)

        self.safety_lbl = QLabel("")
        self.safety_lbl.setObjectName("BodyText")
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


class SlidingSegmentedControl(QWidget):
    """Selector horizontal fluido con superficies solidas neutras (portado de PDF Lector TRODAI)."""

    selection_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._options: list[tuple[str, str]] = []
        self._current_index = 0
        self._hover_index = -1
        self._mode = "dark"
        self._animate = True
        self._pill_x = 2.0
        self._pill_w = 56.0

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuint)
        self._anim.valueChanged.connect(self._on_anim_value)

        self.setFixedHeight(32)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def set_options(self, options: list[tuple[str, str]]) -> None:
        self._options = list(options)
        self._current_index = min(self._current_index, max(0, len(self._options) - 1))
        self.updateGeometry()
        self._snap_pill()
        self.update()

    def set_animations_enabled(self, enabled: bool) -> None:
        self._animate = bool(enabled)

    def apply_theme(self, mode: str) -> None:
        self._mode = "light" if mode == "light" else "dark"
        self.update()

    def current_key(self) -> str:
        if 0 <= self._current_index < len(self._options):
            return self._options[self._current_index][0]
        return ""

    def set_current(self, key: str, *, animate: bool = True, emit_signal: bool = False) -> None:
        for idx, (opt_key, _) in enumerate(self._options):
            if opt_key == key:
                self._select_index(idx, animate=animate, emit_signal=emit_signal)
                return

    def sizeHint(self) -> QSize:  # noqa: N802
        if not self._options:
            return QSize(110, 32)
        fm = QFontMetrics(self.font())
        max_txt = max(fm.horizontalAdvance(label) for _, label in self._options)
        seg_w = max(56, max_txt + 20)
        return QSize(seg_w * len(self._options) + 4, 32)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def _segment_rect(self, index: int) -> QRectF:
        count = max(1, len(self._options))
        inner_w = max(10.0, float(self.width() - 4))
        seg_w = inner_w / count
        return QRectF(2.0 + index * seg_w, 2.0, seg_w, float(self.height() - 4))

    def _snap_pill(self) -> None:
        rect = self._segment_rect(self._current_index)
        self._pill_x = rect.x()
        self._pill_w = rect.width()

    def _on_anim_value(self, value: object) -> None:
        if isinstance(value, QRectF):
            self._pill_x = value.x()
            self._pill_w = value.width()
        else:
            self._pill_x = float(value)
        self.update()

    def _select_index(self, idx: int, *, animate: bool, emit_signal: bool) -> None:
        if not (0 <= idx < len(self._options)):
            return
        changed = idx != self._current_index
        self._current_index = idx
        target = self._segment_rect(idx)

        if animate and self._animate and self.isVisible() and self.width() > 20:
            self._anim.stop()
            self._anim.setStartValue(QRectF(self._pill_x, 2.0, self._pill_w, target.height()))
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._anim.stop()
            self._pill_x = target.x()
            self._pill_w = target.width()
            self.update()

        if changed and emit_signal:
            self.selection_changed.emit(self._options[idx][0])

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._anim.state() != QVariantAnimation.State.Running:
            self._snap_pill()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        count = max(1, len(self._options))
        seg_w = max(1.0, (self.width() - 4) / count)
        idx = int((event.position().x() - 2.0) / seg_w)
        idx = idx if 0 <= idx < len(self._options) else -1
        if idx != self._hover_index:
            self._hover_index = idx
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_index = -1
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._options:
            seg_w = max(1.0, (self.width() - 4) / len(self._options))
            idx = max(0, min(len(self._options) - 1, int((event.position().x() - 2.0) / seg_w)))
            self._select_index(idx, animate=True, emit_signal=True)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = get_palette(self._mode)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(p["bg_track"]))
        painter.setPen(QPen(QColor(p["border_hairline"]), 1))
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)

        if not self._options:
            painter.end()
            return

        if 0 <= self._hover_index < len(self._options) and self._hover_index != self._current_index:
            hr = self._segment_rect(self._hover_index)
            painter.fillRect(hr.toRect(), QColor(p["bg_hover"]))

        pill_rect = QRect(int(round(self._pill_x)), 2, max(8, int(round(self._pill_w))), self.height() - 4)
        painter.fillRect(pill_rect, QColor(p["bg_active"]))
        painter.setPen(QPen(QColor(p["border_selected"]), 1))
        painter.drawRect(pill_rect.adjusted(0, 0, -1, -1))
        sheen = "#475569" if self._mode == "dark" else "#FFFFFF"
        painter.setPen(QPen(QColor(sheen), 1))
        painter.drawLine(pill_rect.left() + 1, pill_rect.top() + 1, pill_rect.right() - 1, pill_rect.top() + 1)

        font = QFont(UI_FONT_FAMILY, 9)
        font.setFamilies([UI_FONT_FAMILY, "Instrument Sans", "Segoe UI"])
        for idx, (_, label) in enumerate(self._options):
            sr = self._segment_rect(idx).toRect()
            is_sel = idx == self._current_index
            font.setWeight(QFont.Weight.Bold if is_sel else QFont.Weight.Medium)
            painter.setFont(font)
            painter.setPen(QColor(p["text_primary"] if is_sel else p["text_secondary"]))
            painter.drawText(sr, Qt.AlignmentFlag.AlignCenter, label)

        painter.end()


class SlidingNavPanel(QWidget):
    """Navegacion lateral vertical con pildora deslizante neutra (cero acento cian)."""

    current_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[tuple[str, str]] = []
        self._tooltips: list[str] = []
        self._current_index = 0
        self._hover_index = -1
        self._mode = "dark"
        self._animate = True
        self._row_height = 38
        self._row_gap = 4
        self._pill_y = 0.0

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(190)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuint)
        self._anim.valueChanged.connect(self._on_anim_val)

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_items(self, items: list[tuple[str, str]]) -> None:
        self._items = list(items)
        total_h = len(self._items) * (self._row_height + self._row_gap)
        self.setFixedHeight(max(38, total_h))
        self._pill_y = float(self._row_y(self._current_index))
        self.update()

    def update_labels(self, labels: list[str]) -> None:
        for idx, lbl in enumerate(labels):
            if idx < len(self._items):
                self._items[idx] = (self._items[idx][0], lbl)
        self.update()

    def set_tooltips(self, tips: list[str]) -> None:
        self._tooltips = list(tips)

    def tooltips(self) -> list[str]:
        return list(self._tooltips)

    def current_index(self) -> int:
        return self._current_index

    def item_count(self) -> int:
        return len(self._items)

    def set_animations_enabled(self, enabled: bool) -> None:
        self._animate = bool(enabled)

    def apply_theme(self, mode: str) -> None:
        self._mode = "light" if mode == "light" else "dark"
        self.update()

    def set_current_index(self, idx: int, *, animate: bool = True, emit_signal: bool = False) -> None:
        if not (0 <= idx < len(self._items)):
            return
        changed = idx != self._current_index
        self._current_index = idx
        target_y = float(self._row_y(idx))
        if animate and self._animate and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(self._pill_y)
            self._anim.setEndValue(target_y)
            self._anim.start()
        else:
            self._anim.stop()
            self._pill_y = target_y
            self.update()
        if changed and emit_signal:
            self.current_changed.emit(idx)

    def _row_y(self, idx: int) -> int:
        return idx * (self._row_height + self._row_gap)

    def _on_anim_val(self, val: object) -> None:
        self._pill_y = float(val)
        self.update()

    def _index_at_y(self, y: float) -> int:
        step = self._row_height + self._row_gap
        idx = int(y // step)
        if 0 <= idx < len(self._items) and (y % step) <= self._row_height:
            return idx
        return -1

    def event(self, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.ToolTip:
            idx = self._index_at_y(float(event.pos().y()))
            if 0 <= idx < len(self._tooltips) and self._tooltips[idx]:
                QToolTip.showText(event.globalPos(), self._tooltips[idx], self)
                return True
            QToolTip.hideText()
        return super().event(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        idx = self._index_at_y(event.position().y())
        if idx != self._hover_index:
            self._hover_index = idx
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_index = -1
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._index_at_y(event.position().y())
            if idx >= 0:
                self.set_current_index(idx, animate=True, emit_signal=True)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = get_palette(self._mode)
        painter = QPainter(self)

        if 0 <= self._hover_index < len(self._items) and self._hover_index != self._current_index:
            hy = self._row_y(self._hover_index)
            painter.fillRect(0, hy, self.width(), self._row_height, QColor(p["bg_hover"]))

        if self._items:
            py = int(round(self._pill_y))
            pill = QRect(0, py, self.width(), self._row_height)
            painter.fillRect(pill, QColor(p["bg_active"]))
            painter.setPen(QPen(QColor(p["border_strong"]), 1))
            painter.drawRect(pill.adjusted(0, 0, -1, -1))
            sheen = "#475569" if self._mode == "dark" else "#FFFFFF"
            painter.setPen(QPen(QColor(sheen), 1))
            painter.drawLine(pill.left() + 1, pill.top() + 1, pill.right() - 1, pill.top() + 1)

        font = QFont(UI_FONT_FAMILY, 10)
        font.setFamilies([UI_FONT_FAMILY, "Instrument Sans", "Segoe UI"])
        for idx, (icon_name, label) in enumerate(self._items):
            ry = self._row_y(idx)
            is_sel = idx == self._current_index
            icon_color = p["text_primary"] if is_sel else p["text_secondary"]
            pm = load_svg_pixmap(icon_name, color=icon_color, size=15)
            painter.drawPixmap(14, ry + (self._row_height - 15) // 2, pm)

            font.setWeight(QFont.Weight.Bold if is_sel else QFont.Weight.Medium)
            painter.setFont(font)
            painter.setPen(QColor(p["text_primary"] if is_sel else p["text_secondary"]))
            text_rect = QRect(39, ry, max(10, self.width() - 47), self._row_height)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)

        painter.end()
