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
    def _plot_rect(self) -> QRectF:
        return QRectF(self.LEFT, self.TOP, max(10.0, self.width() - self.LEFT - self.RIGHT), max(10.0, self.height() - self.TOP - self.EVENT_STRIP - self.AXIS))

    def bands(self) -> tuple[QRectF, QRectF, QRectF]:
        """(banda RAM, banda CPU, franja de eventos)."""
        plot = self._plot_rect()
        ram_h = (plot.height() - self.GAP) * 0.58
        ram = QRectF(plot.left(), plot.top(), plot.width(), ram_h)
        cpu = QRectF(plot.left(), ram.bottom() + self.GAP, plot.width(), plot.height() - ram_h - self.GAP)
        strip = QRectF(plot.left(), plot.bottom() + 1, plot.width(), self.EVENT_STRIP - 2)
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
        ram_band, cpu_band, strip = self.bands()
        self._event_hits = []

        # Marco y rejilla hairline
        p.setPen(QPen(grid, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for band in (ram_band, cpu_band):
            p.drawRect(band.adjusted(0.5, 0.5, -0.5, -0.5))

        ram_max = self.ram_scale_max()
        step = _nice_step(ram_max)
        p.setFont(mono)
        v = 0.0
        while v <= ram_max + 1e-6:
            y = ram_band.bottom() - (v / ram_max) * ram_band.height()
            p.setPen(QPen(grid, 1))
            if 0 < v < ram_max:
                p.drawLine(QPointF(ram_band.left(), y), QPointF(ram_band.right(), y))
            p.setPen(muted)
            label = f"{v:.0f} GB" if step >= 1 else f"{v:.1f} GB"
            ly = min(max(y - 7, ram_band.top()), ram_band.bottom() - 14)  # dentro de la banda
            p.drawText(QRectF(0, ly, self.LEFT - 6, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
            v += step
        for pct in (0, 50, 100):
            y = cpu_band.bottom() - (pct / 100.0) * cpu_band.height()
            p.setPen(QPen(grid, 1))
            if pct == 50:
                p.drawLine(QPointF(cpu_band.left(), y), QPointF(cpu_band.right(), y))
            p.setPen(muted)
            ly = min(max(y - 7, cpu_band.top()), cpu_band.bottom() - 14)
            p.drawText(QRectF(0, ly, self.LEFT - 6, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{pct}%")

        # Eje de tiempo
        ticks = 6 if self.range_s <= 36 * 3600 else 7
        for i in range(ticks + 1):
            ts = self.now - self.range_s + self.range_s * i / ticks
            x = self.x_for(ts)
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(x, ram_band.top()), QPointF(x, cpu_band.bottom()))
            if 0 < i < ticks or i == ticks:
                lab = "ahora" if i == ticks else _time_label(ts, self.range_s)
                w = fm.horizontalAdvance(lab)
                lx = min(max(x - w / 2, self.LEFT), self.width() - self.RIGHT - w)
                p.setPen(muted)
                p.drawText(QRectF(lx, strip.bottom() + 2, w + 2, self.AXIS - 2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, lab)

        # Titulos de banda
        p.setFont(ui)
        p.setPen(muted)
        p.drawText(ram_band.adjusted(6, 3, -6, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "RAM libre (promedio por minuto)")
        p.drawText(cpu_band.adjusted(6, 3, -6, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "CPU %")

        # Umbral SRE (linea discontinua, tono ambar atenuado)
        if 0 < self.threshold_gb <= ram_max:
            y = ram_band.bottom() - (self.threshold_gb / ram_max) * ram_band.height()
            pen = QPen(_with_alpha(warn, 200), 1, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(QPointF(ram_band.left(), y), QPointF(ram_band.right(), y))
            p.setFont(mono)
            lab = f"umbral SRE {self.threshold_gb:.1f} GB"
            w = fm.horizontalAdvance(lab)
            p.drawText(QRectF(ram_band.right() - w - 6, y - 14, w + 2, 12), Qt.AlignmentFlag.AlignRight, lab)

        # Series
        segments = self._segments()
        for seg in segments:
            self._draw_series(p, seg, ram_band, lambda s: s.ram_free_gb / ram_max, txt, fill=True)
            self._draw_series(p, seg, cpu_band, lambda s: s.cpu_pct / 100.0, txt, fill=True)

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

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        pal = self._palette_fn()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        txt = QColor(pal.get("text_primary", "#F3EFE6"))
        muted = QColor(pal.get("text_muted", "#8C867A"))
        grid = _with_alpha(muted, 60)
        mono = QFont(MONO_FONT_FAMILY, 8)
        fm = QFontMetrics(mono)
        plot = QRectF(self.LEFT, self.TOP, max(10.0, self.width() - self.LEFT - self.RIGHT), max(10.0, self.height() - self.TOP - self.AXIS))
        p.setPen(QPen(grid, 1))
        p.drawRect(plot.adjusted(0.5, 0.5, -0.5, -0.5))
        points = self.stacked_totals()
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
        total_max = max(sum(v.values()) for _, v in points)
        top = total_max * 1.15 if total_max > 0 else 1.0

        def x_for(ts: float) -> float:
            return plot.left() + (ts - start) / span * plot.width()

        def y_for(mb: float) -> float:
            return plot.bottom() - (mb / top) * plot.height()

        # Eje vertical: 0, medio y maximo
        for frac in (0.0, 0.5, 1.0):
            mb = top * frac
            y = y_for(mb)
            if 0 < frac < 1:
                p.setPen(QPen(grid, 1))
                p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(muted)
            p.drawText(QRectF(0, y - 7, self.LEFT - 6, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, format_mb(mb))

        # Capas apiladas de abajo hacia arriba (escalonadas: el acumulado sube en cada evento)
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
            p.fillPath(path, _with_alpha(txt, FREED_ALPHAS[kind]))
            p.setPen(QPen(_with_alpha(txt, 230), 1))
            edge = QPainterPath(top_pts[0])
            for pt in top_pts[1:]:
                edge.lineTo(pt)
            p.drawPath(edge)
            lower = upper

        # Eje de tiempo: inicio, medio, ahora
        for frac, lab in ((0.0, None), (0.5, None), (1.0, "ahora")):
            ts = start + span * frac
            text = lab or datetime.fromtimestamp(ts).strftime("%d/%m %H:%M" if span <= 36 * 3600 else "%d/%m")
            w = fm.horizontalAdvance(text)
            x = plot.left() + plot.width() * frac
            lx = min(max(x - w / 2, plot.left()), plot.right() - w)
            p.setPen(muted)
            p.drawText(QRectF(lx, plot.bottom() + 2, w + 2, self.AXIS - 2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
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
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(6)
        head, self.range_buttons = _range_tabs([(RANGE_24H, "24 h"), (RANGE_7D, "7 d")], self.set_range)
        self.summary_lbl = QLabel("Sin datos todavia")
        self.summary_lbl.setObjectName("MonoValue")
        self.summary_lbl.setWordWrap(True)
        head.addSpacing(6)
        head.addWidget(self.summary_lbl, stretch=1)
        self.legend_lbl = QLabel("B AI Boost   L Limpieza   D Depuracion   E Error")
        self.legend_lbl.setObjectName("PageSubtitle")
        head.addWidget(self.legend_lbl)
        lay.addLayout(head)
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
        self.totals_lbl.setObjectName("MonoValue")
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
        self.setMinimumHeight(18)

    def set_totals(self, totals: dict[str, float]) -> None:
        self.totals = {k: float(totals.get(k, 0.0)) for k in FREED_KINDS}
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
        x, y, row_h = 0.0, 0.0, 18.0
        rects: list[QRectF] = []
        for text in self._items():
            w = 16 + fm.horizontalAdvance(text) + 16
            if x > 0 and x + w > width:
                x, y = 0.0, y + row_h
            rects.append(QRectF(x, y, w, row_h))
            x += w
        return rects, int(y + row_h)

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
        txt = QColor(pal.get("text_primary", "#F3EFE6"))
        sec = QColor(pal.get("text_secondary", "#C2BCB0"))
        p = QPainter(self)
        p.setFont(QFont(UI_FONT_FAMILY, 8))
        rects, _ = self._layout(self.width())
        for kind, rect, text in zip(FREED_KINDS, rects, self._items()):
            sw = QRectF(rect.left(), rect.top() + 4, 10, 10)
            p.fillRect(sw, _with_alpha(txt, FREED_ALPHAS[kind]))
            p.setPen(QPen(_with_alpha(txt, 200), 1))
            p.drawRect(sw.adjusted(0.5, 0.5, -0.5, -0.5))
            p.setPen(sec)
            p.drawText(QRectF(rect.left() + 16, rect.top(), rect.width() - 16, rect.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        p.end()
