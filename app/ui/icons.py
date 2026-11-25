# icons.py — 纯 QPainter 矢量图标绘制（全部 Lucide 风格细线）
# 所有图标均通过 QPainter 绘制，不依赖任何外部图片资源
# 线条规范：pen width = max(1.5, size * 0.075)，RoundCap + RoundJoin

import math
from PySide6.QtGui import QPainter, QPen, QColor, QPainterPath, QBrush, QFont
from PySide6.QtCore import Qt, QPointF, QRectF


def _pen(painter: QPainter, size: float, color: QColor) -> QPen:
    """创建标准细线画笔（圆头圆角）"""
    width = max(1.5, size * 0.075)
    pen = QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    return pen


def _draw_size(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """maximize-2 风格：↗↙ 对角双向箭头，表示尺寸调节"""
    _pen(painter, size, color)
    r = size * 0.35
    ah = size * 0.15  # arrowhead length

    # 左下角 ↙ 箭头组
    x0, y0 = cx - r, cy + r
    # 对角线
    painter.drawLine(QPointF(cx - r * 0.1, cy + r * 0.1), QPointF(x0, y0))
    # 箭头头部
    painter.drawLine(QPointF(x0, y0), QPointF(x0 + ah, y0))
    painter.drawLine(QPointF(x0, y0), QPointF(x0, y0 - ah))

    # 右上角 ↗ 箭头组
    x1, y1 = cx + r, cy - r
    painter.drawLine(QPointF(cx + r * 0.1, cy - r * 0.1), QPointF(x1, y1))
    painter.drawLine(QPointF(x1, y1), QPointF(x1 - ah, y1))
    painter.drawLine(QPointF(x1, y1), QPointF(x1, y1 + ah))


def _draw_background(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """image 风格：圆角矩形边框 + 左上小圆点 + 右下折线山峦"""
    _pen(painter, size, color)
    r = size * 0.38
    rr = size * 0.10  # corner radius of image rect

    # 外框（圆角矩形）
    rect = QRectF(cx - r, cy - r * 0.78, r * 2, r * 1.56)
    path = QPainterPath()
    path.addRoundedRect(rect, rr, rr)
    painter.drawPath(path)

    # 左上小圆点（太阳/光圈）
    dot_r = size * 0.072
    painter.drawEllipse(QPointF(cx - r * 0.52, cy - r * 0.38), dot_r, dot_r)

    # 右下折线山峦（三角峰）
    pw = size * 0.075
    painter.setPen(QPen(color, pw, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    mtn = QPainterPath()
    # 左峰
    mtn.moveTo(cx - r * 0.72, cy + r * 0.50)
    mtn.lineTo(cx - r * 0.20, cy - r * 0.05)
    mtn.lineTo(cx + r * 0.10, cy + r * 0.28)
    # 右峰（更高）
    mtn.lineTo(cx + r * 0.42, cy - r * 0.28)
    mtn.lineTo(cx + r * 0.78, cy + r * 0.50)
    painter.drawPath(mtn)


def _draw_touch(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """heart 风格：数学平滑心形曲线，QPainterPath 拟合"""
    _pen(painter, size, color)
    r = size * 0.33

    path = QPainterPath()
    # 心形参数方程近似（贝塞尔拟合）
    # 顶点在上中，向左右延伸，底部汇聚成尖
    top_y = cy - r * 0.28
    # 左半圆控制点
    path.moveTo(cx, cy + r * 0.60)         # 底部尖端
    path.cubicTo(
        cx - r * 1.05, cy + r * 0.10,     # 控制点1
        cx - r * 1.10, cy - r * 0.72,     # 控制点2
        cx - r * 0.45, top_y - r * 0.22   # 左上顶
    )
    path.cubicTo(
        cx - r * 0.05, cy - r * 0.90,     # 控制点3
        cx + r * 0.05, cy - r * 0.90,     # 控制点4
        cx + r * 0.45, top_y - r * 0.22   # 右上顶
    )
    path.cubicTo(
        cx + r * 1.10, cy - r * 0.72,     # 控制点5
        cx + r * 1.05, cy + r * 0.10,     # 控制点6
        cx, cy + r * 0.60                 # 底部尖端（闭合）
    )
    painter.drawPath(path)


def _draw_stream(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """monitor + 播放三角：圆角矩形显示器 + 居中实心三角"""
    _pen(painter, size, color)
    rw = size * 0.42
    rh = size * 0.32
    rr = size * 0.07
    bot_stem = size * 0.10
    bot_base = size * 0.18
    top = cy - rh
    bot = cy + rh

    # 显示器外框
    rect = QRectF(cx - rw, top, rw * 2, rh * 2 - bot_stem)
    path = QPainterPath()
    path.addRoundedRect(rect, rr, rr)
    painter.drawPath(path)

    # 底部支架
    painter.drawLine(QPointF(cx, bot - bot_stem), QPointF(cx, bot))
    painter.drawLine(QPointF(cx - bot_base, bot), QPointF(cx + bot_base, bot))

    # 居中实心播放三角
    tri_r = size * 0.14
    tri = QPainterPath()
    tri.moveTo(cx - tri_r * 0.70, cy - rh * 0.45 + tri_r * 1.0)
    tri.lineTo(cx - tri_r * 0.70, cy - rh * 0.45 - tri_r * 1.0)
    tri.lineTo(cx + tri_r * 1.10, cy - rh * 0.45)
    tri.closeSubpath()
    painter.setBrush(QBrush(color))
    painter.setPen(Qt.NoPen)
    painter.drawPath(tri)


def _draw_settings(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """settings 风格：内圆 + 8等分外凸齿，用 QPainterPath"""
    _pen(painter, size, color)
    inner_r = size * 0.155
    outer_r = size * 0.33
    tooth_r = size * 0.082
    n_teeth = 8

    # 内圆
    painter.drawEllipse(QPointF(cx, cy), inner_r, inner_r)

    # 齿轮路径
    gear = QPainterPath()
    for i in range(n_teeth):
        angle_mid = math.radians(i * 360 / n_teeth)
        angle_off = math.radians(360 / n_teeth * 0.38)
        # 外圆上的两个边缘点（齿侧）
        a1 = angle_mid - angle_off
        a2 = angle_mid + angle_off
        # 内圆上对应的衔接点
        ai1 = angle_mid - angle_off * 1.6
        ai2 = angle_mid + angle_off * 1.6

        p_i1 = QPointF(cx + outer_r * 0.72 * math.cos(ai1), cy + outer_r * 0.72 * math.sin(ai1))
        p_o1 = QPointF(cx + outer_r * math.cos(a1), cy + outer_r * math.sin(a1))
        p_top = QPointF(cx + (outer_r + tooth_r) * math.cos(angle_mid),
                        cy + (outer_r + tooth_r) * math.sin(angle_mid))
        p_o2 = QPointF(cx + outer_r * math.cos(a2), cy + outer_r * math.sin(a2))
        p_i2 = QPointF(cx + outer_r * 0.72 * math.cos(ai2), cy + outer_r * 0.72 * math.sin(ai2))

        if i == 0:
            gear.moveTo(p_i1)
        else:
            gear.lineTo(p_i1)
        gear.lineTo(p_o1)
        gear.lineTo(p_top)
        gear.lineTo(p_o2)
        gear.lineTo(p_i2)

    gear.closeSubpath()
    painter.setPen(QPen(color, max(1.5, size * 0.075), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(gear)


def _draw_collapse(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """chevron-left 风格：单 < 折角，大号，简洁"""
    _pen(painter, size, color)
    arm = size * 0.28
    path = QPainterPath()
    path.moveTo(cx + arm * 0.5, cy - arm)
    path.lineTo(cx - arm * 0.5, cy)
    path.lineTo(cx + arm * 0.5, cy + arm)
    painter.drawPath(path)


def _draw_panel(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """layout-panel 风格：大圆角矩形 + 内部3条横线"""
    _pen(painter, size, color)
    rw = size * 0.38
    rh = size * 0.30
    rr = size * 0.09

    # 外框
    rect = QRectF(cx - rw, cy - rh, rw * 2, rh * 2)
    path = QPainterPath()
    path.addRoundedRect(rect, rr, rr)
    painter.drawPath(path)

    # 3 条内部横线（模拟内容布局）
    line_w = rw * 1.1
    offsets = [-rh * 0.42, 0, rh * 0.42]
    for dy in offsets:
        lx = cx - line_w * 0.50
        rx = cx + line_w * 0.50
        painter.drawLine(QPointF(lx, cy + dy), QPointF(rx, cy + dy))


def _draw_chat(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """Lucide message-square 风格：圆角对话气泡 + 左下微尾巴"""
    _pen(painter, size, color)
    r = size * 0.32
    path = QPainterPath()
    # 矩形气泡
    top_y = cy - r * 0.75
    bot_y = cy + r * 0.40
    path.moveTo(cx - r, top_y)
    path.lineTo(cx + r, top_y)
    path.lineTo(cx + r, bot_y)
    path.lineTo(cx - r * 0.1, bot_y)
    path.lineTo(cx - r * 0.55, cy + r * 0.85)  # 气泡尖角
    path.lineTo(cx - r * 0.40, bot_y)
    path.lineTo(cx - r, bot_y)
    path.closeSubpath()
    painter.drawPath(path)
    # 内部横线
    painter.drawLine(QPointF(cx - r * 0.48, cy - r * 0.20), QPointF(cx + r * 0.48, cy - r * 0.20))
    painter.drawLine(QPointF(cx - r * 0.48, cy + r * 0.10), QPointF(cx + r * 0.15, cy + r * 0.10))


def _draw_voice(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """Lucide mic 风格：麦克风胶囊 + 底部圆弧支撑 + 支架线"""
    _pen(painter, size, color)
    r = size * 0.20
    # 麦克风顶部胶囊 (圆角矩形)
    cap_rect = QRectF(cx - r * 0.55, cy - r * 1.45, r * 1.1, r * 1.85)
    cap = QPainterPath()
    cap.addRoundedRect(cap_rect, r * 0.55, r * 0.55)
    painter.drawPath(cap)
    # 底部圆弧 (U形)
    u_path = QPainterPath()
    u_path.arcMoveTo(QRectF(cx - r * 1.05, cy - r * 0.8, r * 2.1, r * 1.9), 0)
    u_path.arcTo(QRectF(cx - r * 1.05, cy - r * 0.8, r * 2.1, r * 1.9), 0, -180)
    painter.drawPath(u_path)
    # 垂直支架
    painter.drawLine(QPointF(cx, cy + r * 1.1), QPointF(cx, cy + r * 1.7))
    # 底部横杆
    painter.drawLine(QPointF(cx - r * 0.75, cy + r * 1.7), QPointF(cx + r * 0.75, cy + r * 1.7))


def _draw_toggle_display(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """屏幕切换风格：桌面大屏与小屏切换指示"""
    _pen(painter, size, color)
    rw = size * 0.36
    rh = size * 0.25
    rect = QRectF(cx - rw, cy - rh * 1.1, rw * 2, rh * 1.7)
    path = QPainterPath()
    path.addRoundedRect(rect, size * 0.06, size * 0.06)
    painter.drawPath(path)
    # 支柱
    painter.drawLine(QPointF(cx, cy + rh * 0.6), QPointF(cx, cy + rh * 1.0))
    painter.drawLine(QPointF(cx - rw * 0.5, cy + rh * 1.0), QPointF(cx + rw * 0.5, cy + rh * 1.0))
    # 屏幕内双向微箭头
    ah = size * 0.07
    painter.drawLine(QPointF(cx - rw * 0.35, cy - rh * 0.25), QPointF(cx + rw * 0.35, cy - rh * 0.25))
    painter.drawLine(QPointF(cx + rw * 0.35 - ah, cy - rh * 0.25 - ah), QPointF(cx + rw * 0.35, cy - rh * 0.25))
    painter.drawLine(QPointF(cx + rw * 0.35, cy + rh * 0.15), QPointF(cx - rw * 0.35, cy + rh * 0.15))
    painter.drawLine(QPointF(cx - rw * 0.35 + ah, cy + rh * 0.15 + ah), QPointF(cx - rw * 0.35, cy + rh * 0.15))


def _draw_balance(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """wallet / coin 风格：纯金币圆环 + 居中符号"""
    _pen(painter, size, color)
    r = size * 0.35
    painter.drawEllipse(QPointF(cx, cy), r, r)
    # 居中画一个简洁的货币符号或者金币内圈
    inner_r = r * 0.65
    painter.drawEllipse(QPointF(cx, cy), inner_r, inner_r)
    # 横竖微线
    painter.drawLine(QPointF(cx, cy - inner_r * 0.5), QPointF(cx, cy + inner_r * 0.5))


def _draw_whisper(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """sparkles / whisper 风格：聊天气泡 + 微光星芒"""
    _pen(painter, size, color)
    r = size * 0.32
    # 气泡
    path = QPainterPath()
    path.addRoundedRect(QRectF(cx - r, cy - r * 0.7, r * 1.8, r * 1.4), size * 0.08, size * 0.08)
    painter.drawPath(path)
    # 三个圆点
    dot_r = size * 0.035
    for dx in (-r * 0.4, 0, r * 0.4):
        painter.drawEllipse(QPointF(cx - r * 0.1 + dx, cy), dot_r, dot_r)


def _draw_star(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """sparkles / star 风格：四角微光星芒"""
    _pen(painter, size, color)
    r = size * 0.36
    path = QPainterPath()
    path.moveTo(cx, cy - r)
    path.quadTo(cx, cy, cx + r, cy)
    path.quadTo(cx, cy, cx, cy + r)
    path.quadTo(cx, cy, cx - r, cy)
    path.quadTo(cx, cy, cx, cy - r)
    painter.drawPath(path)


def _draw_actions(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """clapperboard 风格：场记板"""
    _pen(painter, size, color)
    r = size * 0.32
    rect = QRectF(cx - r, cy - r * 0.8, r * 2.0, r * 1.6)
    painter.drawRoundedRect(rect, 4, 4)
    painter.drawLine(QPointF(cx - r, cy - r * 0.2), QPointF(cx + r, cy - r * 0.2))
    painter.drawLine(QPointF(cx - r * 0.3, cy - r * 0.8), QPointF(cx - r * 0.5, cy - r * 0.2))
    painter.drawLine(QPointF(cx + r * 0.3, cy - r * 0.8), QPointF(cx + r * 0.1, cy - r * 0.2))


def _draw_weather(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """sun & cloud 风格：天气"""
    _pen(painter, size, color)
    r = size * 0.32
    path = QPainterPath()
    path.arcMoveTo(QRectF(cx - r * 0.9, cy - r * 0.1, r * 0.7, r * 0.6), 180)
    path.arcTo(QRectF(cx - r * 0.9, cy - r * 0.1, r * 0.7, r * 0.6), 180, 180)
    path.arcTo(QRectF(cx - r * 0.4, cy - r * 0.5, r * 0.9, r * 0.9), 160, 190)
    path.arcTo(QRectF(cx + r * 0.2, cy - r * 0.1, r * 0.7, r * 0.6), 120, 190)
    path.closeSubpath()
    painter.drawPath(path)


def _draw_todo(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """checklist 风格：待办清单"""
    _pen(painter, size, color)
    r = size * 0.34
    rect = QRectF(cx - r * 0.7, cy - r * 0.8, r * 1.4, r * 1.7)
    painter.drawRoundedRect(rect, 3, 3)
    clip = QRectF(cx - r * 0.3, cy - r * 0.95, r * 0.6, r * 0.3)
    painter.drawRoundedRect(clip, 2, 2)
    painter.drawLine(QPointF(cx - r * 0.4, cy - r * 0.1), QPointF(cx - r * 0.25, cy + r * 0.1))
    painter.drawLine(QPointF(cx - r * 0.25, cy + r * 0.1), QPointF(cx - r * 0.05, cy - r * 0.2))
    painter.drawLine(QPointF(cx + r * 0.1, cy - r * 0.05), QPointF(cx + r * 0.45, cy - r * 0.05))
    painter.drawLine(QPointF(cx - r * 0.4, cy + r * 0.4), QPointF(cx + r * 0.45, cy + r * 0.4))


def _draw_sleep(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """moon 风格：睡眠弯月"""
    _pen(painter, size, color)
    r = size * 0.34
    path = QPainterPath()
    path.arcMoveTo(QRectF(cx - r, cy - r, r * 2, r * 2), 60)
    path.arcTo(QRectF(cx - r, cy - r, r * 2, r * 2), 60, 240)
    path.arcTo(QRectF(cx - r * 0.4, cy - r, r * 1.6, r * 2), 290, -220)
    path.closeSubpath()
    painter.drawPath(path)


def _draw_dice(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """dice 风格：随机骰子"""
    _pen(painter, size, color)
    r = size * 0.32
    rect = QRectF(cx - r, cy - r, r * 2, r * 2)
    painter.drawRoundedRect(rect, 5, 5)
    dot_r = size * 0.04
    painter.drawEllipse(QPointF(cx, cy), dot_r, dot_r)
    painter.drawEllipse(QPointF(cx - r * 0.5, cy - r * 0.5), dot_r, dot_r)
    painter.drawEllipse(QPointF(cx + r * 0.5, cy + r * 0.5), dot_r, dot_r)


def _draw_rice(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """bowl 风格：吃白饭"""
    _pen(painter, size, color)
    r = size * 0.34
    path = QPainterPath()
    path.moveTo(cx - r, cy - r * 0.1)
    path.arcTo(QRectF(cx - r, cy - r * 0.6, r * 2, r * 1.2), 180, 180)
    path.lineTo(cx - r, cy - r * 0.1)
    painter.drawPath(path)
    painter.drawLine(QPointF(cx - r * 0.35, cy + r * 0.6), QPointF(cx + r * 0.35, cy + r * 0.6))
    painter.drawLine(QPointF(cx - r * 0.6, cy - r * 0.5), QPointF(cx + r * 0.7, cy - r * 0.1))


def _draw_dance(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """music 风格：宅舞音符"""
    _pen(painter, size, color)
    r = size * 0.32
    painter.drawEllipse(QPointF(cx - r * 0.4, cy + r * 0.4), r * 0.28, r * 0.22)
    painter.drawLine(QPointF(cx - r * 0.15, cy + r * 0.4), QPointF(cx - r * 0.15, cy - r * 0.5))
    painter.drawEllipse(QPointF(cx + r * 0.35, cy + r * 0.2), r * 0.28, r * 0.22)
    painter.drawLine(QPointF(cx + r * 0.6, cy + r * 0.2), QPointF(cx + r * 0.6, cy - r * 0.7))
    painter.drawLine(QPointF(cx - r * 0.15, cy - r * 0.5), QPointF(cx + r * 0.6, cy - r * 0.7))


def _draw_rub(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """cat 风格：摸头摸肚肚"""
    _pen(painter, size, color)
    r = size * 0.32
    painter.drawEllipse(QPointF(cx, cy + r * 0.1), r * 0.85, r * 0.75)
    path_l = QPainterPath()
    path_l.moveTo(cx - r * 0.7, cy - r * 0.2)
    path_l.lineTo(cx - r * 0.8, cy - r * 0.8)
    path_l.lineTo(cx - r * 0.2, cy - r * 0.55)
    painter.drawPath(path_l)
    path_r = QPainterPath()
    path_r.moveTo(cx + r * 0.7, cy - r * 0.2)
    path_r.lineTo(cx + r * 0.8, cy - r * 0.8)
    path_r.lineTo(cx + r * 0.2, cy - r * 0.55)
    painter.drawPath(path_r)


def _draw_back(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """back 风格：返回箭头"""
    _pen(painter, size, color)
    r = size * 0.32
    path = QPainterPath()
    path.arcMoveTo(QRectF(cx - r * 0.5, cy - r * 0.5, r * 1.5, r * 1.2), 90)
    path.arcTo(QRectF(cx - r * 0.5, cy - r * 0.5, r * 1.5, r * 1.2), 90, 180)
    painter.drawPath(path)
    ah = size * 0.15
    painter.drawLine(QPointF(cx - r * 0.5, cy - r * 0.5), QPointF(cx - r * 0.5 - ah, cy - r * 0.5))
    painter.drawLine(QPointF(cx - r * 0.5 - ah, cy - r * 0.5), QPointF(cx - r * 0.5, cy - r * 0.5 - ah))
    painter.drawLine(QPointF(cx - r * 0.5 - ah, cy - r * 0.5), QPointF(cx - r * 0.5, cy - r * 0.5 + ah))


def _draw_switch_target(painter: QPainter, cx: float, cy: float, size: float, color: QColor):
    """refresh-cw 风格：双宠控制切换环形双箭头"""
    _pen(painter, size, color)
    r = size * 0.32
    rect = QRectF(cx - r, cy - r, r * 2, r * 2)
    path1 = QPainterPath()
    path1.arcMoveTo(rect, 30)
    path1.arcTo(rect, 30, 130)
    painter.drawPath(path1)

    path2 = QPainterPath()
    path2.arcMoveTo(rect, 210)
    path2.arcTo(rect, 210, 130)
    painter.drawPath(path2)

    ah = size * 0.13
    # 左上箭头
    p1 = QPointF(cx + r * math.cos(math.radians(160)), cy - r * math.sin(math.radians(160)))
    painter.drawLine(p1, QPointF(p1.x() - ah * 0.2, p1.y() - ah))
    painter.drawLine(p1, QPointF(p1.x() + ah, p1.y() - ah * 0.3))
    # 右下箭头
    p2 = QPointF(cx + r * math.cos(math.radians(-20)), cy - r * math.sin(math.radians(-20)))
    painter.drawLine(p2, QPointF(p2.x() + ah * 0.2, p2.y() + ah))
    painter.drawLine(p2, QPointF(p2.x() - ah, p2.y() + ah * 0.3))


# ——— 公共派发入口 ———

_ICON_MAP = {
    'size':           _draw_size,
    'background':     _draw_background,
    'touch':          _draw_touch,
    'stream':         _draw_stream,
    'settings':       _draw_settings,
    'collapse':       _draw_collapse,
    'panel':          _draw_panel,
    'chat':           _draw_chat,
    'voice':          _draw_voice,
    'toggle_display': _draw_toggle_display,
    'display':        _draw_toggle_display,
    'switch_target':  _draw_switch_target,
    'balance':        _draw_balance,
    'whisper':        _draw_whisper,
    'sub_status':     _draw_star,
    'sub_actions':    _draw_actions,
    'status_balance': _draw_balance,
    'status_weather': _draw_weather,
    'status_todo':    _draw_todo,
    'status_sleep':   _draw_sleep,
    'action_random':  _draw_dice,
    'action_whisper': _draw_whisper,
    'action_rice':    _draw_rice,
    'action_dance':   _draw_dance,
    'action_rub':     _draw_rub,
    'back':           _draw_back,
    'back_to_cat':    _draw_back,
    'back_to_main':   _draw_back,
    'cat_food':       _draw_rice,
    'cat_play':       _draw_dance,
    'cat_funny':      _draw_star,
    'cat_touch':      _draw_rub,
    'cat_daily':      _draw_dice,
    'cat_work':       _draw_actions,
    'cat_sleep':      _draw_sleep,
    'anim_action':    _draw_actions,
}


_EMOJI_FALLBACK = {
    'switch_target':  '🔄',
    'voice':          '🎙️',
    'touch':          '🐱',
    'sub_status':     '🌟',
    'sub_actions':    '🎭',
    'status_balance': '💰',
    'status_weather': '⛅',
    'status_todo':    '📋',
    'status_sleep':   '💤',
    'action_random':  '🎲',
    'action_whisper': '💭',
    'action_rice':    '🍚',
    'action_dance':   '💃',
    'action_rub':     '🐱',
    'back':           '↩️',
}


def draw_icon(painter: QPainter, key: str, cx: float, cy: float,
              size: float, color: QColor):
    """统一入口，根据 key 分派到具体绘制函数。"""
    fn = _ICON_MAP.get(key)
    if fn is not None:
        painter.save()
        fn(painter, cx, cy, size, color)
        painter.restore()
        return

    if key in _EMOJI_FALLBACK:
        em = _EMOJI_FALLBACK[key]
        painter.save()
        font = QFont("Segoe UI Emoji", int(size * 0.52))
        painter.setFont(font)
        painter.setPen(color)
        rect = QRectF(cx - size / 2.0, cy - size / 2.0, size, size)
        painter.drawText(rect, Qt.AlignCenter, em)
        painter.restore()
        return

    # fallback：画一个小圆点
    painter.save()
    _pen(painter, size, color)
    r = size * 0.20
    painter.drawEllipse(QPointF(cx, cy), r, r)
    painter.restore()
