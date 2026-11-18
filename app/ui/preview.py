# preview.py — 实时水冷屏画面缩略图控件
#
# PreviewWidget:
#   - 280×210 显示水冷屏实时画面（640×480 → 等比缩放）
#   - update_frame(jpeg_bytes) 接收渲染线程推送的帧
#   - 3秒未收到帧显示"未连接"遮罩

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import (
    QPainter, QColor, QPixmap, QBrush, QPen, QPainterPath, QFont
)

from .tokens import (
    SURFACE, BORDER, ACCENT, DANGER,
    TEXT_MUTED, TEXT_PRIMARY,
    PREVIEW_W, PREVIEW_H, RADIUS
)


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


class PreviewWidget(QWidget):
    """以 280×210 显示水冷屏实时画面（640×480 → 等比缩放）。

    外部调用 update_frame(jpeg_bytes) 刷新画面。
    3 秒内无新帧则显示红色 "⚠ 未连接" 遮罩。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(PREVIEW_W, PREVIEW_H)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)

        self._pixmap: QPixmap | None = None
        self._is_connected = False

        # 超时检测定时器
        self._conn_timer = QTimer(self)
        self._conn_timer.setSingleShot(True)
        self._conn_timer.setInterval(3000)
        self._conn_timer.timeout.connect(self._on_timeout)

    # ================================================================
    # 公共接口
    # ================================================================

    def update_frame(self, jpeg_bytes: bytes):
        """接收来自 renderer 的 JPEG bytes，立即刷新显示。"""
        if not jpeg_bytes:
            return
        px = QPixmap()
        ok = px.loadFromData(jpeg_bytes)
        if ok and not px.isNull():
            self._pixmap = px
        self._is_connected = True
        # 重置超时计时器
        self._conn_timer.start()
        self.update()

    # 别名兼容
    set_frame = update_frame

    # ================================================================
    # 绘制
    # ================================================================

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        w = float(self.width())
        h = float(self.height())
        rr = 10.0
        rect = QRectF(0, 0, w, h)

        # ① 深色背景 + 1px 圆角描边
        clip_path = QPainterPath()
        clip_path.addRoundedRect(rect, rr, rr)
        painter.setClipPath(clip_path)

        bg = _parse_rgba(SURFACE)
        bg.setAlphaF(0.95)
        painter.fillRect(rect.toRect(), bg)

        # ② 画面或提示文字
        if self._pixmap is not None:
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            # 640x480 与预览框 (320x240 / 280x210) 严格同属 4:3 比例，直接硬件加速绘制，彻底杜绝每帧 CPU 重新分配 QPixmap 引起的卡顿
            painter.drawPixmap(rect.toRect(), self._pixmap)
        else:
            # 无画面提示
            painter.setClipping(False)
            font = QFont("Microsoft YaHei UI", 12)
            painter.setFont(font)
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(rect, Qt.AlignCenter, "等待连接…")

        # ③ 未连接遮罩
        if not self._is_connected and self._pixmap is not None:
            self._draw_disconnected_overlay(painter, rect)

        # ④ 描边（放最上层）
        painter.setClipping(False)
        border_c = _parse_rgba(BORDER)
        border_c.setAlphaF(0.18)
        painter.setPen(QPen(border_c, 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), rr, rr)

        painter.end()

    def _draw_disconnected_overlay(self, painter: QPainter, rect: QRectF):
        """半透明红色遮罩 + '⚠ 未连接' 文字"""
        overlay = QColor(0, 0, 0, 140)
        painter.fillRect(rect.toRect(), overlay)

        warn_color = QColor(DANGER)
        font = QFont("Microsoft YaHei UI", 13)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(warn_color)
        painter.drawText(rect, Qt.AlignCenter, "⚠  未连接")

    # ================================================================
    # 超时回调
    # ================================================================

    def _on_timeout(self):
        """3 秒无新帧，标记为断连"""
        self._is_connected = False
        self.update()
