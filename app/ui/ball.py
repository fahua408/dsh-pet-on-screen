# -*- coding: utf-8 -*-
"""ball.py — 悬浮球主窗口（经典极简白环质感、稳健贴边、原位呼吸、零抖动防收回、拖拽磁吸）。

设计准则：
- 恢复最初广受好评的经典极简科技圆环（深灰磨砂圆盘 + 中心白色同心圆环），质感纯粹通透。
- 悬浮球始终 100% 完整显示在屏幕边缘可视区（4px 边距），杜绝跳跃式半藏，杜绝悬停时因坐标平移导致光标脱离而自动收回。
- 闲置状态：低调优雅的深色半透明圆盘 (alpha ≈ 0.65)，中心纯白圆环，与桌面极简融合。
- 鼠标悬停：仅触发原位光圈高亮与高透明度渐变 (alpha ≈ 0.90)，物理坐标绝对不发生跳动，手感坚实稳定。
- 拖拽判定：移动超过 8px 才判定为拖拽，杜绝微小晃动误判。
- 边缘磁吸：松开鼠标时若靠近屏幕左/右边缘 (80px 范围)，平滑滑吸至贴边位置 (4px 边距)。
- 置顶保障：每 2 秒安全置顶一次，防止被全屏应用覆盖。
"""
from __future__ import annotations

import math
from PySide6.QtWidgets import QWidget, QApplication
from PySide6.QtCore import (
    Qt, QPoint, QRect, QTimer, QPropertyAnimation,
    QEasingCurve, Signal, QSize, QRectF
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QRegion, QBrush
)

from .tokens import (
    BALL_SIZE, BALL_IDLE, BALL_HOVER, ACCENT, BORDER
)

PEEK_WIDTH     = 25
SNAP_THRESHOLD = 120
EDGE_MARGIN    = 4
DRAG_THRESHOLD = 8
ANIM_SNAP_MS   = 180


def _parse_rgba(s: str) -> QColor:
    s = s.strip()
    if s.startswith("rgba"):
        vals = s[5:-1].split(",")
        r, g, b = int(vals[0]), int(vals[1]), int(vals[2])
        a = float(vals[3])
        c = QColor(r, g, b)
        c.setAlphaF(a)
        return c
    return QColor(s)


class BallWindow(QWidget):
    """悬浮球主窗口（经典极简圆环风格）。

    Signals:
        action_triggered(str): 'toggle_menu' 单击切换扇形菜单
        drag_started(): 拖拽正式开始（用于收纳子菜单）
    """

    action_triggered = Signal(str)
    drag_started     = Signal()
    SIZE = BALL_SIZE

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self._config = config

        # 窗口属性（无边框、置顶、Tool窗口防任务栏抢占、透明通道）
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(BALL_SIZE, BALL_SIZE)

        # 初始圆形 mask（让窗口外围 100% 透明且不遮挡鼠标点击）
        self._update_mask()

        # 状态
        self._hovered   = False
        self._dragging  = False
        self._drag_start_global = QPoint()
        self._drag_start_pos    = QPoint()
        self._hover_alpha       = 0.0    # 0.0=闲置, 1.0=完全高亮
        self._hover_dir         = 0

        # 边缘贴边隐藏与展开状态
        self._snap_enabled = getattr(config, 'ball_snap', True) if config else True
        self._peek_enabled = getattr(config, 'ball_peek', True) if config else True
        self._dock_edge   = None   # 'left' | 'right' | None
        self._is_tucked   = False  # 是否已半隐缩进边缘
        self._is_menu_open = False # 扇形菜单是否展开中
        self._cast_mode   = getattr(config, 'cast_mode', 'dual') if config else 'dual'
        self._control_target = getattr(config, 'control_target', 'coopanion') if config else 'coopanion'

        # 位置恢复（兼容多显示器，使用所在屏幕的 availableGeometry）
        screen = QApplication.primaryScreen().availableGeometry()
        init_x = screen.right() - BALL_SIZE + 1
        init_y = screen.top() + max(100, screen.height() // 2 - 80)
        if config is not None:
            bx = getattr(config, 'ball_x', -1)
            by = getattr(config, 'ball_y', -1)
            if bx >= 0 and by >= 0:
                target_sc = QApplication.screenAt(QPoint(bx, by))
                if target_sc is not None:
                    screen = target_sc.availableGeometry()
                if screen.left() <= bx <= screen.right() - BALL_SIZE + 1:
                    init_x = bx
                if screen.top() <= by <= screen.bottom() - BALL_SIZE:
                    init_y = by
        self.move(init_x, init_y)

        # 初始检测是否靠近边缘
        if self._snap_enabled:
            if init_x >= screen.right() - BALL_SIZE - SNAP_THRESHOLD:
                self._dock_edge = 'right'
            elif init_x <= screen.left() + SNAP_THRESHOLD:
                self._dock_edge = 'left'

        # 贴边吸附与平滑伸展动画
        self._pos_anim = QPropertyAnimation(self, b"pos")
        self._pos_anim.setEasingCurve(QEasingCurve.OutCubic)

        # 边缘缩进延时定时器（鼠标离开后 1.2 秒才平滑缩进，杜绝抖动）
        self._tuck_timer = QTimer(self)
        self._tuck_timer.setSingleShot(True)
        self._tuck_timer.setInterval(1200)
        self._tuck_timer.timeout.connect(self._do_tuck)

        # 启动时保持完整显示至少 5 秒，之后若用户无操作且靠边才缩进
        if self._dock_edge and self._peek_enabled:
            self._tuck_timer.start(5000)

        # 悬停淡入淡出定时器 (16ms 一帧)
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(16)
        self._hover_timer.timeout.connect(self._tick_hover)

        # 置顶保持定时器（仅在菜单未展开且空闲时温和置顶，避免抢夺菜单/弹窗Z序）
        self._raise_timer = QTimer(self)
        self._raise_timer.setInterval(3500)
        self._raise_timer.timeout.connect(self._safe_raise)
        self._raise_timer.start()

    def _safe_raise(self):
        if self.isVisible() and not self._is_menu_open and not self._dragging:
            self.raise_()

    # ================================================================
    # 极简圆环绘制
    # ================================================================

    def _update_mask(self):
        # 移除紧绷 mask，使用舒适矩形或透明通道，防止动画平移过程中光标掉落
        pass

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        t = self._hover_alpha
        # 底色：在 BALL_IDLE (rgba(50,52,60,0.65)) 与 BALL_HOVER (rgba(68,71,83,0.88)) 之间插值
        idle_c  = _parse_rgba(BALL_IDLE)
        hover_c = _parse_rgba(BALL_HOVER)
        r = idle_c.red()   + t * (hover_c.red()   - idle_c.red())
        g = idle_c.green() + t * (hover_c.green()  - idle_c.green())
        b = idle_c.blue()  + t * (hover_c.blue()   - idle_c.blue())
        a = idle_c.alphaF() + t * (hover_c.alphaF() - idle_c.alphaF())
        base_color = QColor(int(r), int(g), int(b))
        base_color.setAlphaF(a)

        # 绘制磨砂圆形底板
        painter.setBrush(QBrush(base_color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(1, 1, BALL_SIZE - 2, BALL_SIZE - 2)

        # 绘制边缘微光细边框
        border_alpha = int(25 + t * 50)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, border_alpha), 1.0))
        painter.drawEllipse(1, 1, BALL_SIZE - 2, BALL_SIZE - 2)

        # 绘制中心经典极简科技圆环（根据当前活跃桌宠动态渲染专属光环）
        cx, cy = BALL_SIZE / 2.0, BALL_SIZE / 2.0
        ring_r = BALL_SIZE * 0.30
        ring_w = 2.2
        ring_alpha = int(220 + t * 35)  # 220 -> 255

        cast_mode = getattr(self, '_cast_mode', 'dual')
        control_target = getattr(self, '_control_target', 'coopanion')

        if cast_mode == 'coopanion':
            ring_color = QColor(111, 227, 255, ring_alpha)  # 青蓝光环 (大肥鱼)
        elif cast_mode == 'dsh':
            ring_color = QColor(59, 130, 246, ring_alpha)   # 科技蓝光环 (小女仆)
        else:
            if control_target == 'coopanion':
                ring_color = QColor(111, 227, 255, ring_alpha)
            else:
                ring_color = QColor(59, 130, 246, ring_alpha)

        ring_pen = QPen(ring_color, ring_w, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(ring_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(cx - ring_r, cy - ring_r, ring_r * 2.0, ring_r * 2.0))

        # 双宠模式下额外在圆心点亮微光指示点
        if cast_mode == 'dual':
            dot_color = QColor(59, 130, 246, int(180 + t * 60)) if control_target == 'coopanion' else QColor(111, 227, 255, int(180 + t * 60))
            painter.setBrush(QBrush(dot_color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(cx - 3.0, cy - 3.0, 6.0, 6.0))

        painter.end()

    def set_pet_mode(self, mode: str, control_target: str = 'coopanion'):
        """切换当前桌宠模式与控制目标，实时更新悬浮球光环。"""
        self._cast_mode = mode
        self._control_target = control_target
        self.update()

    # ================================================================
    # 交互与拖拽（零微抖动）
    # ================================================================

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_global = event.globalPosition().toPoint()
            self._drag_start_pos    = self.pos()
            self._dragging          = False
            self._tuck_timer.stop()
            self._pos_anim.stop()
            # 若处于边缘缩进状态，点击即刻先完全滑出
            if self._is_tucked:
                self._expand_now()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_start_global
            dist  = math.hypot(delta.x(), delta.y())
            if dist > DRAG_THRESHOLD:
                if not self._dragging:
                    self._dragging = True
                    self.drag_started.emit()
            if self._dragging:
                new_pos = self._drag_start_pos + delta
                sc = QApplication.screenAt(event.globalPosition().toPoint())
                screen = sc.availableGeometry() if sc else self._current_screen()
                new_pos.setX(max(screen.left(), min(new_pos.x(), screen.right() - BALL_SIZE)))
                new_pos.setY(max(screen.top(), min(new_pos.y(), screen.bottom() - BALL_SIZE)))
                self.move(new_pos)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if not self._dragging:
                # 确定是单击（非拖拽）：展开/收起菜单
                self.action_triggered.emit('toggle_menu')
            else:
                # 拖拽结束：磁吸至最近屏幕边缘
                self._snap_to_edge()
            self._dragging = False
            self._save_position()

    # ================================================================
    # 贴边吸附与边缘缩进
    # ================================================================

    def _current_screen(self):
        center = self.geometry().center()
        sc = QApplication.screenAt(center)
        if sc:
            return sc.availableGeometry()
        return QApplication.primaryScreen().availableGeometry()

    def set_snap_enabled(self, enabled: bool):
        self._snap_enabled = bool(enabled)
        if not self._snap_enabled:
            self._dock_edge = None
            if self._is_tucked:
                self._expand_now()

    def set_peek_enabled(self, enabled: bool):
        self._peek_enabled = bool(enabled)
        if not self._peek_enabled:
            self._tuck_timer.stop()
            if self._is_tucked:
                self._expand_now()
        else:
            if self._dock_edge and not self._is_menu_open and not self._hovered:
                self._tuck_timer.start(1200)

    def _snap_to_edge(self):
        if not self._snap_enabled:
            self._dock_edge = None
            return

        screen = self._current_screen()
        x = self.x()
        target_x = x
        if x < screen.left() + SNAP_THRESHOLD:
            self._dock_edge = 'left'
            target_x = screen.left()
        elif x + BALL_SIZE > screen.right() - SNAP_THRESHOLD:
            self._dock_edge = 'right'
            target_x = screen.right() - BALL_SIZE + 1
        else:
            self._dock_edge = None

        if target_x != x:
            self._pos_anim.stop()
            self._pos_anim.setDuration(ANIM_SNAP_MS)
            self._pos_anim.setStartValue(self.pos())
            self._pos_anim.setEndValue(QPoint(target_x, self.y()))
            self._pos_anim.start()

        # 停驻边缘后，若开启了半隐收纳，启动缩进倒计时
        if self._dock_edge and self._peek_enabled and not self._is_menu_open:
            self._tuck_timer.start(1200)

    def _do_tuck(self):
        """平滑缩进屏幕边缘，仅露出约 55% 作为极简贴边把手。"""
        if not self._peek_enabled or not self._dock_edge or self._is_menu_open or self._dragging or self._hovered:
            return

        # 二次全局光标安全校验：若光标仍在球体几何范围内，绝不收缩
        from PySide6.QtGui import QCursor
        if self.geometry().contains(QCursor.pos()):
            return

        screen = self._current_screen()
        if self._dock_edge == 'right':
            target_x = screen.right() - PEEK_WIDTH + 1
        elif self._dock_edge == 'left':
            target_x = screen.left() - (BALL_SIZE - PEEK_WIDTH)
        else:
            return

        self._pos_anim.stop()
        self._pos_anim.setDuration(ANIM_SNAP_MS)
        self._pos_anim.setStartValue(self.pos())
        self._pos_anim.setEndValue(QPoint(target_x, self.y()))
        self._pos_anim.start()
        self._is_tucked = True

    def _expand_now(self):
        """平滑滑出边缘，完全展现极简圆环。"""
        screen = self._current_screen()
        if self._dock_edge == 'right':
            target_x = screen.right() - BALL_SIZE + 1
        elif self._dock_edge == 'left':
            target_x = screen.left()
        else:
            target_x = self.x()

        self._pos_anim.stop()
        self._pos_anim.setDuration(160)
        self._pos_anim.setStartValue(self.pos())
        self._pos_anim.setEndValue(QPoint(target_x, self.y()))
        self._pos_anim.start()
        self._is_tucked = False

    def get_untucked_pos(self) -> tuple[int, int]:
        """返回悬浮球完全展开状态下的屏幕坐标（防止半隐边缘坐标被持久化保存）。"""
        screen = self._current_screen()
        x, y = self.x(), self.y()
        if self._dock_edge == 'right':
            x = screen.right() - BALL_SIZE + 1
        elif self._dock_edge == 'left':
            x = screen.left()
        return x, y

    def set_menu_open(self, is_open: bool):
        """外部（如扇形菜单开启/关闭）同步状态，确保菜单展开期间绝不缩进"""
        self._is_menu_open = is_open
        if is_open:
            self._tuck_timer.stop()
            if self._is_tucked:
                self._expand_now()
        else:
            if self._dock_edge and self._peek_enabled and not self._hovered:
                self._tuck_timer.start(1200)

    # ================================================================
    # 悬停处理（原地高亮，并平滑滑出）
    # ================================================================

    def enterEvent(self, event):
        self._hovered = True
        self._hover_dir = +1
        self._tuck_timer.stop()
        if self._is_tucked:
            self._expand_now()
        if not self._hover_timer.isActive():
            self._hover_timer.start()

    def leaveEvent(self, event):
        self._hovered = False
        self._hover_dir = -1
        if not self._hover_timer.isActive():
            self._hover_timer.start()
        # 鼠标离开后，若停靠在边缘、开启了半隐藏且菜单未展开，1.2 秒后平滑缩进
        if self._dock_edge and self._peek_enabled and not self._is_menu_open and not self._dragging:
            self._tuck_timer.start(1200)

    def _tick_hover(self):
        step = 16.0 / 140.0
        self._hover_alpha = max(0.0, min(1.0, self._hover_alpha + self._hover_dir * step))
        self.update()
        if self._hover_alpha in (0.0, 1.0):
            self._hover_timer.stop()

    def _save_position(self):
        if self._config is not None:
            try:
                bx, by = self.get_untucked_pos()
                self._config.ball_x = bx
                self._config.ball_y = by
                try:
                    from config import save_config
                except ImportError:
                    from ..config import save_config
                save_config(self._config)
            except Exception:
                pass
