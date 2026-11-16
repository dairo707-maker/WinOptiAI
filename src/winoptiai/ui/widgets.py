"""Reusable minimalist Obsidian/Alabaster Acrylic UI components (strictly 0px corners)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class NotebookCanvas(QWidget):
    """Stationery desk notebook paper canvas with fine 24px architectural pencil grid."""

    def __init__(self, theme_mode: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("RootCanvas")
        self._theme_mode = theme_mode

    def set_theme_mode(self, mode: str) -> None:
        self._theme_mode = mode
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        rect = self.rect()

        if self._theme_mode == "light":
            bg = QColor(246, 242, 233, 236)
            grid_color = QColor(124, 117, 102, 28)
            margin_color = QColor(168, 92, 82, 46)
        else:
            bg = QColor(22, 22, 20, 226)
            grid_color = QColor(228, 222, 208, 16)
            margin_color = QColor(180, 120, 110, 32)

        painter.fillRect(rect, bg)

        step = 24
        painter.setPen(QPen(grid_color, 1))
        for x in range(step, rect.width(), step):
            painter.drawLine(x, 0, x, rect.height())
        for y in range(step, rect.height(), step):
            painter.drawLine(0, y, rect.width(), y)

        # Subtle stationery notebook vertical margin line after sidebar
        painter.setPen(QPen(margin_color, 1))
        painter.drawLine(254, 0, 254, rect.height())
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
        if a is not None and b is not None:
            return float(a) < float(b)
        return super().__lt__(other)


class NumericTreeItem(QTreeWidgetItem):
    """Tree item sorting numerically on columns that store UserRole byte/count values."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        a = self.data(col, Qt.ItemDataRole.UserRole)
        b = other.data(col, Qt.ItemDataRole.UserRole)
        if a is not None and b is not None:
            return float(a) < float(b)
        return super().__lt__(other)


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
    ) -> None:
        super().__init__(elevated=False, parent=parent)
        self._icon_name = icon_name
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

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
        self.value_lbl.setObjectName("MetricValue")
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
