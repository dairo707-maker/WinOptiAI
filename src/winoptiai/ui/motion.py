"""Motor sutil de minianimaciones reactivas al puntero y transicion entre vistas (TRODAI Motion)."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from typing import Callable

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QStackedWidget, QWidget

from ..core.win32_bridge import is_battery_saver_active, windows_animations_enabled
from .theme import get_palette


@dataclass(frozen=True)
class MotionGuardState:
    should_animate: bool
    status_code: str
    target_fps: int


class MotionPerformanceGuard:
    """Evalua preferencias de Windows, ahorro de bateria, visibilidad y carga pesada."""

    def __init__(
        self,
        *,
        os_animations_fn: Callable[[], bool] | None = None,
        battery_saver_fn: Callable[[], bool] | None = None,
        headless_fn: Callable[[], bool] | None = None,
    ) -> None:
        self._os_animations_fn = os_animations_fn or windows_animations_enabled
        self._battery_saver_fn = battery_saver_fn or is_battery_saver_active
        self._headless_fn = headless_fn or (lambda: os.environ.get("QT_QPA_PLATFORM") == "offscreen")

    def evaluate(
        self,
        *,
        window_visible: bool = True,
        heavy_task_active: bool = False,
        static_override: bool = False,
    ) -> MotionGuardState:
        if static_override:
            return MotionGuardState(False, "static", 0)
        if self._headless_fn():
            return MotionGuardState(False, "offscreen", 0)
        if not window_visible:
            return MotionGuardState(False, "hidden", 0)
        if heavy_task_active:
            return MotionGuardState(False, "paused", 0)
        if not self._os_animations_fn():
            return MotionGuardState(False, "os_off", 0)
        if self._battery_saver_fn():
            return MotionGuardState(False, "battery", 0)
        return MotionGuardState(True, "active", 30)


class MotionBackdropWidget(QWidget):
    """Superficie solida 0px con malla poligonal sutil reactiva al puntero para Sidebar, TopBar y Banners."""

    def __init__(
        self,
        surface_kind: str = "sidebar",
        theme_mode: str = "dark",
        parent: QWidget | None = None,
        *,
        guard: MotionPerformanceGuard | None = None,
        preset: str = "polygonal_mesh",
    ) -> None:
        super().__init__(parent)
        self._surface_kind = surface_kind
        self._theme_mode = "light" if theme_mode == "light" else "dark"
        self._guard = guard or MotionPerformanceGuard()
        self._preset = preset
        self._heavy_task_active = False
        self._phase = 0.0
        self._pointer_pos: QPointF | None = None
        self._last_polled_cursor: QPoint | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._on_tick)

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setMouseTracking(True)

    def guard_state(self) -> MotionGuardState:
        return self._guard.evaluate(
            window_visible=self.isVisible(),
            heavy_task_active=self._heavy_task_active,
            static_override=(self._preset == "none"),
        )

    def set_theme_mode(self, mode: str) -> None:
        norm = "light" if mode == "light" else "dark"
        if norm != self._theme_mode:
            self._theme_mode = norm
            self.update()

    def set_heavy_task_active(self, active: bool) -> None:
        val = bool(active)
        if val != self._heavy_task_active:
            self._heavy_task_active = val
            self._sync_motion_state()

    def _sync_motion_state(self) -> None:
        state = self.guard_state()
        if state.should_animate:
            interval = 33 if state.target_fps <= 30 else 16
            if self._timer.interval() != interval:
                self._timer.setInterval(interval)
            if not self._timer.isActive():
                self._timer.start()
        elif self._timer.isActive():
            self._timer.stop()

    def _on_tick(self) -> None:
        if self.isVisible():
            try:
                cur = QCursor.pos()
                if self._last_polled_cursor is None:
                    self._last_polled_cursor = cur
                elif cur != self._last_polled_cursor:
                    self._last_polled_cursor = cur
                    local = self.mapFromGlobal(cur)
                    if 0 <= local.x() <= self.width() and 0 <= local.y() <= self.height():
                        self._pointer_pos = QPointF(local)
                    else:
                        self._pointer_pos = None
            except Exception:  # noqa: BLE001
                pass
        self._phase = (self._phase + 0.022) % (math.tau * 100.0)
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._pointer_pos = QPointF(event.position())
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._pointer_pos is not None:
            self._pointer_pos = None
            self.update()
        super().leaveEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_motion_state()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._pointer_pos = None
        if self._timer.isActive():
            self._timer.stop()
        super().hideEvent(event)

    def cleanup(self) -> None:
        if self._timer.isActive():
            self._timer.stop()

    def _draw_polygonal_mesh(self, painter: QPainter, pal: dict[str, str], opacity: float) -> None:
        w, h = float(self.width()), float(self.height())
        if w < 12 or h < 12:
            return
        accent = QColor(pal.get("motion_cyan", pal["accent"]))
        alt = QColor(pal.get("motion_blue", pal["accent_alt"]))
        cols = max(2, min(14, int(round(w / 90.0))))
        rows = max(2, min(10, int(round(h / 72.0))))
        ptr = self._pointer_pos
        pts: list[list[QPointF]] = []
        for r in range(rows + 1):
            row_pts: list[QPointF] = []
            for c in range(cols + 1):
                bx = (c / cols) * w
                by = (r / rows) * h
                if 0 < c < cols and 0 < r < rows:
                    bx += math.sin(self._phase * 1.1 + c * 1.3 + r) * (w * 0.032)
                    by += math.cos(self._phase * 0.9 + r * 1.5 + c) * (h * 0.045)
                    if ptr is not None:
                        dx = ptr.x() - bx
                        dy = ptr.y() - by
                        dist = math.hypot(dx, dy)
                        if 1.0 < dist < 240.0:
                            pull = (1.0 - dist / 240.0) * 18.0
                            bx += (dx / dist) * pull
                            by += (dy / dist) * pull
                row_pts.append(QPointF(bx, by))
            pts.append(row_pts)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        line_pen = QPen(accent, 1.0)
        for r in range(rows):
            for c in range(cols):
                p00 = pts[r][c]
                p10 = pts[r][c + 1]
                p01 = pts[r + 1][c]
                p11 = pts[r + 1][c + 1]
                pulse = 0.5 + 0.5 * math.sin(self._phase + c * 0.7 + r * 0.9)
                fill_color = QColor(accent if (r + c) % 2 == 0 else alt)
                fill_color.setAlpha(int((14 + pulse * 30) * opacity))
                painter.setBrush(fill_color)
                line_color = QColor(accent)
                line_color.setAlpha(int((36 + pulse * 48) * opacity))
                line_pen.setColor(line_color)
                painter.setPen(line_pen)
                painter.drawPolygon(QPolygonF([p00, p10, p11]))
                painter.drawPolygon(QPolygonF([p00, p11, p01]))
        painter.restore()

    def paintEvent(self, _event) -> None:  # noqa: N802
        pal = get_palette(self._theme_mode)
        base_hex = pal["bg_glass_elevated"] if self._surface_kind == "banner" else pal["bg_sidebar"]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(base_hex))

        if self._preset != "none":
            eff_opacity = 0.30 if self._theme_mode == "dark" else 0.22
            if self._surface_kind == "banner":
                eff_opacity += 0.08
            self._draw_polygonal_mesh(painter, pal, eff_opacity)

        painter.setPen(QPen(QColor(pal["border_hairline"]), 1))
        if self._surface_kind == "sidebar" and self.width() > 0:
            painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        elif self._surface_kind in ("topbar", "banner") and self.height() > 0:
            painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        painter.end()


class ViewTransitionController:
    """Transicion horizontal sutil de 145 ms al cambiar de vista (sin QGraphicsOpacityEffect)."""

    def __init__(self, stack: QStackedWidget, guard: MotionPerformanceGuard | None = None) -> None:
        self._stack = stack
        self._guard = guard or MotionPerformanceGuard()
        self._active_anim: QPropertyAnimation | None = None
        self._active_target: QWidget | None = None

    def switch_to(self, index: int, *, immediate: bool = False) -> None:
        if index < 0 or index >= self._stack.count() or self._stack.currentIndex() == index:
            return
        if self._active_anim is not None:
            try:
                self._active_anim.stop()
            except Exception:  # noqa: BLE001
                pass
            if self._active_target is not None:
                self._active_target.move(0, 0)
            self._active_anim = None
            self._active_target = None

        state = self._guard.evaluate(window_visible=self._stack.isVisible())
        if immediate or not state.should_animate:
            self._stack.setCurrentIndex(index)
            return

        target = self._stack.widget(index)
        self._stack.setCurrentIndex(index)
        if target is None or target.width() <= 0:
            return

        anim = QPropertyAnimation(target, b"pos", target)
        anim.setDuration(145)
        anim.setStartValue(QPoint(14, 0))
        anim.setEndValue(QPoint(0, 0))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _cleanup() -> None:
            try:
                target.move(0, 0)
            except Exception:  # noqa: BLE001
                pass
            self._active_anim = None
            self._active_target = None

        anim.finished.connect(_cleanup)
        self._active_anim = anim
        self._active_target = target
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
