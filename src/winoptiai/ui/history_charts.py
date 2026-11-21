"""Graficos de monitoreo con historial (v0.5.8), estilo Obsidian Acrylic.

- QPainter propio (sin librerias de graficos): monocromo, lineas de 1 px, esquinas rectas.
- ``TimeSeriesChart``: RAM libre (con la linea del umbral SRE) y CPU % en 24 h / 7 d, mas una
  franja de marcadores de eventos de ``audit.jsonl`` (B = AI Boost, L = limpieza,
  D = depuracion de Cuarentena, E = informe de error) sobre la misma linea de tiempo.
- ``FreedSpaceChart``: area apilada escalonada del espacio en disco liberado por tipo.
- ``HistoryPanel`` / ``FreedSpacePanel``: cabecera con pestanas de rango y leyenda, y carga de
  datos en la hebra de ``MetricsHistory`` (nunca en el hilo GUI).
"""

from __future__ import annotations

from datetime import datetime
import time
from typing import Any, Callable

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QToolTip, QVBoxLayout, QWidget

from ..core.metrics_history import (
    EVENT_BOOST,
    EVENT_CLEAN,
    EVENT_ERROR,
    EVENT_PURGE,
    FREED_DUPS,
    FREED_KINDS,
    FREED_ONEDRIVE,
    FREED_QUARANTINE,
    FREED_TEMP,
    RANGE_24H,
    RANGE_7D,
    SAMPLE_INTERVAL_SECONDS,
    AuditEvent,
    MetricSample,
    MetricsHistory,
    freed_cumulative_series,
)
from .theme import MONO_FONT_FAMILY, UI_FONT_FAMILY
from .widgets import semaphore_hex

EVENT_GLYPHS = {EVENT_BOOST: "B", EVENT_CLEAN: "L", EVENT_PURGE: "D", EVENT_ERROR: "E"}
EVENT_NAMES = {
    EVENT_BOOST: "AI Boost",
    EVENT_CLEAN: "Limpieza",
    EVENT_PURGE: "Depuracion Cuarentena",
    EVENT_ERROR: "Informe de error",
}
FREED_NAMES = {
    FREED_TEMP: "Temporales",
    FREED_DUPS: "Duplicados",
    FREED_QUARANTINE: "Cuarentena",
    FREED_ONEDRIVE: "OneDrive",
}
# Niveles de gris (alfa sobre el color de texto) en lugar de colores saturados.
FREED_ALPHAS = {FREED_TEMP: 210, FREED_DUPS: 140, FREED_QUARANTINE: 85, FREED_ONEDRIVE: 40}


def format_mb(mb: float) -> str:
    if mb >= 1024 * 1024:
        return f"{mb / (1024 * 1024):.2f} TB"
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.0f} MB"


def _with_alpha(color: QColor, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(max(0, min(255, alpha)))
    return c


def _time_label(ts: float, range_s: float) -> str:
    try:
        dt = datetime.fromtimestamp(max(0.0, ts))
    except (OSError, OverflowError, ValueError):
        return ""
    return dt.strftime("%H:%M") if range_s <= 36 * 3600 else dt.strftime("%d/%m")


def _nice_step(span: float, target_ticks: int = 4) -> float:
    raw = span / max(1, target_ticks)
    for step in (0.25, 0.5, 1, 2, 4, 5, 8, 10, 16, 20, 25, 32, 50, 64, 100):
        if step >= raw:
            return float(step)
    return float(raw)


class TimeSeriesChart(QWidget):
    """RAM libre + CPU % con umbral SRE y marcadores de eventos sobre una sola linea de tiempo."""

    LEFT = 46
    RIGHT = 10
    TOP = 8
    EVENT_STRIP = 16
    AXIS = 16
    GAP = 18

    def __init__(self, palette_fn: Callable[[], dict[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette_fn = palette_fn
        self.samples: list[MetricSample] = []
        self.events: list[AuditEvent] = []
        self.now = time.time()
        self.range_s = float(RANGE_24H)
        self.threshold_gb = 0.0
        self._event_hits: list[tuple[QRectF, AuditEvent]] = []
        self.setMouseTracking(True)
        self.setMinimumHeight(150)

    # ------------------------------------------------------------------ data
    def set_data(
        self,
        samples: list[MetricSample],
        events: list[AuditEvent],
        now: float,
        range_s: float,
        threshold_gb: float,
    ) -> None:
        self.samples = list(samples)
        self.events = list(events)
        self.now = float(now) if now and now > 0 else time.time()
        self.range_s = float(range_s)
        self.threshold_gb = float(threshold_gb)
        self.update()

    # ------------------------------------------------------------------ geometry
    def _layout_metrics(self, fm: QFontMetrics | None = None) -> tuple[float, float, float, float, float, float]:
        if fm is None:
            fm = QFontMetrics(QFont(MONO_FONT_FAMILY, 8))
        ram_max = self.ram_scale_max()
        step = _nice_step(ram_max)
        y_labels = ["0%", "50%", "100%"]
        v = 0.0
        while v <= ram_max + 1e-6:
            y_labels.append(f"{v:.0f} GB" if step >= 1 else f"{v:.1f} GB")
            v += step
        max_y_w = max((fm.horizontalAdvance(lab) for lab in y_labels), default=32)
        left = max(float(self.LEFT), float(max_y_w + 14))
        right = max(float(self.RIGHT), float(fm.horizontalAdvance("ahora") / 2.0 + 6.0))
        label_h = max(14.0, float(fm.height() + 2))
        top = max(float(self.TOP), label_h / 2.0 + 2.0)
        event_strip = max(float(self.EVENT_STRIP), float(fm.height() + 4))
        axis = max(18.0, float(fm.height() + 8))
        return left, right, top, event_strip, axis, label_h

    def _plot_rect(self, fm: QFontMetrics | None = None) -> QRectF:
        left, right, top, event_strip, axis, _ = self._layout_metrics(fm)
        return QRectF(
            left,
            top,
            max(10.0, self.width() - left - right),
            max(10.0, self.height() - top - event_strip - axis),
        )

    def bands(self, fm: QFontMetrics | None = None) -> tuple[QRectF, QRectF, QRectF]:
        """(banda RAM, banda CPU, franja de eventos)."""
        _, _, _, event_strip, _, _ = self._layout_metrics(fm)
        plot = self._plot_rect(fm)
        ram_h = (plot.height() - self.GAP) * 0.58
        ram = QRectF(plot.left(), plot.top(), plot.width(), ram_h)
        cpu = QRectF(plot.left(), ram.bottom() + self.GAP, plot.width(), plot.height() - ram_h - self.GAP)
        strip = QRectF(plot.left(), plot.bottom() + 1, plot.width(), event_strip - 2)
        return ram, cpu, strip

    def x_for(self, ts: float) -> float:
        plot = self._plot_rect()
        start = self.now - self.range_s
        frac = (ts - start) / self.range_s if self.range_s > 0 else 0.0
        return plot.left() + max(0.0, min(1.0, frac)) * plot.width()

    def ram_scale_max(self) -> float:
        peak = max((s.ram_free_gb for s in self.samples), default=0.0)
        top = max(peak, self.threshold_gb) * 1.15
        step = _nice_step(top)
        return max(step, step * int(top / step + 0.999))

    def _segments(self) -> list[list[MetricSample]]:
        """Cortar la linea donde la app estuvo cerrada (huecos > 3 intervalos de muestreo)."""
        if not self.samples:
            return []
        bucket = max(SAMPLE_INTERVAL_SECONDS, self.range_s / 720.0)
        segs: list[list[MetricSample]] = [[self.samples[0]]]
        for prev, cur in zip(self.samples, self.samples[1:]):
            if cur.ts - prev.ts > 3 * bucket:
                segs.append([cur])
            else:
                segs[-1].append(cur)
        return segs

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        pal = self._palette_fn()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        txt = QColor(pal.get("text_primary", "#F3EFE6"))
        muted = QColor(pal.get("text_muted", "#8C867A"))
        warn = QColor(pal.get("tag_warn", "#D9A86C"))
        risk = QColor(pal.get("tag_risk", "#CF7C7C"))
        grid = _with_alpha(muted, 60)
        mono = QFont(MONO_FONT_FAMILY, 8)
        ui = QFont(UI_FONT_FAMILY, 8)
        fm = QFontMetrics(mono)
        left, right, _top, _strip_h, axis, label_h = self._layout_metrics(fm)
        ram_band, cpu_band, strip = self.bands(fm)
        self._event_hits = []

        # Marco y rejilla hairline
        p.setPen(QPen(grid, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for band in (ram_band, cpu_band):
            p.drawRect(band.adjusted(0.5, 0.5, -0.5, -0.5))

        ram_max = self.ram_scale_max()
        step = _nice_step(ram_max)
        p.setFont(mono)
        ticks_v: list[float] = []
        v = 0.0
        while v <= ram_max + 1e-6:
            ticks_v.append(v)
            v += step

        def _ram_ly(val: float) -> float:
            y_pos = ram_band.bottom() - (val / ram_max) * ram_band.height()
            return min(max(y_pos - label_h / 2.0, ram_band.top() - 2.0), ram_band.bottom() - label_h)

        top_v = ticks_v[-1] if ticks_v else ram_max
        top_ly = _ram_ly(top_v)
        prev_drawn_ly: float | None = None
        for idx, v in enumerate(ticks_v):
            y = ram_band.bottom() - (v / ram_max) * ram_band.height()
            is_edge = idx == 0 or idx == len(ticks_v) - 1
            p.setPen(QPen(grid, 1))
            if 0 < v < ram_max:
                p.drawLine(QPointF(ram_band.left(), y), QPointF(ram_band.right(), y))
            ly = _ram_ly(v)
            if not is_edge:
                if prev_drawn_ly is not None and abs(ly - prev_drawn_ly) < label_h + 1.0:
                    continue
                if abs(ly - top_ly) < label_h + 1.0:
                    continue
            prev_drawn_ly = ly
            p.setPen(muted)
            label = f"{v:.0f} GB" if step >= 1 else f"{v:.1f} GB"
            p.drawText(QRectF(2, ly, left - 8, label_h), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)

        for pct in (0, 50, 100):
            y = cpu_band.bottom() - (pct / 100.0) * cpu_band.height()
            p.setPen(QPen(grid, 1))
            if pct == 50:
                p.drawLine(QPointF(cpu_band.left(), y), QPointF(cpu_band.right(), y))
                if cpu_band.height() < 3.0 * label_h:
                    continue
            p.setPen(muted)
            ly = min(max(y - label_h / 2.0, cpu_band.top() - 2.0), cpu_band.bottom() - label_h)
            p.drawText(QRectF(2, ly, left - 8, label_h), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{pct}%")

        # Eje de tiempo (evita colision entre ticks contiguos y "ahora")
        ticks = 6 if self.range_s <= 36 * 3600 else 7
        w_now = fm.horizontalAdvance("ahora")
        now_lx = min(max(self.x_for(self.now) - w_now / 2.0, ram_band.left()), ram_band.right() - w_now)
        last_x_right = ram_band.left() - 8.0
        for i in range(ticks + 1):
            ts = self.now - self.range_s + self.range_s * i / ticks
            x = self.x_for(ts)
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(x, ram_band.top()), QPointF(x, cpu_band.bottom()))
            if i == ticks:
                p.setPen(muted)
                p.drawText(
                    QRectF(now_lx, strip.bottom() + 3, w_now + 4, axis - 4),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    "ahora",
                )
            elif i > 0:
                lab = _time_label(ts, self.range_s)
                w = fm.horizontalAdvance(lab)
                lx = min(max(x - w / 2.0, ram_band.left()), ram_band.right() - w)
                if lx >= last_x_right + 8.0 and lx + w + 8.0 <= now_lx:
                    p.setPen(muted)
                    p.drawText(
                        QRectF(lx, strip.bottom() + 3, w + 4, axis - 4),
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        lab,
                    )
                    last_x_right = lx + w

        # Titulos de banda
        p.setFont(ui)
        p.setPen(muted)
        p.drawText(ram_band.adjusted(6, 3, -6, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "RAM libre (promedio por minuto)")
        p.drawText(cpu_band.adjusted(6, 3, -6, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "CPU %")

        # Umbral SRE (linea discontinua, tono ambar atenuado; nunca se recorta arriba)
        if 0 < self.threshold_gb <= ram_max:
            y = ram_band.bottom() - (self.threshold_gb / ram_max) * ram_band.height()
            pen = QPen(_with_alpha(warn, 200), 1, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(QPointF(ram_band.left(), y), QPointF(ram_band.right(), y))
            p.setFont(mono)
            lab = f"umbral SRE {self.threshold_gb:.1f} GB"
            w = fm.horizontalAdvance(lab)
            ui_h = max(14.0, float(QFontMetrics(ui).height() + 2))
            if y - label_h - 1.0 >= ram_band.top() + ui_h + 2.0:
                thresh_ly = y - label_h - 1.0
            else:
                thresh_ly = min(y + 2.0, ram_band.bottom() - label_h)
            p.drawText(
                QRectF(ram_band.right() - w - 8, thresh_ly, w + 4, label_h),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                lab,
            )

        # Series (Cyber Cyan / Governance Blue en paleta TRODAI)
        ram_col = QColor(pal.get("accent", "#0EA5E9"))
        cpu_col = QColor(pal.get("accent_alt", "#3B82F6"))
        segments = self._segments()
        for seg in segments:
            self._draw_series(p, seg, ram_band, lambda s: s.ram_free_gb / ram_max, ram_col, fill=True)
            self._draw_series(p, seg, cpu_band, lambda s: s.cpu_pct / 100.0, cpu_col, fill=True)

        # Marcadores de eventos
        p.setFont(mono)
        start = self.now - self.range_s
        for ev in self.events:
            if ev.ts < start or ev.category not in EVENT_GLYPHS:
                continue
            x = self.x_for(ev.ts)
            col = risk if ev.category == EVENT_ERROR else txt
            p.setPen(QPen(_with_alpha(col, 70), 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(x, ram_band.top()), QPointF(x, cpu_band.bottom()))
            box = QRectF(x - 6, strip.top(), 12, strip.height())
            p.setPen(QPen(_with_alpha(col, 200), 1))
            p.setBrush(QColor(pal.get("bg_menu", "#1C1C19")))
            p.drawRect(box.adjusted(0.5, 0.5, -0.5, -0.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, EVENT_GLYPHS[ev.category])
            self._event_hits.append((box.adjusted(-2, -2, 2, 2), ev))

        if not self.samples:
            p.setFont(QFont(UI_FONT_FAMILY, 9))
            p.setPen(muted)
            p.drawText(
                ram_band.adjusted(8, 18, -8, -4),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                "Recopilando historial: se guarda un punto por minuto mientras WinOptiAI esta abierta "
                "(tambien minimizada en la bandeja). Vuelva en unos minutos.",
            )
        p.end()

    def _draw_series(self, p: QPainter, seg: list[MetricSample], band: QRectF, frac_fn, color: QColor, fill: bool) -> None:
        pts = [
            QPointF(self.x_for(s.ts), band.bottom() - max(0.0, min(1.0, frac_fn(s))) * band.height())
            for s in seg
        ]
        if len(pts) == 1:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRect(QRectF(pts[0].x() - 1, pts[0].y() - 1, 2, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            return
        line = QPainterPath(pts[0])
        for pt in pts[1:]:
            line.lineTo(pt)
        if fill:
            area = QPainterPath(line)
            area.lineTo(pts[-1].x(), band.bottom())
            area.lineTo(pts[0].x(), band.bottom())
            area.closeSubpath()
            p.fillPath(area, _with_alpha(color, 22))
        p.setPen(QPen(color, 1))
        p.drawPath(line)

    # ------------------------------------------------------------------ tooltip
    def nearest_sample(self, x: float) -> MetricSample | None:
        if not self.samples:
            return None
        best = min(self.samples, key=lambda s: abs(self.x_for(s.ts) - x))
        return best if abs(self.x_for(best.ts) - x) <= 12 else None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        for box, ev in self._event_hits:
            if box.contains(pos):
                when = datetime.fromtimestamp(ev.ts).strftime("%d/%m %H:%M")
                extra = f"\nLiberado: {format_mb(ev.freed_mb)}" if ev.freed_mb > 0 else ""
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{when}  {EVENT_NAMES.get(ev.category or '', ev.action)}\n{ev.action}: {ev.detail[:160]}{extra}",
                    self,
                )
                return
        s = self.nearest_sample(pos.x())
        if s is None:
            QToolTip.hideText()
            return
        when = datetime.fromtimestamp(s.ts).strftime("%d/%m %H:%M")
        parts = [when, f"RAM libre {s.ram_free_gb:.2f} GB de {s.ram_total_gb:.1f} GB", f"CPU {s.cpu_pct:.0f}%"]
        if s.cpu_temp_c is not None:
            parts.append(f"Temperatura {s.cpu_temp_c:.0f} C")
        if s.disk_free_gb is not None:
            parts.append(f"Disco libre {s.disk_free_gb:.1f} GB")
        if s.app_ram_mb is not None:
            parts.append(f"RAM de WinOptiAI {s.app_ram_mb:.0f} MB")
        QToolTip.showText(event.globalPosition().toPoint(), "\n".join(parts), self)

    def leaveEvent(self, _event) -> None:  # noqa: N802
        QToolTip.hideText()


class FreedSpaceChart(QWidget):
    """Area apilada escalonada: espacio en disco liberado acumulado por tipo."""

    LEFT = 58
    RIGHT = 10
    TOP = 8
    AXIS = 16

    def __init__(self, palette_fn: Callable[[], dict[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette_fn = palette_fn
        self.events: list[AuditEvent] = []
        self.now = time.time()
        self.setMinimumHeight(140)

    def set_data(self, events: list[AuditEvent], now: float) -> None:
        self.events = [e for e in events if e.freed_kind and e.freed_mb > 0]
        self.now = float(now) if now and now > 0 else time.time()
        self.update()

    def stacked_totals(self) -> list[tuple[float, dict[str, float]]]:
        """Puntos (ts, acumulado por tipo) en cada evento; util para pruebas y dibujo."""
        series = freed_cumulative_series(self.events)
        stamps = sorted({ts for pts in series.values() for ts, _ in pts})
        acc = {k: 0.0 for k in FREED_KINDS}
        idx = {k: 0 for k in FREED_KINDS}
        out: list[tuple[float, dict[str, float]]] = []
        for ts in stamps:
            for k in FREED_KINDS:
                pts = series[k]
                while idx[k] < len(pts) and pts[idx[k]][0] <= ts:
                    acc[k] = pts[idx[k]][1]
                    idx[k] += 1
            out.append((ts, dict(acc)))
        return out

    def _layout_metrics(
        self,
        fm: QFontMetrics | None = None,
        y_labels: list[str] | None = None,
    ) -> tuple[float, float, float, float, float]:
        if fm is None:
            fm = QFontMetrics(QFont(MONO_FONT_FAMILY, 8))
        if y_labels is None:
            points = self.stacked_totals()
            if points:
                total_max = max(sum(v.values()) for _, v in points)
                top_val = total_max * 1.15 if total_max > 0 else 1.0
                y_labels = [format_mb(top_val * frac) for frac in (0.0, 0.5, 1.0)]
            else:
                y_labels = ["0 MB"]
        max_y_w = max((fm.horizontalAdvance(lab) for lab in y_labels), default=40)
        left = max(float(self.LEFT), float(max_y_w + 14))
        right = max(float(self.RIGHT), float(fm.horizontalAdvance("ahora") / 2.0 + 6.0))
        label_h = max(14.0, float(fm.height() + 2))
        margin_top = max(float(self.TOP), label_h / 2.0 + 2.0)
        axis = max(float(self.AXIS), float(fm.height() + 6))
        return left, right, margin_top, axis, label_h

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        pal = self._palette_fn()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        txt = QColor(pal.get("text_primary", "#F3EFE6"))
        muted = QColor(pal.get("text_muted", "#8C867A"))
        grid = _with_alpha(muted, 60)
        mono = QFont(MONO_FONT_FAMILY, 8)
        fm = QFontMetrics(mono)
        points = self.stacked_totals()
        if points:
            total_max = max(sum(v.values()) for _, v in points)
            top = total_max * 1.15 if total_max > 0 else 1.0
            y_labels = [format_mb(top * frac) for frac in (0.0, 0.5, 1.0)]
        else:
            top = 1.0
            y_labels = ["0 MB"]
        left, right, margin_top, axis, label_h = self._layout_metrics(fm, y_labels)
        plot = QRectF(
            left,
            margin_top,
            max(10.0, self.width() - left - right),
            max(10.0, self.height() - margin_top - axis),
        )
        p.setPen(QPen(grid, 1))
        p.drawRect(plot.adjusted(0.5, 0.5, -0.5, -0.5))
        p.setFont(mono)
        if not points:
            p.setFont(QFont(UI_FONT_FAMILY, 9))
            p.setPen(muted)
            p.drawText(
                plot.adjusted(10, 6, -10, -6),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                "Aun no hay limpiezas registradas. Cada limpieza de temporales, duplicados, Cuarentena "
                "u OneDrive suma aqui el espacio que reporto haber liberado.",
            )
            p.end()
            return

        start = points[0][0]
        end = max(self.now, points[-1][0] + 1)
        span = max(1.0, end - start)

        def x_for(ts: float) -> float:
            return plot.left() + (ts - start) / span * plot.width()

        def y_for(mb: float) -> float:
            return plot.bottom() - (mb / top) * plot.height()

        # Eje vertical: 0, medio y maximo (centrados en su linea sin recortar arriba ni abajo)
        for frac, y_lab in zip((0.0, 0.5, 1.0), y_labels):
            mb = top * frac
            y = y_for(mb)
            if 0 < frac < 1:
                p.setPen(QPen(grid, 1))
                p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(muted)
            ly = min(max(y - label_h / 2.0, 2.0), plot.bottom() - label_h)
            p.drawText(
                QRectF(2, ly, left - 8, label_h),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                y_lab,
            )

        # Capas apiladas de abajo hacia arriba (escalonadas: tono acento TRODAI)
        area_col = QColor(pal.get("accent", txt.name()))
        lower = [0.0] * len(points)
        for kind in FREED_KINDS:
            upper = [lower[i] + points[i][1][kind] for i in range(len(points))]
            if max(upper) - max(lower) <= 0 and all(u == lo for u, lo in zip(upper, lower)):
                lower = upper
                continue
            path = QPainterPath(QPointF(x_for(points[0][0]), y_for(lower[0])))
            top_pts: list[QPointF] = []
            for i, (ts, _) in enumerate(points):
                x = x_for(ts)
                if i > 0:
                    top_pts.append(QPointF(x, y_for(upper[i - 1])))
                top_pts.append(QPointF(x, y_for(upper[i])))
            top_pts.append(QPointF(plot.right(), y_for(upper[-1])))
            for pt in top_pts:
                path.lineTo(pt)
            path.lineTo(plot.right(), y_for(lower[-1]))
            for i in range(len(points) - 1, -1, -1):
                x = x_for(points[i][0])
                path.lineTo(x, y_for(lower[i]))
                if i > 0:
                    path.lineTo(x, y_for(lower[i - 1]))
            path.closeSubpath()
            p.fillPath(path, _with_alpha(area_col, FREED_ALPHAS[kind]))
            p.setPen(QPen(_with_alpha(area_col, 230), 1))
            edge = QPainterPath(top_pts[0])
            for pt in top_pts[1:]:
                edge.lineTo(pt)
            p.drawPath(edge)
            lower = upper

        # Eje de tiempo: inicio, medio, ahora (evita solapamientos si la vista es estrecha)
        fmt = "%d/%m %H:%M" if span <= 36 * 3600 else "%d/%m"
        t_start = datetime.fromtimestamp(start).strftime(fmt)
        t_mid = datetime.fromtimestamp(start + span * 0.5).strftime(fmt)
        w_start = fm.horizontalAdvance(t_start)
        w_mid = fm.horizontalAdvance(t_mid)
        w_now = fm.horizontalAdvance("ahora")
        lx_start = plot.left()
        lx_now = max(plot.left(), plot.right() - w_now)
        lx_mid = min(max(plot.left() + plot.width() * 0.5 - w_mid / 2.0, plot.left()), plot.right() - w_mid)
        p.setPen(muted)
        p.drawText(QRectF(lx_start, plot.bottom() + 2, w_start + 4, axis - 2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, t_start)
        if lx_mid >= lx_start + w_start + 10.0 and lx_mid + w_mid + 10.0 <= lx_now:
            p.drawText(QRectF(lx_mid, plot.bottom() + 2, w_mid + 4, axis - 2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, t_mid)
        p.drawText(QRectF(lx_now, plot.bottom() + 2, w_now + 4, axis - 2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "ahora")
        p.end()


class _LoadRelay(QObject):
    """Lleva resultados de la hebra de metricas al hilo GUI (conexion en cola)."""

    loaded = Signal(int, object)


def _range_tabs(labels: list[tuple[int, str]], on_pick: Callable[[int], None]) -> tuple[QHBoxLayout, dict[int, QPushButton]]:
    row = QHBoxLayout()
    row.setSpacing(6)
    buttons: dict[int, QPushButton] = {}
    for value, text in labels:
        b = QPushButton(text)
        b.setObjectName("ModeTab")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda _=False, v=value: on_pick(v))
        buttons[value] = b
        row.addWidget(b)
    return row, buttons


def _mark_selected(buttons: dict[int, QPushButton], value: int) -> None:
    for v, b in buttons.items():
        b.setProperty("selected", v == value)
        b.style().unpolish(b)
        b.style().polish(b)


class _AsyncPanel(QWidget):
    """Base: carga diferida y coalescida desde ``MetricsHistory`` sin bloquear la GUI."""

    def __init__(self, palette_fn: Callable[[], dict[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette_fn = palette_fn
        self.history: MetricsHistory | None = None
        self.threshold_fn: Callable[[], float] = lambda: 0.0
        self._token = 0
        self._relay = _LoadRelay(self)
        self._relay.loaded.connect(self._on_loaded, Qt.ConnectionType.QueuedConnection)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self.refresh_now)

    def attach(self, history: MetricsHistory, threshold_fn: Callable[[], float]) -> None:
        self.history = history
        self.threshold_fn = threshold_fn
        self.schedule_refresh(0)

    def schedule_refresh(self, delay_ms: int = 600) -> None:
        self._debounce.start(max(0, delay_ms))

    def _range(self) -> int:
        return RANGE_24H

    def refresh_now(self) -> None:
        if self.history is None:
            return
        self._token += 1
        token = self._token
        relay = self._relay
        fut = self.history.submit(self.history.load_snapshot, self._range())

        def _done(f) -> None:
            try:
                data = f.result()
            except Exception:  # noqa: BLE001
                return
            try:
                relay.loaded.emit(token, data)
            except RuntimeError:  # widget ya destruido
                pass

        fut.add_done_callback(_done)

    def _on_loaded(self, token: int, data: Any) -> None:
        if token != self._token or not isinstance(data, dict):
            return
        self.apply_snapshot(data)

    def apply_snapshot(self, data: dict[str, Any]) -> None:  # pragma: no cover - abstracto
        raise NotImplementedError


class HistoryPanel(_AsyncPanel):
    """Pestanas 24 h / 7 d + leyenda + ``TimeSeriesChart``."""

    def __init__(self, palette_fn: Callable[[], dict[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(palette_fn, parent)
        self.range_s = RANGE_24H
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(4)
        head, self.range_buttons = _range_tabs([(RANGE_24H, "24 h"), (RANGE_7D, "7 d")], self.set_range)
        self.summary_lbl = QLabel("Sin datos todavia")
        self.summary_lbl.setObjectName("BodyText")
        self.summary_lbl.setWordWrap(True)
        head.addSpacing(8)
        head.addWidget(self.summary_lbl, stretch=1)
        lay.addLayout(head)
        self.legend_lbl = QLabel("B AI Boost   L Limpieza   D Depuracion   E Error")
        self.legend_lbl.setObjectName("Caption")
        lay.addWidget(self.legend_lbl)
        self.chart = TimeSeriesChart(palette_fn)
        self.chart.setMinimumHeight(170)
        lay.addWidget(self.chart, stretch=1)
        _mark_selected(self.range_buttons, self.range_s)

    def _range(self) -> int:
        return self.range_s

    def set_range(self, range_s: int) -> None:
        self.range_s = int(range_s)
        _mark_selected(self.range_buttons, self.range_s)
        self.refresh_now()

    def apply_snapshot(self, data: dict[str, Any]) -> None:
        samples: list[MetricSample] = data.get("samples", [])
        events: list[AuditEvent] = data.get("events", [])
        self.chart.set_data(samples, events, data.get("now", 0.0), data.get("range", self.range_s), self.threshold_fn())
        if samples:
            ram = [s.ram_free_gb for s in samples]
            cpu = [s.cpu_pct for s in samples]
            below = sum(1 for v in ram if v < self.threshold_fn())
            boosts = sum(1 for e in events if e.category == EVENT_BOOST)
            self.summary_lbl.setText(
                f"RAM libre min {min(ram):.2f} GB | CPU prom {sum(cpu) / len(cpu):.0f}% | "
                f"{below * 100 // len(ram)}% bajo umbral | {boosts} AI Boost"
            )
        else:
            self.summary_lbl.setText("Sin datos todavia")


class FreedSpacePanel(_AsyncPanel):
    """Leyenda con totales por tipo + ``FreedSpaceChart`` (todo el historial de audit.jsonl)."""

    def __init__(self, palette_fn: Callable[[], dict[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(palette_fn, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(6)
        self.totals_lbl = QLabel("Sin limpiezas registradas")
        self.totals_lbl.setObjectName("BodyText")
        self.totals_lbl.setWordWrap(True)
        lay.addWidget(self.totals_lbl)
        self.legend = _FreedLegend(palette_fn)
        lay.addWidget(self.legend)
        self.chart = FreedSpaceChart(palette_fn)
        lay.addWidget(self.chart, stretch=1)

    def _range(self) -> int:
        return RANGE_7D

    def apply_snapshot(self, data: dict[str, Any]) -> None:
        # El acumulado usa todo el historial de audit.jsonl (no solo 7 d).
        totals: dict[str, float] = data.get("freed_totals_all", {})
        self.legend.set_totals(totals)
        grand = sum(totals.values())
        last7 = sum(data.get("freed_totals", {}).values())
        self.totals_lbl.setText(
            f"Total liberado reportado: {format_mb(grand)} | ultimos 7 d: {format_mb(last7)}"
            if grand > 0
            else "Sin limpiezas registradas"
        )
        self.chart.set_data(data.get("freed_events_all", []), data.get("now", 0.0))


class _FreedLegend(QWidget):
    """Muestras de tono + nombre + total de cada tipo (pintado propio, sin recortes)."""

    def __init__(self, palette_fn: Callable[[], dict[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette_fn = palette_fn
        self.totals: dict[str, float] = {k: 0.0 for k in FREED_KINDS}
        self.setMinimumHeight(self.heightForWidth(400))

    def set_totals(self, totals: dict[str, float]) -> None:
        self.totals = {k: float(totals.get(k, 0.0)) for k in FREED_KINDS}
        h = self.heightForWidth(max(200, self.width() or 400))
        if self.minimumHeight() != h:
            self.setMinimumHeight(h)
        self.updateGeometry()
        self.update()

    def _items(self) -> list[str]:
        return [f"{FREED_NAMES[k]} {format_mb(self.totals[k])}" for k in FREED_KINDS]

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._layout(width)[1]

    def _layout(self, width: int) -> tuple[list[QRectF], int]:
        fm = QFontMetrics(QFont(UI_FONT_FAMILY, 8))
        row_h = float(max(22, fm.height() + 6))
        x, y = 0.0, 0.0
        eff_w = max(120, int(width))
        rects: list[QRectF] = []
        for text in self._items():
            w = 16 + fm.horizontalAdvance(text) + 18
            if x > 0 and x + w > eff_w:
                x, y = 0.0, y + row_h
            rects.append(QRectF(x, y, w, row_h))
            x += w
        return rects, int(round(y + row_h))

    def sizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize

        return QSize(400, self.heightForWidth(max(200, self.width())))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        h = self.heightForWidth(self.width())
        if self.minimumHeight() != h:
            self.setMinimumHeight(h)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        pal = self._palette_fn()
        txt = QColor(pal.get("accent", pal.get("text_primary", "#0EA5E9")))
        sec = QColor(pal.get("text_secondary", "#CBD5E1"))
        p = QPainter(self)
        p.setFont(QFont(UI_FONT_FAMILY, 8))
        rects, _ = self._layout(self.width())
        for kind, rect, text in zip(FREED_KINDS, rects, self._items()):
            sw = QRectF(rect.left(), rect.top() + (rect.height() - 10.0) / 2.0, 10, 10)
            p.fillRect(sw, _with_alpha(txt, FREED_ALPHAS[kind]))
            p.setPen(QPen(_with_alpha(txt, 200), 1))
            p.drawRect(sw.adjusted(0.5, 0.5, -0.5, -0.5))
            p.setPen(sec)
            p.drawText(QRectF(rect.left() + 16, rect.top(), rect.width() - 16, rect.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        p.end()


def css_qcolor(value: str, fallback: str = "#000000") -> QColor:
    """Convierte colores de la paleta QSS a QColor, incluido el formato ``rgba(r, g, b, a)``.

    v0.6.1: ``QColor("rgba(...)")`` es invalido y se pintaba NEGRO; en modo claro el panel de
    medidores quedaba negro con texto oscuro ilegible.
    """
    text = (value or "").strip()
    if text.lower().startswith("rgba(") and text.endswith(")"):
        try:
            parts = [float(x) for x in text[5:-1].split(",")]
            r, g, b = (int(v) for v in parts[:3])
            alpha = int(parts[3]) if len(parts) > 3 else 255
            return QColor(r, g, b, max(0, min(255, alpha)))
        except (ValueError, IndexError):
            return QColor(fallback)
    c = QColor(text)
    return c if c.isValid() else QColor(fallback)


class SystemGaugesWidget(QWidget):
    """Medidores radiales en cuadricula 2x2 (RAM, Disco, CPU y Temperatura/Memoria virtual).

    v0.6.1: 4 medidores que crecen con el alto disponible (antes 3 fijos de 56 px dejaban un
    hueco grande debajo), linea de detalle bajo cada etiqueta y colores legibles en modo claro.
    Jerarquia tipografica: cabecera y porcentaje en negrita, etiquetas semibold, detalle normal.
    """

    def __init__(self, palette_fn: Callable[[], dict[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette_fn = palette_fn
        self._gauges: list[dict[str, Any]] = [
            {"label": "RAM", "pct": 0, "tone": "ok", "text": "0%", "detail": ""},
            {"label": "DISCO C:", "pct": 0, "tone": "ok", "text": "0%", "detail": ""},
            {"label": "CPU", "pct": 0, "tone": "ok", "text": "0%", "detail": ""},
            {"label": "TEMP. CPU", "pct": 0, "tone": "neutral", "text": "--", "detail": "Sin sensor"},
        ]
        self._health_label = "OPTIMO"
        self._health_tone = "ok"
        self.setMinimumSize(185, 160)

    # Compatibilidad: pruebas y codigo antiguo leen estos atributos.
    @property
    def _ram_pct(self) -> int:
        return int(self._gauges[0]["pct"])

    @property
    def _disk_pct(self) -> int:
        return int(self._gauges[1]["pct"])

    @property
    def _cpu_pct(self) -> int:
        return int(self._gauges[2]["pct"])

    def update_values(
        self,
        ram_pct: int,
        ram_tone: str,
        disk_pct: int,
        disk_tone: str,
        cpu_pct: int,
        cpu_tone: str,
        health_label: str,
        health_tone: str,
        details: tuple[str, str, str] | None = None,
        fourth: dict[str, Any] | None = None,
    ) -> None:
        values = ((ram_pct, ram_tone), (disk_pct, disk_tone), (cpu_pct, cpu_tone))
        for i, (pct, tone) in enumerate(values):
            pct_i = max(0, min(100, int(pct)))
            self._gauges[i].update(pct=pct_i, tone=tone, text=f"{pct_i}%")
            if details is not None:
                self._gauges[i]["detail"] = details[i]
        if fourth is not None:
            g = self._gauges[3]
            g["label"] = str(fourth.get("label", g["label"]))
            g["pct"] = max(0, min(100, int(fourth.get("pct", 0))))
            g["tone"] = str(fourth.get("tone", "neutral"))
            g["text"] = str(fourth.get("text", f"{g['pct']}%"))
            g["detail"] = str(fourth.get("detail", ""))
        self._health_label = health_label
        self._health_tone = health_tone
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        pal = self._palette_fn()
        mode = pal.get("mode", "dark")
        light = mode == "light"
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w, h = float(self.width()), float(self.height())
        border_col = css_qcolor(pal.get("border_hairline", "#1F2A44"), "#1F2A44")
        bg_col = css_qcolor(pal.get("bg_table", "#0A0F1D"), "#FFFFFF" if light else "#0A0F1D")
        bg_col.setAlpha(255)  # lienzo opaco y legible en ambos temas
        txt_col = css_qcolor(pal.get("text_primary", ""), "#0A0F1D" if light else "#F8FAFC")
        sec_col = css_qcolor(pal.get("text_secondary", ""), "#334155" if light else "#CBD5E1")
        muted_col = css_qcolor(pal.get("text_muted", ""), "#4A5568" if light else "#94A3B8")
        track_col = css_qcolor(pal.get("border_hairline" if light else "border_strong", ""), "#33415F")

        p.fillRect(self.rect(), bg_col)
        p.setPen(QPen(border_col, 1))
        p.drawRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0))

        # Cabecera: titulo en negrita, estado global con su color de semaforo
        h_col = QColor(semaphore_hex(self._health_tone, mode))
        p.fillRect(QRectF(10, 11, 8, 8), h_col)
        p.setFont(QFont(UI_FONT_FAMILY, 9, QFont.Weight.Bold))
        p.setPen(txt_col)
        p.drawText(QRectF(24, 6, w - 34, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "SALUD")
        p.setPen(h_col)
        p.drawText(QRectF(10, 6, w - 20, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._health_label)

        top = 30.0
        avail_h = max(60.0, h - top - 6.0)
        cols, rows = 2, 2
        cell_w = (w - 12.0) / cols
        cell_h = avail_h / rows
        label_block = 30.0  # etiqueta + detalle bajo el anillo
        if cell_h - label_block < 34.0:
            self._paint_bars(p, top, avail_h, w, mode, txt_col, track_col)
            p.end()
            return

        arc_d = max(34.0, min(cell_w - 22.0, cell_h - label_block - 8.0, 96.0))
        ring_w = max(4.0, float(round(arc_d / 14.0)))
        pct_pt = int(max(9.0, min(15.0, arc_d / 5.6)))
        for idx, g in enumerate(self._gauges):
            r_i, c_i = divmod(idx, cols)
            cx = 6.0 + cell_w * c_i + cell_w / 2.0
            cy0 = top + cell_h * r_i + max(2.0, (cell_h - arc_d - label_block) / 2.0)
            arc_r = QRectF(0, 0, arc_d - ring_w, arc_d - ring_w)
            arc_r.moveCenter(QPointF(cx, cy0 + arc_d / 2.0))
            tone_col = QColor(semaphore_hex(g["tone"], mode))
            p.setPen(QPen(track_col, ring_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            p.drawArc(arc_r, 90 * 16, -360 * 16)
            if g["pct"] > 0:
                p.setPen(QPen(tone_col, ring_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
                p.drawArc(arc_r, 90 * 16, -int((g["pct"] / 100.0) * 360 * 16))
            p.setFont(QFont(MONO_FONT_FAMILY, pct_pt, QFont.Weight.Medium))
            p.setPen(txt_col)
            p.drawText(arc_r, Qt.AlignmentFlag.AlignCenter, g["text"])
            ly = cy0 + arc_d + 3.0
            p.setFont(QFont(UI_FONT_FAMILY, 8, QFont.Weight.Medium))
            p.setPen(sec_col)
            p.drawText(QRectF(cx - cell_w / 2.0, ly, cell_w, 14), Qt.AlignmentFlag.AlignCenter, g["label"])
            if g["detail"]:
                p.setFont(QFont(UI_FONT_FAMILY, 8, QFont.Weight.Normal))
                p.setPen(muted_col)
                fm = QFontMetrics(p.font())
                detail = fm.elidedText(g["detail"], Qt.TextElideMode.ElideRight, int(cell_w - 6))
                p.drawText(QRectF(cx - cell_w / 2.0, ly + 14, cell_w, 14), Qt.AlignmentFlag.AlignCenter, detail)
        p.end()

    def _paint_bars(self, p, top, avail_h, w, mode, txt_col, track_col) -> None:
        """Respaldo compacto por barras si el panel es muy bajo."""
        y = top
        row_step = avail_h / len(self._gauges)
        for g in self._gauges:
            tone_col = QColor(semaphore_hex(g["tone"], mode))
            p.setFont(QFont(UI_FONT_FAMILY, 8, QFont.Weight.Medium))
            p.setPen(txt_col)
            p.drawText(QRectF(10, y, w - 20, 14), Qt.AlignmentFlag.AlignLeft, g["label"])
            p.setFont(QFont(MONO_FONT_FAMILY, 8, QFont.Weight.Medium))
            p.setPen(tone_col)
            p.drawText(QRectF(10, y, w - 20, 14), Qt.AlignmentFlag.AlignRight, g["text"])
            p.fillRect(QRectF(10, y + 16, w - 20, 4), track_col)
            p.fillRect(QRectF(10, y + 16, (w - 20) * (g["pct"] / 100.0), 4), tone_col)
            y += row_step
