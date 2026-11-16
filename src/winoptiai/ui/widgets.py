"""Reusable minimalist Obsidian Acrylic UI components (strictly 0px corners)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from .svg_icons import load_svg_pixmap
from .theme import MONO_FONT_FAMILY, PALETTE


class GlassPanel(QFrame):
    """Translucent 0px rectangular container with 1px hairline border."""

    def __init__(self, elevated: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GlassPanelElevated" if elevated else "GlassPanel")


class StatusTag(QLabel):
    """Minimalist custom inline tag badge (0px, 1px hairline border, IBM Plex Mono)."""

    TONES = {
        "neutral": ("#9BA3AE", "rgba(155, 163, 174, 48)", "rgba(155, 163, 174, 14)"),
        "active": ("#E2E7ED", "rgba(226, 231, 237, 90)", "rgba(226, 231, 237, 24)"),
        "ok": ("#9BB8AA", "rgba(140, 168, 154, 85)", "rgba(140, 168, 154, 18)"),
        "warn": ("#D4A76A", "rgba(200, 155, 98, 90)", "rgba(200, 155, 98, 18)"),
        "risk": ("#CC7A7A", "rgba(184, 106, 106, 95)", "rgba(184, 106, 106, 22)"),
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(load_svg_pixmap(icon_name, color=PALETTE["text_secondary"], size=14))
        header.addWidget(icon_lbl)

        title_lbl = QLabel(title.upper())
        title_lbl.setObjectName("SectionLabel")
        header.addWidget(title_lbl)
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
