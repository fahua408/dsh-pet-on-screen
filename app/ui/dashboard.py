# -*- coding: utf-8 -*-
"""dashboard.py — 桌宠之家 · 可视化详细操作控制中心（920×600 现代化桌面中枢）。

功能设计：
- 920×600 极简现代化磨砂暗黑工作台（Linear / Fluent 风格）。
- 自定义无边框标题栏：拖拽移动、设备状态徽标、最小化、关闭至托盘。
- 左侧导航栏（5大模块）：
    1. 📊 运行概览（实时画幅、推流数据仪表、快捷互动、Coopanion 状态）
    2. 🎭 桌宠工坊（体型 DPR 倍率滑块、6款内置高清质感背景画廊、自定义壁纸、纯色拾色器）
    3. ⚡ 屏幕固件（待机壁纸更换/恢复出厂、开机动画制作刷入/恢复出厂、动态进度条）
    4. 🩺 硬件诊断（设备 VID/PID、MI_00/MI_01 复合总线状态、分包统计、总线重置）
    5. ⚙️ 偏好设置（Windows 开机自启动、关闭最小化到托盘、悬浮球吸附行为、配置目录快捷打开）
"""
from __future__ import annotations

import io
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import (
    Qt, QTimer, QPoint, QRectF, Signal, QSize
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath,
    QFont, QPixmap, QIcon, QLinearGradient
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QCheckBox, QColorDialog,
    QFileDialog, QFrame, QStackedWidget, QMessageBox,
    QProgressBar, QScrollArea, QGridLayout, QSizePolicy,
    QRadioButton, QButtonGroup
)

from .tokens import (
    SURFACE, SURFACE_HOVER, SURFACE_ACTIVE,
    BORDER, ACCENT, TEXT_PRIMARY, TEXT_MUTED, TEXT_ACCENT,
    DANGER, SCALES, build_qss
)
from .preview import PreviewWidget
from .flash_widget import FlashWidget
try:
    from core.autostart import is_autostart_enabled, set_autostart
except ImportError:
    try:
        from ..core.autostart import is_autostart_enabled, set_autostart
    except ImportError:
        from app.core.autostart import is_autostart_enabled, set_autostart

log = logging.getLogger('tcomas.ui.dashboard')

DASHBOARD_W = 920
DASHBOARD_H = 600

# 预设背景定义
PRESET_BACKGROUNDS = [
    ('dots', '深空点阵', 'bg_1_dots.jpg', '经典微光点阵，极简科技感'),
    ('gradient', '暗夜极光', 'bg_2_gradient.jpg', '深邃暗夜流光，优雅灵动'),
    ('starry', '璀璨星河', 'bg_3_starry.jpg', '微茫星宿散落，宁静空灵'),
    ('underwater', '幽蓝深海', 'bg_4_underwater.jpg', '沉浸深海水下，清爽通透'),
    ('cyber', '赛博碳纤', 'bg_5_cyber.jpg', '矩阵纹理质感，机械硬朗'),
    ('midnight', '午夜深黑', 'bg_6_midnight.jpg', '纯粹纯暗沉浸，突出桌宠'),
]

# 114 款动作分类树
ANIM_CATEGORIES = {
    "待机日常": ["待机呼吸休闲", "悠闲哼歌", "超大伸懒腰", "原地敲击桌面互动", "东张西望"],
    "趣味搞怪": ["吃Token", "大口吃零食", "偷吃零食被抓住", "深度思考碎碎念", "被落叶淹没", "写福字"],
    "玩耍娱乐": ["原地专心玩魔方", "原地蹲下玩玩具汽车", "鲸鱼吐泡泡特效", "优雅女仆舞", "可爱宅舞", "三球抛接", "荡秋千", "下五子棋"],
    "吃货特辑": ["吃白饭", "中秋赏月吃月饼", "吃年糕", "是啊，吃什么", "凭空生花", "动物环绕"],
    "点击回应": ["点击回应-开心跃动", "点击回应-挠痒咯咯笑", "点击回应-害羞惊讶", "点击回应-傲娇生气", "原地跳跃抓碎头顶物品", "开心小跑"],
    "位移行走": ["螃蟹走路", "原地漂浮踏步", "原地左转奔跑", "侧身急躁跑", "被鼠标拖拽悬空反馈"],
    "作息睡眠": ["睡觉-开始", "睡觉-循环", "睡觉-起来", "打瞌睡被惊醒"],
    "工作状态": ["写代码", "工作状态-思考冒泡", "工作状态-忙碌点按", "工作状态-清点归档", "工作状态-原地踱步张望", "工作状态-垂头叹气冒汗"],
    "余额档位": ["余额-金袋叮当", "余额-钱袋满溢", "余额-钱袋如常", "余额-数金皱眉", "余额-分文不剩", "余额-袋空如洗"],
    "碎碎念":   ["碎碎念-擦桌碎碎念", "碎碎念-发呆碎碎念", "碎碎念-对屏碎碎念"],
}

# 27 款 Meme 表情包
MEMES_DIALOG = [
    '吃白饭的大肥鱼', '大的要来啦', '大的药来了', '要不直接骂他', '死掉了',
    '深度睡眠', '大烧货', '先养着吧', '吃饱饱摸肚子', '誓死践行开源精神',
    '电死你', '可爱', 'token给妈妈保管', '假如给我三天多模态', '厉害了我的鲸',
    '哦鲸鲸', '压力一只大肥鱼', '黎曼猜想没证明喵', '除了调情没啥用', '我不更新你们用什么'
]

MEMES_OTHER = [
    '哪来的电脑病毒', '鱼片有资源吗', '大师这个区是什么意思', '就骚了怎么滴吧',
    '完蛋了把黄油删了', '就一碗', 'Ciallo'
]


def _parse_rgba(s: str) -> QColor:
    s = s.strip()
    if s.startswith("rgba"):
        vals = s[5:-1].split(",")
        r, g, b = int(vals[0]), int(vals[1]), int(vals[2])
        a = float(vals[3])
        c = QColor(r, g, b)
        c.setAlpha(int(a * 255))
        return c
    return QColor(s)


class _DashboardTitleBar(QWidget):
    """控制中心顶部自定义标题栏，支持原生 Windows 丝滑无死锁拖拽。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            win = self.window()
            if win:
                wh = win.windowHandle()
                if wh and hasattr(wh, 'startSystemMove') and wh.startSystemMove():
                    event.accept()
                    return
                # 兜底手动拖拽标记
                win._dragging_header = True
                win._drag_offset = event.globalPosition().toPoint() - win.pos()
                event.accept()
                return
        super().mousePressEvent(event)


class DashboardWindow(QWidget):
    """可视化详细操作控制中心主窗口。"""

    scale_changed = Signal(float)
    transform_changed = Signal(float, int, int)
    bubble_scale_changed = Signal(float)
    background_changed = Signal(str, object)
    pet_action = Signal(str)
    anim_requested = Signal(str)
    meme_requested = Signal(str)
    stream_toggled = Signal(bool)
    hide_pet_toggled = Signal(bool)
    ball_snap_toggled = Signal(bool)
    ball_peek_toggled = Signal(bool)
    chat_requested = Signal()
    reload_requested = Signal()

    # 多桌宠投放调度信号
    cast_mode_changed = Signal(str)
    selective_cast_changed = Signal(bool, bool)
    dual_layout_changed = Signal(str)
    control_target_changed = Signal(str)

    # Coopanion 专属交互与微调信号
    coopanion_touch = Signal()
    coopanion_voice = Signal()
    coopanion_chat = Signal()
    coopanion_scale_changed = Signal(float)

    def __init__(self, settings=None, renderer=None, pusher=None, flash_bridge=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.renderer = renderer
        self.pusher = pusher
        self.flash_bridge = flash_bridge

        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.Window |
            Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(DASHBOARD_W, DASHBOARD_H)

        self._drag_offset = QPoint()
        self._dragging_header = False

        self._status = dict(fps=0.0, kb=0.0, pkt=0, ok=False, msg="初始化中")
        self._total_frames = 0
        self._start_time = time.monotonic()

        self._build_ui()

        # 状态定时刷新
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._on_timer_tick)
        self._timer.start()

        # 初始同步
        self._sync_settings()

    # ================================================================
    # 窗口外观绘制（圆角与磨砂背景）
    # ================================================================

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(rect, 14.0, 14.0)

        # 填充深色底板
        painter.fillPath(path, QBrush(QColor(18, 20, 25, 248)))

        # 边缘微光描边
        pen = QPen(QColor(255, 255, 255, 22), 1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 14.0, 14.0)
        painter.end()

    # ================================================================
    # UI 构建
    # ================================================================

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        # 1. 顶部标题栏
        root.addWidget(self._make_titlebar())

        # 2. 下方内容主体（左侧导航 + 右侧堆叠页）
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # 左侧导航栏
        body.addWidget(self._make_sidebar())

        # 分割竖线
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("background: rgba(255,255,255,0.06); max-width: 1px;")
        body.addWidget(sep)

        # 右侧堆叠内容区
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")

        self._stack.addWidget(self._make_page_overview())     # 0: 运行概览
        self._stack.addWidget(self._make_page_cast())         # 1: 桌宠投放 (NEW!)
        self._stack.addWidget(self._make_page_pet())          # 2: 桌宠工坊
        self._stack.addWidget(self._make_page_firmware())     # 3: 屏幕固件
        self._stack.addWidget(self._make_page_diagnostics())  # 4: 硬件诊断
        self._stack.addWidget(self._make_page_settings())     # 5: 偏好设置

        body.addWidget(self._stack)
        root.addLayout(body)

    # ---------------------------------------------------------------- 标题栏
    def _make_titlebar(self) -> QWidget:
        tb = _DashboardTitleBar(self)
        tb.setFixedHeight(48)
        tb.setStyleSheet("""
            QWidget {
                background: rgba(24, 27, 34, 0.95);
                border-top-left-radius: 14px;
                border-top-right-radius: 14px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.06);
            }
        """)

        layout = QHBoxLayout(tb)
        layout.setContentsMargins(18, 0, 14, 0)
        layout.setSpacing(12)

        # 品牌图标与标题
        icon_lbl = QLabel()
        ico_file = Path(__file__).resolve().parent.parent / 'assets' / 'app_icon.ico'
        if ico_file.is_file():
            icon_lbl.setPixmap(QPixmap(str(ico_file)).scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            icon_lbl.setText("🐟")
            icon_lbl.setStyleSheet("font-size: 18px;")
        layout.addWidget(icon_lbl)

        title = QLabel("桌宠之家 · 控制中心")
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {TEXT_PRIMARY};")
        layout.addWidget(title)

        tag = QLabel("TCOMAS LG700 独立版")
        tag.setStyleSheet("""
            background: rgba(111, 227, 255, 0.12);
            color: #6FE3FF;
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 6px;
            border: 1px solid rgba(111, 227, 255, 0.30);
        """)
        layout.addWidget(tag)

        layout.addStretch()

        # 顶部硬件连接状态指示徽标
        self._status_badge = QLabel("● 水冷屏检测中…")
        self._status_badge.setStyleSheet("""
            color: #8C95A3;
            font-size: 12px;
            padding: 4px 12px;
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.05);
        """)
        layout.addWidget(self._status_badge)

        # 最小化按钮
        btn_min = QPushButton("—")
        btn_min.setFixedSize(30, 30)
        btn_min.setToolTip("最小化")
        btn_min.setStyleSheet("""
            QPushButton {
                background: transparent; color: #8C95A3; font-size: 13px; border-radius: 6px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.08); color: #FFF; }
        """)
        btn_min.clicked.connect(self.showMinimized)
        layout.addWidget(btn_min)

        # 关闭按钮（关闭到托盘）
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(30, 30)
        btn_close.setToolTip("隐藏到系统托盘（保持后台推流）")
        btn_close.setStyleSheet("""
            QPushButton {
                background: transparent; color: #8C95A3; font-size: 13px; border-radius: 6px;
            }
            QPushButton:hover { background: rgba(255,91,91,0.25); color: #FF5B5B; }
        """)
        btn_close.clicked.connect(self.hide)
        layout.addWidget(btn_close)

        return tb

    # ---------------------------------------------------------------- 侧边导航栏
    def _make_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setFixedWidth(180)
        sidebar.setStyleSheet("background: rgba(18, 20, 25, 0.98);")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 16, 10, 16)
        layout.setSpacing(6)

        self._nav_buttons = []
        nav_items = [
            ("📊  运行概览", 0),
            ("🚀  桌宠投放", 1),
            ("🎭  桌宠工坊", 2),
            ("⚡  屏幕固件", 3),
            ("🩺  硬件诊断", 4),
            ("⚙️  偏好设置", 5),
        ]

        for text, idx in nav_items:
            btn = QPushButton(text)
            btn.setFixedHeight(40)
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {TEXT_MUTED};
                    font-size: 13px;
                    font-weight: 500;
                    text-align: left;
                    padding-left: 14px;
                    border-radius: 8px;
                    border: 1px solid transparent;
                }}
                QPushButton:hover {{
                    background: rgba(255, 255, 255, 0.05);
                    color: {TEXT_PRIMARY};
                }}
                QPushButton:checked {{
                    background: rgba(111, 227, 255, 0.12);
                    color: {ACCENT};
                    font-weight: bold;
                    border: 1px solid rgba(111, 227, 255, 0.35);
                }}
            """)
            btn.clicked.connect(lambda checked, i=idx: self._on_nav_selected(i))
            layout.addWidget(btn)
            self._nav_buttons.append(btn)

        self._nav_buttons[0].setChecked(True)
        layout.addStretch()

        # 底部版本标签
        ver_lbl = QLabel("v1.0.0 独立纯净版\n免原生后台与HWiNFO")
        ver_lbl.setStyleSheet(f"color: rgba(140,149,163,0.50); font-size: 11px; padding: 8px 6px;")
        layout.addWidget(ver_lbl)

        return sidebar

    def _on_nav_selected(self, index: int):
        if self._stack.currentIndex() == index:
            return
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)
        self._stack.setCurrentIndex(index)
        # 若切回运行概览页，立即推送最新一帧以保证无卡顿秒显
        if index == 0 and hasattr(self, '_last_jpeg_bytes') and self._last_jpeg_bytes:
            self._overview_preview.update_frame(self._last_jpeg_bytes)

    # ---------------------------------------------------------------- 页 0：运行概览
    def _make_page_overview(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # 顶部主体：左侧 400×300 晶莹大画幅实时监视 + 右侧管理仪表
        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        # 实时大预览卡片 (蓝圈部分按要求大幅扩大至 400×300，紧凑包裹杜绝红色浪费空隙)
        preview_card = QFrame()
        preview_card.setStyleSheet(f"""
            QFrame {{
                background: rgba(26, 29, 36, 0.90);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }}
        """)
        pv_layout = QVBoxLayout(preview_card)
        pv_layout.setContentsMargins(12, 10, 12, 12)
        pv_layout.setSpacing(8)

        pv_title = QLabel("实时水冷屏监视画幅（400×300 等比放大沉浸展示）")
        pv_title.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; font-weight: bold;")
        pv_layout.addWidget(pv_title)

        # 大尺寸预览框（400×300 晶莹清晰大屏）
        self._overview_preview = PreviewWidget()
        self._overview_preview.setFixedSize(400, 300)
        pv_layout.addWidget(self._overview_preview, 0, Qt.AlignCenter)

        top_row.addWidget(preview_card, 0)

        # 右侧推流控制与统计仪表卡片列
        right_col = QVBoxLayout()
        right_col.setSpacing(12)

        # 推流显示卡片
        ctrl_card = QFrame()
        ctrl_card.setStyleSheet("""
            QFrame {
                background: rgba(26, 29, 36, 0.90);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }
        """)
        ctrl_layout = QVBoxLayout(ctrl_card)
        ctrl_layout.setContentsMargins(16, 14, 16, 14)
        ctrl_layout.setSpacing(10)

        ctrl_title = QLabel("推流与显示管理")
        ctrl_title.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; font-weight: bold;")
        ctrl_layout.addWidget(ctrl_title)

        # 桌宠投屏显示位置切换开关（开: 水冷屏运作/主桌面隐藏；关: 主桌面运作/小屏待机）
        self._chk_display_mode = QCheckBox("🖥️ 投屏至水冷屏运作（主桌面桌宠自动隐藏）")
        self._chk_display_mode.setChecked(True)
        self._chk_display_mode.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: bold;")
        self._chk_display_mode.toggled.connect(self._on_toggle_display_mode)
        ctrl_layout.addWidget(self._chk_display_mode)

        lbl_mode_hint = QLabel("💡 开启：桌宠在水冷屏运作并隐藏主桌面原版；关闭：桌宠在主桌面运作，水冷屏待机。")
        lbl_mode_hint.setWordWrap(True)
        lbl_mode_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        ctrl_layout.addWidget(lbl_mode_hint)

        self._btn_reload = QPushButton("↻ 立即刷新推流画面")
        self._btn_reload.setFixedHeight(32)
        self._btn_reload.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.14);
                color: #FFFFFF;
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover { background: rgba(255, 255, 255, 0.16); }
        """)
        self._btn_reload.clicked.connect(self._on_reload_page)
        ctrl_layout.addWidget(self._btn_reload)

        right_col.addWidget(ctrl_card)

        # 数据仪表卡片
        stats_card = QFrame()
        stats_card.setStyleSheet("""
            QFrame {
                background: rgba(26, 29, 36, 0.90);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }
        """)
        stats_layout = QGridLayout(stats_card)
        stats_layout.setContentsMargins(16, 14, 16, 14)
        stats_layout.setHorizontalSpacing(16)
        stats_layout.setVerticalSpacing(8)

        self._lbl_fps_val = QLabel("0.0 FPS")
        self._lbl_fps_val.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {ACCENT};")
        self._lbl_fps_tip = QLabel("实时推流帧率")
        self._lbl_fps_tip.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")

        self._lbl_bw_val = QLabel("0.0 KB/s")
        self._lbl_bw_val.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {TEXT_PRIMARY};")
        self._lbl_bw_tip = QLabel("传输带宽")
        self._lbl_bw_tip.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")

        self._lbl_pkt_val = QLabel("0 包")
        self._lbl_pkt_val.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {TEXT_PRIMARY};")
        self._lbl_pkt_tip = QLabel("累计已发数据包")
        self._lbl_pkt_tip.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")

        self._lbl_status_val = QLabel("等待数据")
        self._lbl_status_val.setStyleSheet(f"font-size: 14px; font-weight: bold; color: #8C95A3;")
        self._lbl_status_tip = QLabel("管道传输状态")
        self._lbl_status_tip.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")

        stats_layout.addWidget(self._lbl_fps_val, 0, 0)
        stats_layout.addWidget(self._lbl_fps_tip, 1, 0)
        stats_layout.addWidget(self._lbl_bw_val, 0, 1)
        stats_layout.addWidget(self._lbl_bw_tip, 1, 1)
        stats_layout.addWidget(self._lbl_pkt_val, 2, 0)
        stats_layout.addWidget(self._lbl_pkt_tip, 3, 0)
        stats_layout.addWidget(self._lbl_status_val, 2, 1)
        stats_layout.addWidget(self._lbl_status_tip, 3, 1)

        right_col.addWidget(stats_card)
        top_row.addLayout(right_col, 1)
        layout.addLayout(top_row)

        # 底部状态栏
        bottom_box = QFrame()
        bottom_box.setStyleSheet("""
            background: rgba(22, 24, 30, 0.80);
            border-radius: 8px;
            padding: 6px 12px;
            border: 1px solid rgba(255,255,255,0.05);
        """)
        b_lay = QHBoxLayout(bottom_box)
        b_lay.setContentsMargins(10, 4, 10, 4)
        self._lbl_coopanion_info = QLabel("大肥鱼钛坦屏双桌宠控制台 · DirectIO 极速硬件推流 · Playwright 独立渲染")
        self._lbl_coopanion_info.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        b_lay.addWidget(self._lbl_coopanion_info)
        b_lay.addStretch()
        layout.addWidget(bottom_box)

        layout.addStretch()
        return page

    # ---------------------------------------------------------------- 页 1：桌宠投放 (NEW!)
    def _make_page_cast(self) -> QWidget:
        page = QWidget()
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # 1. 顶部标题
        header = QVBoxLayout()
        header.setSpacing(4)
        t_lbl = QLabel("🚀  桌宠投放管理中心")
        t_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 18px; font-weight: bold;")
        s_lbl = QLabel("支持双桌宠独立选择、组合混排与一键热切换，无缝投射至 TCOMAS 640×480 水冷屏")
        s_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        header.addWidget(t_lbl)
        header.addWidget(s_lbl)
        layout.addLayout(header)

        # 2. 核心模式快捷切换卡片组 (3选1)
        mode_box = QFrame()
        mode_box.setStyleSheet(f"""
            QFrame {{
                background: rgba(26, 29, 36, 0.90);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }}
        """)
        mb_layout = QVBoxLayout(mode_box)
        mb_layout.setContentsMargins(18, 16, 18, 16)
        mb_layout.setSpacing(12)

        mb_title = QLabel("一键投放模式切换")
        mb_title.setStyleSheet(f"color: {ACCENT}; font-size: 13px; font-weight: bold;")
        mb_layout.addWidget(mb_title)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)

        self._btn_mode_coop = QPushButton("🐟 仅投放大肥鱼\n(Coopanion 专属)")
        self._btn_mode_dsh = QPushButton("👧 仅投放蓝毛女仆\n(DeepSeek dsh-pet 专属)")
        self._btn_mode_dual = QPushButton("🌟 双桌宠同台投放\n(一起投放 · 合体共舞)")

        for btn in (self._btn_mode_coop, self._btn_mode_dsh, self._btn_mode_dual):
            btn.setFixedHeight(56)
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.04);
                    color: {TEXT_PRIMARY};
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 10px;
                    font-size: 13px;
                    font-weight: 500;
                    padding: 6px 12px;
                }}
                QPushButton:hover {{
                    background: rgba(111, 227, 255, 0.08);
                    border: 1px solid rgba(111, 227, 255, 0.35);
                }}
                QPushButton:checked {{
                    background: rgba(111, 227, 255, 0.18);
                    color: {ACCENT};
                    border: 2px solid {ACCENT};
                    font-weight: bold;
                }}
            """)

        self._btn_mode_coop.clicked.connect(lambda: self._set_cast_mode('coopanion'))
        self._btn_mode_dsh.clicked.connect(lambda: self._set_cast_mode('dsh'))
        self._btn_mode_dual.clicked.connect(lambda: self._set_cast_mode('dual'))

        mode_row.addWidget(self._btn_mode_coop)
        mode_row.addWidget(self._btn_mode_dsh)
        mode_row.addWidget(self._btn_mode_dual)
        mb_layout.addLayout(mode_row)
        layout.addWidget(mode_box)

        # 3. 选择性投放独立开关区 (卡片A & 卡片B)
        sel_box = QFrame()
        sel_box.setStyleSheet(f"""
            QFrame {{
                background: rgba(26, 29, 36, 0.90);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }}
        """)
        sb_layout = QVBoxLayout(sel_box)
        sb_layout.setContentsMargins(18, 16, 18, 16)
        sb_layout.setSpacing(12)

        sb_title = QLabel("选择性投放独立控制 (双宠自由勾选组合)")
        sb_title.setStyleSheet(f"color: {ACCENT}; font-size: 13px; font-weight: bold;")
        sb_layout.addWidget(sb_title)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)

        # 卡片 A: 大肥鱼
        card_coop = QFrame()
        card_coop.setStyleSheet("background: rgba(18, 22, 30, 0.7); border: 1px solid rgba(111, 227, 255, 0.2); border-radius: 10px;")
        cc_layout = QVBoxLayout(card_coop)
        cc_layout.setContentsMargins(14, 12, 14, 12)
        cc_layout.setSpacing(8)

        self._chk_cast_coop = QCheckBox("🐟 投放大肥鱼 (Coopanion)")
        self._chk_cast_coop.setChecked(True)
        self._chk_cast_coop.setStyleSheet(f"color: {ACCENT}; font-size: 13px; font-weight: bold;")
        self._chk_cast_coop.toggled.connect(self._on_selective_toggle)
        cc_layout.addWidget(self._chk_cast_coop)

        self._lbl_coop_status = QLabel("● 服务探测: 127.0.0.1:7797")
        self._lbl_coop_status.setStyleSheet("color: #10b981; font-size: 11px;")
        cc_layout.addWidget(self._lbl_coop_status)

        self._btn_launch_coop = QPushButton("🚀 一键启动 Coopanion 客户端")
        self._btn_launch_coop.setFixedHeight(28)
        self._btn_launch_coop.setStyleSheet("background: rgba(255,255,255,0.06); color: #cbd5e1; border-radius: 6px; font-size: 11px;")
        self._btn_launch_coop.clicked.connect(self._on_launch_coopanion)
        cc_layout.addWidget(self._btn_launch_coop)

        cards_row.addWidget(card_coop)

        # 卡片 B: 蓝毛女仆
        card_dsh = QFrame()
        card_dsh.setStyleSheet("background: rgba(18, 22, 30, 0.7); border: 1px solid rgba(59, 130, 246, 0.2); border-radius: 10px;")
        cd_layout = QVBoxLayout(card_dsh)
        cd_layout.setContentsMargins(14, 12, 14, 12)
        cd_layout.setSpacing(8)

        self._chk_cast_dsh = QCheckBox("👧 投放蓝毛女仆 (DeepSeek dsh-pet)")
        self._chk_cast_dsh.setChecked(True)
        self._chk_cast_dsh.setStyleSheet("color: #60a5fa; font-size: 13px; font-weight: bold;")
        self._chk_cast_dsh.toggled.connect(self._on_selective_toggle)
        cd_layout.addWidget(self._chk_cast_dsh)

        self._lbl_dsh_status = QLabel("● 状态总线: 动态端口就绪")
        self._lbl_dsh_status.setStyleSheet("color: #10b981; font-size: 11px;")
        cd_layout.addWidget(self._lbl_dsh_status)

        self._btn_launch_dsh = QPushButton("🚀 一键唤醒 DeepSeek Harness")
        self._btn_launch_dsh.setFixedHeight(28)
        self._btn_launch_dsh.setStyleSheet("background: rgba(255,255,255,0.06); color: #cbd5e1; border-radius: 6px; font-size: 11px;")
        self._btn_launch_dsh.clicked.connect(self._on_launch_dsh)
        cd_layout.addWidget(self._btn_launch_dsh)

        cards_row.addWidget(card_dsh)
        sb_layout.addLayout(cards_row)
        layout.addWidget(sel_box)

        # 4. 双宠同台画面布局
        self._dual_layout_box = QFrame()
        self._dual_layout_box.setStyleSheet(f"""
            QFrame {{
                background: rgba(26, 29, 36, 0.90);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }}
        """)
        dl_layout = QVBoxLayout(self._dual_layout_box)
        dl_layout.setContentsMargins(18, 16, 18, 16)
        dl_layout.setSpacing(12)

        dl_title = QLabel("双宠同台屏幕画面排布 (Dual Layout)")
        dl_title.setStyleSheet(f"color: {ACCENT}; font-size: 13px; font-weight: bold;")
        dl_layout.addWidget(dl_title)

        layout_row = QHBoxLayout()
        layout_row.setSpacing(8)

        self._btn_layout_side = QPushButton("左右并排\n50% : 50%")
        self._btn_layout_coop = QPushButton("大肥鱼主位\n65% : 35%")
        self._btn_layout_dsh  = QPushButton("蓝毛女仆主位\n35% : 65%")
        self._btn_layout_over = QPushButton("同台叠层漫游\nOverlay")

        for b in (self._btn_layout_side, self._btn_layout_coop, self._btn_layout_dsh, self._btn_layout_over):
            b.setFixedHeight(48)
            b.setCheckable(True)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.04);
                    color: {TEXT_PRIMARY};
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 8px;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background: rgba(111, 227, 255, 0.08);
                }}
                QPushButton:checked {{
                    background: rgba(111, 227, 255, 0.16);
                    color: {ACCENT};
                    border: 1px solid {ACCENT};
                    font-weight: bold;
                }}
            """)

        self._btn_layout_side.clicked.connect(lambda: self._set_dual_layout('side_by_side'))
        self._btn_layout_coop.clicked.connect(lambda: self._set_dual_layout('coopanion_main'))
        self._btn_layout_dsh.clicked.connect(lambda: self._set_dual_layout('dsh_main'))
        self._btn_layout_over.clicked.connect(lambda: self._set_dual_layout('overlay'))

        layout_row.addWidget(self._btn_layout_side)
        layout_row.addWidget(self._btn_layout_coop)
        layout_row.addWidget(self._btn_layout_dsh)
        layout_row.addWidget(self._btn_layout_over)
        dl_layout.addLayout(layout_row)
        layout.addWidget(self._dual_layout_box)

        # 5. 双宠模式悬浮球当前控制目标
        self._target_box = QFrame()
        self._target_box.setStyleSheet(f"""
            QFrame {{
                background: rgba(26, 29, 36, 0.90);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }}
        """)
        tb_layout = QVBoxLayout(self._target_box)
        tb_layout.setContentsMargins(18, 16, 18, 16)
        tb_layout.setSpacing(10)

        tb_title = QLabel("悬浮球当前交互控制靶心 (与悬浮球【🔄 控制切换】按键实时同步)")
        tb_title.setStyleSheet(f"color: {ACCENT}; font-size: 13px; font-weight: bold;")
        tb_layout.addWidget(tb_title)

        target_row = QHBoxLayout()
        target_row.setSpacing(16)
        self._radio_target_coop = QRadioButton("🐟 交互控制大肥鱼 (摸头 / 语音 / 对话)")
        self._radio_target_dsh  = QRadioButton("👧 交互控制蓝毛小女仆 (摸头 / 114动作转盘 / 状态)")
        self._radio_target_coop.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        self._radio_target_dsh.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")

        self._radio_target_coop.toggled.connect(lambda c: c and self._set_control_target('coopanion'))
        self._radio_target_dsh.toggled.connect(lambda c: c and self._set_control_target('dsh'))

        target_row.addWidget(self._radio_target_coop)
        target_row.addWidget(self._radio_target_dsh)
        tb_layout.addLayout(target_row)
        layout.addWidget(self._target_box)

        layout.addStretch()

        scroll.setWidget(content)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(scroll)

        self._sync_cast_ui_state()
        return page

    def _set_cast_mode(self, mode: str):
        if not self.settings:
            return
        self.settings.update(cast_mode=mode)
        if mode == 'coopanion':
            self.settings.update(cast_coopanion=True, cast_dsh=False)
        elif mode == 'dsh':
            self.settings.update(cast_coopanion=False, cast_dsh=True)
        elif mode == 'dual':
            self.settings.update(cast_coopanion=True, cast_dsh=True)
        self._sync_cast_ui_state()
        self.cast_mode_changed.emit(mode)

    def _on_selective_toggle(self):
        c_coop = self._chk_cast_coop.isChecked()
        c_dsh = self._chk_cast_dsh.isChecked()
        if not self.settings:
            return
        self.settings.update(cast_coopanion=c_coop, cast_dsh=c_dsh)
        if c_coop and c_dsh:
            mode = 'dual'
        elif c_coop:
            mode = 'coopanion'
        elif c_dsh:
            mode = 'dsh'
        else:
            mode = 'standby'
        self.settings.update(cast_mode=mode)
        self._sync_cast_ui_state()
        self.selective_cast_changed.emit(c_coop, c_dsh)
        self.cast_mode_changed.emit(mode)

    def _set_dual_layout(self, layout: str):
        if self.settings:
            self.settings.update(dual_layout=layout)
        self._sync_cast_ui_state()
        self.dual_layout_changed.emit(layout)

    def _set_control_target(self, target: str):
        if self.settings:
            self.settings.update(control_target=target)
        self.control_target_changed.emit(target)

    def update_control_target_from_ball(self, target: str):
        if hasattr(self, '_radio_target_coop') and hasattr(self, '_radio_target_dsh'):
            self._radio_target_coop.blockSignals(True)
            self._radio_target_dsh.blockSignals(True)
            self._radio_target_coop.setChecked(target == 'coopanion')
            self._radio_target_dsh.setChecked(target == 'dsh')
            self._radio_target_coop.blockSignals(False)
            self._radio_target_dsh.blockSignals(False)

    def _sync_cast_ui_state(self):
        if not self.settings:
            return
        s = self.settings.snapshot()
        mode = s.get('cast_mode', 'dual')
        c_coop = s.get('cast_coopanion', True)
        c_dsh = s.get('cast_dsh', True)
        d_layout = s.get('dual_layout', 'side_by_side')
        c_target = s.get('control_target', 'coopanion')

        if hasattr(self, '_btn_mode_coop'):
            self._btn_mode_coop.setChecked(mode == 'coopanion')
            self._btn_mode_dsh.setChecked(mode == 'dsh')
            self._btn_mode_dual.setChecked(mode == 'dual')

        if hasattr(self, '_chk_cast_coop'):
            self._chk_cast_coop.blockSignals(True)
            self._chk_cast_dsh.blockSignals(True)
            self._chk_cast_coop.setChecked(c_coop)
            self._chk_cast_dsh.setChecked(c_dsh)
            self._chk_cast_coop.blockSignals(False)
            self._chk_cast_dsh.blockSignals(False)

        if hasattr(self, '_dual_layout_box'):
            is_dual = (mode == 'dual')
            self._dual_layout_box.setVisible(is_dual)
            self._target_box.setVisible(is_dual)
            self._btn_layout_side.setChecked(d_layout == 'side_by_side')
            self._btn_layout_coop.setChecked(d_layout == 'coopanion_main')
            self._btn_layout_dsh.setChecked(d_layout == 'dsh_main')
            self._btn_layout_over.setChecked(d_layout == 'overlay')

        if hasattr(self, '_radio_target_coop'):
            self._radio_target_coop.blockSignals(True)
            self._radio_target_dsh.blockSignals(True)
            self._radio_target_coop.setChecked(c_target == 'coopanion')
            self._radio_target_dsh.setChecked(c_target == 'dsh')
            self._radio_target_coop.blockSignals(False)
            self._radio_target_dsh.blockSignals(False)

    def _on_launch_coopanion(self):
        target_path = Path(r"D:\Program Files\Coopanion\Coopanion.exe")
        if target_path.exists():
            subprocess.Popen([str(target_path)])
        else:
            QMessageBox.information(self, "提示", f"未在 {target_path} 找到 Coopanion 程序，请确认安装。")

    def _on_launch_dsh(self):
        try:
            from core.win32_guard import trigger_dsh_chat
            trigger_dsh_chat()
        except Exception:
            pass

    # ---------------------------------------------------------------- 页 2：桌宠工坊（双桌宠二级独立专属工坊）
    def _make_page_pet(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(20, 16, 20, 16)
        page_layout.setSpacing(12)

        # 顶部二级工坊分段切换条 (Segmented Tab Bar)
        tab_row = QHBoxLayout()
        tab_row.setSpacing(10)

        self._btn_subtab_coop = QPushButton("🐟  大肥鱼专属工坊 (Coopanion 互动 · 视口DPR · 舞台壁纸)")
        self._btn_subtab_dsh  = QPushButton("👧  蓝毛女仆专属工坊 (DeepSeek 互动 · 114动作 · 27Meme · 微调)")

        for btn in (self._btn_subtab_coop, self._btn_subtab_dsh):
            btn.setFixedHeight(38)
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.05);
                    color: {TEXT_MUTED};
                    border: 1px solid rgba(255, 255, 255, 0.10);
                    border-radius: 8px;
                    font-size: 13px;
                    font-weight: 500;
                    padding: 0 16px;
                }}
                QPushButton:hover {{
                    background: rgba(111, 227, 255, 0.08);
                    color: {TEXT_PRIMARY};
                }}
                QPushButton:checked {{
                    background: rgba(111, 227, 255, 0.18);
                    color: {ACCENT};
                    border: 1px solid {ACCENT};
                    font-weight: bold;
                }}
            """)

        self._btn_subtab_coop.clicked.connect(lambda: self._switch_pet_subtab(0))
        self._btn_subtab_dsh.clicked.connect(lambda: self._switch_pet_subtab(1))

        tab_row.addWidget(self._btn_subtab_coop, 1)
        tab_row.addWidget(self._btn_subtab_dsh, 1)
        page_layout.addLayout(tab_row)

        # 二级堆叠页面
        self._pet_substack = QStackedWidget()
        self._pet_substack.setStyleSheet("background: transparent;")

        self._pet_substack.addWidget(self._make_subpage_coopanion())
        self._pet_substack.addWidget(self._make_subpage_dsh())

        page_layout.addWidget(self._pet_substack, 1)

        # 默认选中当前控制目标或大肥鱼
        default_target = getattr(self.settings, 'control_target', 'coopanion') if self.settings else 'coopanion'
        if default_target == 'dsh':
            self._switch_pet_subtab(1)
        else:
            self._switch_pet_subtab(0)

        return page

    def _switch_pet_subtab(self, idx: int):
        self._btn_subtab_coop.setChecked(idx == 0)
        self._btn_subtab_dsh.setChecked(idx == 1)
        self._pet_substack.setCurrentIndex(idx)

    # ---------------- 二级子页 A：大肥鱼专属工坊 (Coopanion)
    def _make_subpage_coopanion(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 8, 4, 16)
        layout.setSpacing(14)

        # 1. 🐟 大肥鱼专属交互中心
        act_card = QFrame()
        act_card.setStyleSheet("""
            QFrame {
                background: rgba(26, 29, 36, 0.90);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }
        """)
        ac_layout = QVBoxLayout(act_card)
        ac_layout.setContentsMargins(18, 14, 18, 14)
        ac_layout.setSpacing(10)

        ac_title = QLabel("🐟 大肥鱼专属交互与控制中心")
        ac_title.setStyleSheet(f"color: {ACCENT}; font-size: 13px; font-weight: bold;")
        ac_layout.addWidget(ac_title)

        ac_row = QHBoxLayout()
        ac_row.setSpacing(10)

        btn_coop_touch = QPushButton("👋 抚摸大肥鱼 (摸头)")
        btn_coop_chat  = QPushButton("💬 对话输入")
        btn_coop_voice = QPushButton("🎙️ 语音对话 (Alt×2)")
        btn_coop_wake  = QPushButton("🚀 启动/唤醒 Coopanion")

        for b in (btn_coop_touch, btn_coop_chat, btn_coop_voice, btn_coop_wake):
            b.setFixedHeight(34)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(111, 227, 255, 0.12);
                    border: 1px solid rgba(111, 227, 255, 0.35);
                    color: {TEXT_PRIMARY};
                    border-radius: 8px;
                    font-size: 12px;
                    font-weight: bold;
                    padding: 0 12px;
                }}
                QPushButton:hover {{
                    background: rgba(111, 227, 255, 0.25);
                    color: {ACCENT};
                }}
            """)
            ac_row.addWidget(b)

        btn_coop_touch.clicked.connect(self.coopanion_touch.emit)
        btn_coop_chat.clicked.connect(lambda: (self._set_control_target('coopanion'), self.chat_requested.emit()))
        btn_coop_voice.clicked.connect(self.coopanion_voice.emit)
        btn_coop_wake.clicked.connect(self._on_launch_coopanion)

        ac_layout.addLayout(ac_row)
        layout.addWidget(act_card)

        # 2. 📐 水冷屏大肥鱼体型微调 (DPR 视口无损缩放)
        scale_card = QFrame()
        scale_card.setStyleSheet("""
            QFrame {
                background: rgba(26, 29, 36, 0.90);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }
        """)
        s_layout = QVBoxLayout(scale_card)
        s_layout.setContentsMargins(18, 14, 18, 14)
        s_layout.setSpacing(8)

        s_header = QHBoxLayout()
        s_title = QLabel("📐 大肥鱼水冷屏体型比例 (DPR 视口无损缩放)")
        s_title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: bold;")
        s_header.addWidget(s_title)
        s_header.addStretch()

        init_scale = getattr(self.settings, 'coopanion_scale', 1.6) if self.settings else 1.6
        init_tag = f"{init_scale}× (默认推荐)" if init_scale == 1.6 else f"{init_scale}×"
        self._lbl_coop_scale_val = QLabel(init_tag)
        self._lbl_coop_scale_val.setStyleSheet(f"color: {ACCENT}; font-size: 13px; font-weight: bold;")
        s_header.addWidget(self._lbl_coop_scale_val)
        s_layout.addLayout(s_header)

        slider_row = QHBoxLayout()
        slider_row.setSpacing(12)

        self._slider_coop_scale = QSlider(Qt.Horizontal)
        self._slider_coop_scale.setRange(0, len(SCALES) - 1)
        try:
            cur_idx = SCALES.index(init_scale)
        except ValueError:
            cur_idx = 2
        self._slider_coop_scale.setValue(cur_idx)
        self._slider_coop_scale.valueChanged.connect(self._on_coop_scale_slider_changed)
        slider_row.addWidget(self._slider_coop_scale, 1)

        btn_reset_coop_scale = QPushButton("↺ 复位 1.6×")
        btn_reset_coop_scale.setFixedHeight(24)
        btn_reset_coop_scale.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
                color: #CBD5E1;
                border-radius: 6px;
                font-size: 11px;
                padding: 0 8px;
            }
            QPushButton:hover { background: rgba(255, 255, 255, 0.16); color: #FFF; }
        """)
        btn_reset_coop_scale.clicked.connect(self._on_reset_coop_scale)
        slider_row.addWidget(btn_reset_coop_scale)
        s_layout.addLayout(slider_row)

        s_desc = QLabel("💡 核心算法：采用「缩小逻辑视口 + 提高设备像素比 (DPR)」渲染架构，既让大肥鱼高清饱满，又确保游动完全处于 640×480 物理屏幕之内。")
        s_desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        s_layout.addWidget(s_desc)
        layout.addWidget(scale_card)

        # 3. 🖼️ 舞台背景质感画廊
        layout.addWidget(self._make_background_card())

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def _on_coop_scale_slider_changed(self, idx: int):
        if 0 <= idx < len(SCALES):
            val = SCALES[idx]
            tag = f"{val}× (默认推荐)" if val == 1.6 else f"{val}×"
            self._lbl_coop_scale_val.setText(tag)
            if self.settings:
                self.settings.update(coopanion_scale=val)
            self.coopanion_scale_changed.emit(val)

    def _on_reset_coop_scale(self):
        default_idx = SCALES.index(1.6) if 1.6 in SCALES else 2
        self._slider_coop_scale.setValue(default_idx)

    # ---------------- 二级子页 B：蓝毛女仆专属工坊 (DeepSeek dsh-pet)
    def _make_subpage_dsh(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 8, 4, 16)
        layout.setSpacing(14)

        # 1. 🌟 蓝毛女仆专属生活状态与交互
        life_card = QFrame()
        life_card.setStyleSheet("""
            QFrame {
                background: rgba(26, 29, 36, 0.90);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }
        """)
        life_layout = QVBoxLayout(life_card)
        life_layout.setContentsMargins(18, 14, 18, 14)
        life_layout.setSpacing(10)

        life_title = QLabel("👧 蓝毛女仆生活状态与快捷交互")
        life_title.setStyleSheet(f"color: #60a5fa; font-size: 13px; font-weight: bold;")
        life_layout.addWidget(life_title)

        life_btn_row = QHBoxLayout()
        life_btn_row.setSpacing(8)

        btn_dsh_touch = QPushButton("👋 摸摸头")
        btn_dsh_chat  = QPushButton("💬 对话输入")
        btn_balance   = QPushButton("💰 查余额")
        btn_weather   = QPushButton("⛅ 查天气")
        btn_todo      = QPushButton("📋 待办 (D)")
        btn_sleep     = QPushButton("💤 睡觉 (Z)")
        btn_whisper   = QPushButton("💭 碎碎念")

        for b in (btn_dsh_touch, btn_dsh_chat, btn_balance, btn_weather, btn_todo, btn_sleep, btn_whisper):
            b.setFixedHeight(32)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(96, 165, 250, 0.12);
                    border: 1px solid rgba(96, 165, 250, 0.35);
                    color: {TEXT_PRIMARY};
                    border-radius: 8px;
                    font-size: 12px;
                    font-weight: bold;
                    padding: 0 8px;
                }}
                QPushButton:hover {{
                    background: rgba(96, 165, 250, 0.25);
                    color: #93c5fd;
                }}
            """)
            life_btn_row.addWidget(b)

        btn_dsh_touch.clicked.connect(lambda: self.pet_action.emit('touch'))
        btn_dsh_chat.clicked.connect(lambda: (self._set_control_target('dsh'), self.chat_requested.emit()))
        btn_balance.clicked.connect(lambda: self.pet_action.emit('balance'))
        btn_weather.clicked.connect(lambda: self.pet_action.emit('weather'))
        btn_todo.clicked.connect(lambda: self.pet_action.emit('todo'))
        btn_sleep.clicked.connect(lambda: self.pet_action.emit('sleep_toggle'))
        btn_whisper.clicked.connect(lambda: self.pet_action.emit('whisper'))

        life_layout.addLayout(life_btn_row)
        layout.addWidget(life_card)

        # 2. 📐 水冷屏蓝毛女仆体型与位置微调
        layout.addWidget(self._make_dsh_transform_card())

        # 3. 🎭 动作点播工坊 (114款 WebM 全量分类点播)
        layout.addWidget(self._make_anim_card())

        # 4. 🖼️ 表情包配图点播大厅 (27款 Meme 图文同步)
        layout.addWidget(self._make_meme_card())

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def _make_dsh_transform_card(self) -> QWidget:
        """水冷屏蓝毛女仆体型与位置微调卡片"""
        transform_card = QFrame()
        transform_card.setStyleSheet("""
            QFrame {
                background: rgba(26, 29, 36, 0.90);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }
        """)
        t_layout = QVBoxLayout(transform_card)
        t_layout.setContentsMargins(18, 14, 18, 14)
        t_layout.setSpacing(10)

        t_title = QLabel("📐 水冷屏蓝毛女仆体型与位置微调")
        t_title.setStyleSheet("color: #60a5fa; font-size: 13px; font-weight: bold;")
        t_layout.addWidget(t_title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        # 缩放比例
        lbl_s_tag = QLabel("体型缩放:")
        lbl_s_tag.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        self._slider_scale = QSlider(Qt.Horizontal)
        self._slider_scale.setRange(50, 150)
        self._slider_scale.setValue(100)
        self._lbl_scale_num = QLabel("100%")
        self._lbl_scale_num.setFixedWidth(46)
        self._lbl_scale_num.setStyleSheet(f"color: {ACCENT}; font-size: 12px; font-weight: bold;")
        grid.addWidget(lbl_s_tag, 0, 0)
        grid.addWidget(self._slider_scale, 0, 1)
        grid.addWidget(self._lbl_scale_num, 0, 2)

        # 气泡放大比例
        lbl_b_tag = QLabel("气泡放大:")
        lbl_b_tag.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        self._slider_bubble = QSlider(Qt.Horizontal)
        self._slider_bubble.setRange(80, 200)
        self._slider_bubble.setValue(100)
        self._lbl_bubble_num = QLabel("100%")
        self._lbl_bubble_num.setFixedWidth(46)
        self._lbl_bubble_num.setStyleSheet(f"color: {ACCENT}; font-size: 12px; font-weight: bold;")
        grid.addWidget(lbl_b_tag, 1, 0)
        grid.addWidget(self._slider_bubble, 1, 1)
        grid.addWidget(self._lbl_bubble_num, 1, 2)

        # 水平位置
        lbl_x_tag = QLabel("水平偏移:")
        lbl_x_tag.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        self._slider_pos_x = QSlider(Qt.Horizontal)
        self._slider_pos_x.setRange(-150, 150)
        self._slider_pos_x.setValue(0)
        self._lbl_pos_x_num = QLabel("0 px")
        self._lbl_pos_x_num.setFixedWidth(46)
        self._lbl_pos_x_num.setStyleSheet(f"color: {ACCENT}; font-size: 12px; font-weight: bold;")
        grid.addWidget(lbl_x_tag, 2, 0)
        grid.addWidget(self._slider_pos_x, 2, 1)
        grid.addWidget(self._lbl_pos_x_num, 2, 2)

        # 垂直位置
        lbl_y_tag = QLabel("垂直偏移:")
        lbl_y_tag.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        self._slider_pos_y = QSlider(Qt.Horizontal)
        self._slider_pos_y.setRange(-150, 150)
        self._slider_pos_y.setValue(0)
        self._lbl_pos_y_num = QLabel("0 px")
        self._lbl_pos_y_num.setFixedWidth(46)
        self._lbl_pos_y_num.setStyleSheet(f"color: {ACCENT}; font-size: 12px; font-weight: bold;")
        grid.addWidget(lbl_y_tag, 3, 0)
        grid.addWidget(self._slider_pos_y, 3, 1)
        grid.addWidget(self._lbl_pos_y_num, 3, 2)

        t_layout.addLayout(grid)

        # 操作按钮行：复位居中 + 试看气泡效果
        btn_t_row = QHBoxLayout()
        btn_t_row.setSpacing(10)

        self._btn_reset_transform = QPushButton("↺ 复位默认位置")
        self._btn_reset_transform.setFixedHeight(28)
        self._btn_reset_transform.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
                color: #CBD5E1;
                border-radius: 6px;
                font-size: 12px;
                padding: 0 12px;
            }
            QPushButton:hover { background: rgba(255, 255, 255, 0.16); color: #FFFFFF; }
        """)
        btn_t_row.addWidget(self._btn_reset_transform)

        self._btn_test_bubble = QPushButton("💬 试看台词气泡效果")
        self._btn_test_bubble.setFixedHeight(28)
        self._btn_test_bubble.setStyleSheet(f"""
            QPushButton {{
                background: rgba(111, 227, 255, 0.12);
                border: 1px solid rgba(111, 227, 255, 0.35);
                color: {ACCENT};
                border-radius: 6px;
                font-size: 12px;
                font-weight: bold;
                padding: 0 12px;
            }}
            QPushButton:hover {{ background: rgba(111, 227, 255, 0.25); }}
        """)
        self._btn_test_bubble.clicked.connect(self._on_test_bubble_preview)
        btn_t_row.addWidget(self._btn_test_bubble)
        btn_t_row.addStretch()

        t_layout.addLayout(btn_t_row)

        self._slider_scale.valueChanged.connect(self._on_transform_slider_changed)
        self._slider_bubble.valueChanged.connect(self._on_transform_slider_changed)
        self._slider_pos_x.valueChanged.connect(self._on_transform_slider_changed)
        self._slider_pos_y.valueChanged.connect(self._on_transform_slider_changed)
        self._btn_reset_transform.clicked.connect(self._on_reset_transform)

        return transform_card

    def _make_anim_card(self) -> QWidget:
        """114款动作分类点播工坊卡片"""
        anim_card = QFrame()
        anim_card.setStyleSheet("""
            QFrame {
                background: rgba(26, 29, 36, 0.90);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }
        """)
        anim_layout = QVBoxLayout(anim_card)
        anim_layout.setContentsMargins(18, 14, 18, 14)
        anim_layout.setSpacing(10)

        anim_header = QHBoxLayout()
        anim_title = QLabel("🎭 动作点播工坊（点击即在水冷屏即时播放）")
        anim_title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: bold;")
        anim_header.addWidget(anim_title)
        anim_header.addStretch()
        self._lbl_anim_hint = QLabel("提示：点击动作立即在水冷屏播放")
        self._lbl_anim_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        anim_header.addWidget(self._lbl_anim_hint)
        anim_layout.addLayout(anim_header)

        # 分类标签选择行
        cat_scroll = QScrollArea()
        cat_scroll.setFixedHeight(36)
        cat_scroll.setWidgetResizable(True)
        cat_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        cat_bar = QWidget()
        cat_row = QHBoxLayout(cat_bar)
        cat_row.setContentsMargins(0, 0, 0, 0)
        cat_row.setSpacing(6)
        self._cat_buttons = []

        cat_names = ["全部"] + list(ANIM_CATEGORIES.keys())
        for idx, cat_name in enumerate(cat_names):
            btn_cat = QPushButton(cat_name)
            btn_cat.setCheckable(True)
            btn_cat.setChecked(idx == 0)
            btn_cat.setFixedHeight(26)
            btn_cat.setCursor(Qt.PointingHandCursor)
            btn_cat.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.06);
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    color: #8E98A8;
                    border-radius: 6px;
                    font-size: 11px;
                    padding: 0 8px;
                }
                QPushButton:hover {
                    color: #FFFFFF;
                    background: rgba(255, 255, 255, 0.12);
                }
                QPushButton:checked {
                    background: rgba(111, 227, 255, 0.22);
                    border-color: #6FE3FF;
                    color: #6FE3FF;
                    font-weight: bold;
                }
            """)
            btn_cat.clicked.connect(lambda _, c=cat_name: self._filter_anim_category(c))
            cat_row.addWidget(btn_cat)
            self._cat_buttons.append(btn_cat)
        cat_row.addStretch()
        cat_scroll.setWidget(cat_bar)
        anim_layout.addWidget(cat_scroll)

        # 动作网格容器
        self._anim_grid_widget = QWidget()
        self._anim_grid = QGridLayout(self._anim_grid_widget)
        self._anim_grid.setContentsMargins(0, 4, 0, 4)
        self._anim_grid.setSpacing(8)

        anim_layout.addWidget(self._anim_grid_widget)
        self._populate_anim_grid("全部")
        return anim_card

    def _make_meme_card(self) -> QWidget:
        """27款表情包配图点播大厅卡片"""
        meme_card = QFrame()
        meme_card.setStyleSheet("""
            QFrame {
                background: rgba(26, 29, 36, 0.90);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }
        """)
        meme_layout = QVBoxLayout(meme_card)
        meme_layout.setContentsMargins(18, 14, 18, 14)
        meme_layout.setSpacing(10)

        meme_title = QLabel("🖼️ 表情包配图点播（点击即让水冷屏桌宠弹出对应图文气泡）")
        meme_title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: bold;")
        meme_layout.addWidget(meme_title)

        lbl_g1 = QLabel("💬 纳入对话的经典配图 (20款)")
        lbl_g1.setStyleSheet(f"color: {ACCENT}; font-size: 11px; font-weight: bold;")
        meme_layout.addWidget(lbl_g1)

        grid_m1 = QGridLayout()
        grid_m1.setSpacing(8)
        self._populate_meme_grid(grid_m1, MEMES_DIALOG)
        meme_layout.addLayout(grid_m1)

        lbl_g2 = QLabel("✨ 其他趣味表情 (7款)")
        lbl_g2.setStyleSheet(f"color: {ACCENT}; font-size: 11px; font-weight: bold; margin-top: 6px;")
        meme_layout.addWidget(lbl_g2)

        grid_m2 = QGridLayout()
        grid_m2.setSpacing(8)
        self._populate_meme_grid(grid_m2, MEMES_OTHER)
        meme_layout.addLayout(grid_m2)

        return meme_card

    def _make_background_card(self) -> QWidget:
        """舞台预设背景质感画廊卡片"""
        bg_card = QFrame()
        bg_card.setStyleSheet("""
            QFrame {
                background: rgba(26, 29, 36, 0.90);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }
        """)
        bg_layout = QVBoxLayout(bg_card)
        bg_layout.setContentsMargins(18, 14, 18, 14)
        bg_layout.setSpacing(12)

        bg_title = QLabel("舞台背景质感画廊（内置 640×480 高清定制）")
        bg_title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: bold;")
        bg_layout.addWidget(bg_title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        assets_bg_dir = Path(__file__).resolve().parent.parent / 'assets' / 'backgrounds'

        for idx, (b_key, b_name, b_file, b_desc) in enumerate(PRESET_BACKGROUNDS):
            cell = QFrame()
            cell.setStyleSheet("""
                QFrame {
                    background: rgba(35, 38, 47, 0.85);
                    border: 1px solid rgba(255,255,255,0.08);
                    border-radius: 8px;
                }
                QFrame:hover {
                    border-color: rgba(111,227,255,0.40);
                }
            """)
            c_lay = QVBoxLayout(cell)
            c_lay.setContentsMargins(10, 8, 10, 8)
            c_lay.setSpacing(4)

            # 缩略图
            thumb = QLabel()
            thumb.setFixedSize(96, 64)
            img_path = assets_bg_dir / b_file
            if img_path.is_file():
                px = QPixmap(str(img_path)).scaled(96, 64, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                thumb.setPixmap(px)
            thumb.setStyleSheet("border-radius: 4px; background: #000;")
            c_lay.addWidget(thumb, 0, Qt.AlignCenter)

            name_lbl = QLabel(b_name)
            name_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
            c_lay.addWidget(name_lbl, 0, Qt.AlignCenter)

            desc_lbl = QLabel(b_desc)
            desc_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
            c_lay.addWidget(desc_lbl, 0, Qt.AlignCenter)

            btn_apply = QPushButton("使用")
            btn_apply.setFixedHeight(26)
            btn_apply.setStyleSheet("""
                QPushButton {
                    background: rgba(255,255,255,0.08);
                    color: #F0F3F8;
                    border-radius: 6px;
                    font-size: 11px;
                }
                QPushButton:hover { background: rgba(111,227,255,0.25); color: #6FE3FF; }
            """)
            btn_apply.clicked.connect(lambda ch, k=b_key, f=str(img_path): self._apply_preset_bg(k, f))
            c_lay.addWidget(btn_apply)

            grid.addWidget(cell, idx // 3, idx % 3)

        bg_layout.addLayout(grid)

        # 自定义背景选择行
        custom_row = QHBoxLayout()
        custom_row.setSpacing(10)

        btn_pick_img = QPushButton("📁 导入自定义图片背景…")
        btn_pick_img.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.08);
                color: #F0F3F8;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 8px;
                padding: 6px 14px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.14); }
        """)
        btn_pick_img.clicked.connect(self._on_choose_custom_image)
        custom_row.addWidget(btn_pick_img)

        btn_pick_color = QPushButton("🎨 选择纯色背景…")
        btn_pick_color.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.08);
                color: #F0F3F8;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 8px;
                padding: 6px 14px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.14); }
        """)
        btn_pick_color.clicked.connect(self._on_choose_custom_color)
        custom_row.addWidget(btn_pick_color)

        btn_reset_bg = QPushButton("恢复极简点阵")
        btn_reset_bg.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #8C95A3;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 8px;
                padding: 6px 14px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.06); color: #FFF; }
        """)
        btn_reset_bg.clicked.connect(lambda: self._apply_preset_bg('dots', ''))
        custom_row.addWidget(btn_reset_bg)

        custom_row.addStretch()
        bg_layout.addLayout(custom_row)
        return bg_card

    # ---------------------------------------------------------------- 页 2：屏幕固件
    def _make_page_firmware(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("TCOMAS LG700 原生 Flash 固件工坊")
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        tip = QLabel("可安全替换冷头内部断电待机壁纸与开机自检动画。刷写过程将自动暂停推流并互斥操作，完成后无缝恢复。")
        tip.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        layout.addWidget(tip)

        # 嵌入 FlashWidget
        self._flash_widget = FlashWidget(parent=self)
        self._wire_flash_widget()
        layout.addWidget(self._flash_widget)

        layout.addStretch()
        return page

    def _wire_flash_widget(self):
        self._flash_widget.wallpaper_change_requested.connect(self._on_change_wallpaper)
        self._flash_widget.animation_change_requested.connect(self._on_change_animation)
        self._flash_widget.wallpaper_reset_requested.connect(self._on_reset_flash)
        self._flash_widget.animation_reset_requested.connect(self._on_reset_flash)

    # ---------------------------------------------------------------- 页 3：硬件诊断
    def _make_page_diagnostics(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        title = QLabel("USB 设备与复合总线诊断")
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        diag_card = QFrame()
        diag_card.setStyleSheet("""
            QFrame {
                background: rgba(26, 29, 36, 0.90);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }
        """)
        d_lay = QGridLayout(diag_card)
        d_lay.setContentsMargins(20, 16, 20, 16)
        d_lay.setHorizontalSpacing(24)
        d_lay.setVerticalSpacing(12)

        items = [
            ("设备型号", "TCOMAS LG700 (640×480 IPS 水冷屏)"),
            ("硬件标识", "VID: 0x1A2C  |  PID: 0x151C"),
            ("驱动方案", "Windows 原生 HID (无依赖纯 ctypes kernel32 DirectIO)"),
            ("控制端口 (MI_00)", "UsagePage: 0xFF06, Usage: 0x0001 (固件与开机动画刷写)"),
            ("数据端口 (MI_01)", "UsagePage: 0xFF06, Usage: 0x0002 (1025B JPEG 实时流分包)"),
            ("当前传输通道", "WriteFile 异步 OVERLAPPED 互斥管道"),
        ]

        for i, (k, v) in enumerate(items):
            k_lbl = QLabel(k)
            k_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; font-weight: bold;")
            v_lbl = QLabel(v)
            v_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
            d_lay.addWidget(k_lbl, i, 0)
            d_lay.addWidget(v_lbl, i, 1)

        layout.addWidget(diag_card)

        # 诊断操作
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        btn_reconnect = QPushButton("🔄 重新枚举并重置推流总线")
        btn_reconnect.setStyleSheet("""
            QPushButton {
                background: rgba(111,227,255,0.14);
                color: #6FE3FF;
                border: 1px solid rgba(111,227,255,0.35);
                border-radius: 8px;
                padding: 7px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background: rgba(111,227,255,0.25); }
        """)
        btn_reconnect.clicked.connect(self._on_reconnect_bus)
        action_row.addWidget(btn_reconnect)

        action_row.addStretch()
        layout.addLayout(action_row)

        layout.addStretch()
        return page

    # ---------------------------------------------------------------- 页 4：偏好设置
    def _make_page_settings(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        title = QLabel("系统与软件偏好设置")
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        s_card = QFrame()
        s_card.setStyleSheet("""
            QFrame {
                background: rgba(26, 29, 36, 0.90);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }
        """)
        s_lay = QVBoxLayout(s_card)
        s_lay.setContentsMargins(20, 16, 20, 16)
        s_lay.setSpacing(14)

        self._chk_autostart = QCheckBox("开机自动启动桌宠之家（后台推流水冷屏）")
        self._chk_autostart.setChecked(is_autostart_enabled())
        self._chk_autostart.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        self._chk_autostart.toggled.connect(self._on_toggle_autostart)
        s_lay.addWidget(self._chk_autostart)

        self._chk_close_tray = QCheckBox("关闭此窗口时最小化到系统托盘（不退出程序，保持屏幕运行）")
        self._chk_close_tray.setChecked(True)
        self._chk_close_tray.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        s_lay.addWidget(self._chk_close_tray)

        self._chk_ball_snap = QCheckBox("桌面悬浮球靠近屏幕边缘时自动磁吸")
        self._chk_ball_snap.setChecked(True)
        self._chk_ball_snap.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        self._chk_ball_snap.toggled.connect(self._on_toggle_ball_snap)
        s_lay.addWidget(self._chk_ball_snap)

        self._chk_ball_peek = QCheckBox("桌面悬浮球无操作时半隐藏收纳（仅露出 55%）")
        self._chk_ball_peek.setChecked(True)
        self._chk_ball_peek.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        self._chk_ball_peek.toggled.connect(self._on_toggle_ball_peek)
        s_lay.addWidget(self._chk_ball_peek)

        layout.addWidget(s_card)

        # 快捷工具行
        tool_row = QHBoxLayout()
        tool_row.setSpacing(10)

        btn_open_appdata = QPushButton("📂 打开配置文件所在目录")
        btn_open_appdata.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.08);
                color: #F0F3F8;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 8px;
                padding: 7px 16px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.14); }
        """)
        btn_open_appdata.clicked.connect(self._on_open_appdata)
        tool_row.addWidget(btn_open_appdata)

        btn_clear_cache = QPushButton("🧹 清理运行缓存与临时文件")
        btn_clear_cache.setStyleSheet("""
            QPushButton {
                background: rgba(111, 227, 255, 0.12);
                color: #6FE3FF;
                border: 1px solid rgba(111, 227, 255, 0.35);
                border-radius: 8px;
                padding: 7px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background: rgba(111, 227, 255, 0.22); }
        """)
        btn_clear_cache.clicked.connect(self._on_clear_cache)
        tool_row.addWidget(btn_clear_cache)

        btn_reset_cfg = QPushButton("重置所有设置为默认")
        btn_reset_cfg.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #FF5B5B;
                border: 1px solid rgba(255,91,91,0.35);
                border-radius: 8px;
                padding: 7px 16px;
            }
            QPushButton:hover { background: rgba(255,91,91,0.15); }
        """)
        btn_reset_cfg.clicked.connect(self._on_reset_config)
        tool_row.addWidget(btn_reset_cfg)

        tool_row.addStretch()
        layout.addLayout(tool_row)

        layout.addStretch()
        return page

    # ================================================================
    # 窗口拖拽（基于 Windows 原生 startSystemMove，杜绝卡顿与粘滞）
    # ================================================================

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            local_pos = self.mapFromGlobal(event.globalPosition().toPoint())
            if local_pos.y() <= 48:
                wh = self.windowHandle()
                if wh and hasattr(wh, 'startSystemMove') and wh.startSystemMove():
                    event.accept()
                    return
                # 兜底手动拖拽
                self._dragging_header = True
                self._drag_offset = event.globalPosition().toPoint() - self.pos()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # 核心防护：若左键未按住，坚决清空拖拽标记，杜绝窗口粘滞与假死卡住
        if not (event.buttons() & Qt.LeftButton):
            self._dragging_header = False
            super().mouseMoveEvent(event)
            return

        if self._dragging_header:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging_header = False
        super().mouseReleaseEvent(event)

    def changeEvent(self, event):
        # 窗口激活/失焦或状态改变时重置拖拽标记
        self._dragging_header = False
        super().changeEvent(event)

    def leaveEvent(self, event):
        # 鼠标指针移出窗口范围且未按住左键时安全复位
        if not (self.mouseButtons() & Qt.LeftButton):
            self._dragging_header = False
        super().leaveEvent(event)

    # ================================================================
    # 状态与槽处理
    # ================================================================

    def _sync_settings(self):
        if not self.settings:
            return
        scale, bg_mode, bg_value, pushing, *rest = self.settings.snapshot()
        ox = getattr(self.settings, 'offset_x', 0)
        oy = getattr(self.settings, 'offset_y', 0)
        b_scale = getattr(self.settings, 'bubble_scale', 1.0)
        if hasattr(self, '_slider_scale'):
            self._slider_scale.blockSignals(True)
            self._slider_pos_x.blockSignals(True)
            self._slider_pos_y.blockSignals(True)
            self._slider_scale.setValue(int(scale * 100))
            self._slider_pos_x.setValue(ox)
            self._slider_pos_y.setValue(oy)
            self._lbl_scale_num.setText(f"{int(scale * 100)}%")
            self._lbl_pos_x_num.setText(f"{ox} px")
            self._lbl_pos_y_num.setText(f"{oy} px")
            self._slider_scale.blockSignals(False)
            self._slider_pos_x.blockSignals(False)
            self._slider_pos_y.blockSignals(False)
        if hasattr(self, '_slider_bubble'):
            self._slider_bubble.blockSignals(True)
            self._slider_bubble.setValue(int(b_scale * 100))
            self._lbl_bubble_num.setText(f"{int(b_scale * 100)}%")
            self._slider_bubble.blockSignals(False)
        try:
            idx = SCALES.index(scale)
            if hasattr(self, '_scale_slider'):
                self._scale_slider.setValue(idx)
            if hasattr(self, '_lbl_scale_value'):
                self._lbl_scale_value.setText(f"{scale}×")
        except ValueError:
            pass
        coop_sc = getattr(self.settings, 'coopanion_scale', 1.6)
        try:
            c_idx = SCALES.index(coop_sc)
            if hasattr(self, '_slider_coop_scale'):
                self._slider_coop_scale.blockSignals(True)
                self._slider_coop_scale.setValue(c_idx)
                self._slider_coop_scale.blockSignals(False)
            if hasattr(self, '_lbl_coop_scale_val'):
                tag = f"{coop_sc}× (默认推荐)" if coop_sc == 1.6 else f"{coop_sc}×"
                self._lbl_coop_scale_val.setText(tag)
        except ValueError:
            pass
        if hasattr(self, '_chk_display_mode'):
            is_screen_mode = bool(pushing and getattr(self.settings, 'hide_desktop_pet', True))
            self._chk_display_mode.blockSignals(True)
            self._chk_display_mode.setChecked(is_screen_mode)
            self._chk_display_mode.blockSignals(False)
        if hasattr(self, '_chk_pushing'):
            self._chk_pushing.setChecked(pushing)
        if hasattr(self, '_chk_hide_desktop'):
            self._chk_hide_desktop.setChecked(self.settings.hide_desktop_pet)
        if hasattr(self, '_chk_ball_snap'):
            self._chk_ball_snap.blockSignals(True)
            self._chk_ball_snap.setChecked(getattr(self.settings, 'ball_snap', True))
            self._chk_ball_snap.blockSignals(False)
        if hasattr(self, '_chk_ball_peek'):
            self._chk_ball_peek.blockSignals(True)
            self._chk_ball_peek.setChecked(getattr(self.settings, 'ball_peek', True))
            self._chk_ball_peek.blockSignals(False)

    def _on_timer_tick(self):
        fps = self._status.get('fps', 0.0)
        kb = self._status.get('kb', 0.0)
        pkt = self._status.get('pkt', 0)
        ok = self._status.get('ok', False)
        msg = self._status.get('msg', '等待设备')

        self._lbl_fps_val.setText(f"{fps:.1f} FPS")
        self._lbl_bw_val.setText(f"{kb:.1f} KB/s")
        self._lbl_pkt_val.setText(f"{pkt:,} 包")
        self._lbl_status_val.setText(msg)

        # 仅当连接状态发生跳变时才重设 QSS 样式表，避免每 400ms 频繁 CSS 重算造成界面卡顿
        if not hasattr(self, '_last_ok_status') or self._last_ok_status != ok:
            self._last_ok_status = ok
            if ok:
                self._lbl_status_val.setStyleSheet("font-size: 14px; font-weight: bold; color: #6FE3FF;")
                self._status_badge.setText(f"● LG700 已连接 ({fps:.1f} FPS)")
                self._status_badge.setStyleSheet("""
                    color: #6FE3FF;
                    font-size: 12px;
                    padding: 4px 12px;
                    border-radius: 12px;
                    background: rgba(111, 227, 255, 0.12);
                    border: 1px solid rgba(111, 227, 255, 0.25);
                """)
            else:
                self._lbl_status_val.setStyleSheet("font-size: 14px; font-weight: bold; color: #FF5B5B;")
                self._status_badge.setText("○ 等待设备连接")
                self._status_badge.setStyleSheet("""
                    color: #FF5B5B;
                    font-size: 12px;
                    padding: 4px 12px;
                    border-radius: 12px;
                    background: rgba(255, 91, 91, 0.12);
                    border: 1px solid rgba(255, 91, 91, 0.25);
                """)

    def on_status_updated(self, fps: float, kb: float, pkt: int, ok: bool, msg: str):
        self._status = dict(fps=fps, kb=kb, pkt=pkt, ok=ok, msg=msg)

    def on_frame_ready(self, jpeg_bytes: bytes):
        self._last_jpeg_bytes = jpeg_bytes
        # 核心防卡顿机制：仅在控制中心可见且当前停留在【运行概览】页 (0) 时才解码并重绘，杜绝切页背景过载
        if self.isVisible() and self._stack.currentIndex() == 0:
            self._overview_preview.update_frame(jpeg_bytes)

    def _on_toggle_display_mode(self, checked: bool):
        """切换桌宠显示位置：开=小屏幕运作/隐藏主桌面；关=主桌面运作/小屏待机"""
        if self.settings:
            self.settings.update(pushing=checked, hide_desktop_pet=checked)
        self.stream_toggled.emit(checked)
        self.hide_pet_toggled.emit(checked)

    def _on_transform_slider_changed(self):
        scale = self._slider_scale.value() / 100.0
        ox = self._slider_pos_x.value()
        oy = self._slider_pos_y.value()
        b_scale = self._slider_bubble.value() / 100.0 if hasattr(self, '_slider_bubble') else 1.0
        self._lbl_scale_num.setText(f"{self._slider_scale.value()}%")
        self._lbl_pos_x_num.setText(f"{ox} px")
        self._lbl_pos_y_num.setText(f"{oy} px")
        if hasattr(self, '_lbl_bubble_num'):
            self._lbl_bubble_num.setText(f"{self._slider_bubble.value()}%")
        self.transform_changed.emit(scale, ox, oy)
        self.bubble_scale_changed.emit(b_scale)
        if self.settings:
            self.settings.update(scale=scale, offset_x=ox, offset_y=oy, bubble_scale=b_scale)

    def _on_test_bubble_preview(self):
        """立即向水冷屏派发一条测试台词气泡，便于用户直观检验气泡放大效果。"""
        pct = self._slider_bubble.value() if hasattr(self, '_slider_bubble') else 100
        msg = f"气泡放大 {pct}% 测试：主人能看清我说话吗？"
        if self.renderer:
            self.renderer.send_command('say', text=msg, meme='可爱')
        else:
            self.meme_requested.emit('可爱')

    def _on_reset_transform(self):
        self._slider_scale.blockSignals(True)
        self._slider_pos_x.blockSignals(True)
        self._slider_pos_y.blockSignals(True)
        if hasattr(self, '_slider_bubble'):
            self._slider_bubble.blockSignals(True)
            self._slider_bubble.setValue(100)
            self._slider_bubble.blockSignals(False)
        self._slider_scale.setValue(100)
        self._slider_pos_x.setValue(0)
        self._slider_pos_y.setValue(0)
        self._slider_scale.blockSignals(False)
        self._slider_pos_x.blockSignals(False)
        self._slider_pos_y.blockSignals(False)
        self._on_transform_slider_changed()

    def _filter_anim_category(self, cat_name: str):
        for btn in self._cat_buttons:
            btn.setChecked(btn.text() == cat_name)
        self._populate_anim_grid(cat_name)

    def _populate_anim_grid(self, category: str):
        # 清空网格旧按钮
        while self._anim_grid.count():
            item = self._anim_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if category == "全部":
            all_actions = []
            for lst in ANIM_CATEGORIES.values():
                for a in lst:
                    if a not in all_actions:
                        all_actions.append(a)
            items = all_actions
        else:
            items = ANIM_CATEGORIES.get(category, [])

        cols = 4
        for idx, name in enumerate(items):
            btn = QPushButton(name)
            btn.setFixedHeight(28)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.06);
                    border: 1px solid rgba(255, 255, 255, 0.10);
                    color: #CBD5E1;
                    border-radius: 6px;
                    font-size: 11px;
                    padding: 0 6px;
                }
                QPushButton:hover {
                    background: rgba(111, 227, 255, 0.20);
                    border-color: #6FE3FF;
                    color: #FFFFFF;
                }
                QPushButton:pressed {
                    background: rgba(47, 115, 246, 0.35);
                }
            """)
            btn.clicked.connect(lambda _, n=name: self._on_anim_button_clicked(n))
            self._anim_grid.addWidget(btn, idx // cols, idx % cols)

    def _on_anim_button_clicked(self, anim_name: str):
        self._lbl_anim_hint.setText(f"✓ 已在水冷屏点播: {anim_name}")
        self._lbl_anim_hint.setStyleSheet("color: #6FE3FF; font-size: 11px;")
        self.anim_requested.emit(anim_name)

    def _populate_meme_grid(self, grid: QGridLayout, memes_list: list[str]):
        memes_dir = Path(__file__).resolve().parent.parent / 'assets' / 'memes'
        cols = 4
        for idx, meme_name in enumerate(memes_list):
            btn = QPushButton()
            btn.setFixedHeight(34)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(f"在水冷屏展示: {meme_name}")

            btn_layout = QHBoxLayout(btn)
            btn_layout.setContentsMargins(6, 2, 6, 2)
            btn_layout.setSpacing(6)

            icon_lbl = QLabel()
            icon_lbl.setFixedSize(24, 24)
            icon_lbl.setScaledContents(True)
            img_path = memes_dir / f"{meme_name}.png"
            if img_path.is_file():
                icon_lbl.setPixmap(QPixmap(str(img_path)))
            btn_layout.addWidget(icon_lbl)

            txt_lbl = QLabel(meme_name)
            txt_lbl.setStyleSheet("color: #CBD5E1; font-size: 11px; border: none; background: transparent;")
            btn_layout.addWidget(txt_lbl, 1)

            btn.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.05);
                    border: 1px solid rgba(255, 255, 255, 0.10);
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background: rgba(111, 227, 255, 0.18);
                    border-color: #6FE3FF;
                }
            """)
            btn.clicked.connect(lambda _, m=meme_name: self.meme_requested.emit(m))
            grid.addWidget(btn, idx // cols, idx % cols)

    def _on_scale_slider_changed(self, idx: int):
        val = SCALES[idx]
        self._lbl_scale_value.setText(f"{val}×")
        self.scale_changed.emit(val)
        if self.settings:
            self.settings.update(scale=val)

    def _apply_preset_bg(self, key: str, file_path: str):
        if key == 'dots' or not file_path:
            if self.settings:
                self.settings.update(bg_mode='dots', bg_value='#0D1117')
            self.background_changed.emit('dots', '#0D1117')
        else:
            if self.settings:
                self.settings.update(bg_mode='image', bg_value=file_path)
            self.background_changed.emit('image', file_path)

    def _on_choose_custom_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择自定义背景图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if path:
            self._apply_preset_bg('image', path)

    def _on_choose_custom_color(self):
        color = QColorDialog.getColor(QColor(13, 17, 23), self, "选择背景颜色")
        if color.isValid():
            c_hex = color.name()
            if self.settings:
                self.settings.update(bg_mode='color', bg_value=c_hex)
            self.background_changed.emit('color', c_hex)

    def _on_toggle_pushing(self, checked: bool):
        self.stream_toggled.emit(checked)
        if self.settings:
            self.settings.update(pushing=checked)

    def _on_toggle_hide_desktop(self, checked: bool):
        if self.settings:
            self.settings.update(hide_desktop_pet=checked)
        self.hide_pet_toggled.emit(checked)

    def _on_touch_action(self):
        self.pet_action.emit('touch')

    def _on_reload_page(self):
        if self.renderer:
            self.renderer.send_command('reload')

    def _on_reconnect_bus(self):
        if self.pusher:
            log.info("用户请求手动重置 USB 推流总线...")
            # 模拟断开并重连
            self.pusher.pause()
            QTimer.singleShot(600, self.pusher.resume)

    def _on_toggle_autostart(self, checked: bool):
        ok = set_autostart(checked)
        if not ok:
            QMessageBox.warning(self, "设置失败", "修改 Windows 开机自启注册表项失败，请以管理员身份重试。")
            self._chk_autostart.setChecked(is_autostart_enabled())
        else:
            if self.settings:
                self.settings.update(autostart=checked)

    def _on_toggle_ball_snap(self, checked: bool):
        if self.settings:
            self.settings.update(ball_snap=checked)
        self.ball_snap_toggled.emit(checked)

    def _on_toggle_ball_peek(self, checked: bool):
        if self.settings:
            self.settings.update(ball_peek=checked)
        self.ball_peek_toggled.emit(checked)

    def _on_open_appdata(self):
        p = Path(os.environ.get('APPDATA', '')) / 'BigFishTitanConsole'
        if not p.exists():
            p = Path(os.environ.get('APPDATA', '')) / 'DshPetConsole'
        p.mkdir(parents=True, exist_ok=True)
        os.startfile(str(p))

    def _on_clear_cache(self):
        freed_bytes = 0
        cleaned_items = 0
        try:
            import tempfile, shutil
            temp_dir = Path(tempfile.gettempdir())
            # 1. 清理临时推流、转码与截帧文件
            for pat in ('tcomas_*', 'bigfish_*', 'playwright_*', 'tmp*tcomas*'):
                for p in temp_dir.glob(pat):
                    try:
                        if p.is_file():
                            freed_bytes += p.stat().st_size
                            p.unlink(missing_ok=True)
                            cleaned_items += 1
                        elif p.is_dir():
                            for sub in p.rglob('*'):
                                if sub.is_file():
                                    freed_bytes += sub.stat().st_size
                            shutil.rmtree(p, ignore_errors=True)
                            cleaned_items += 1
                    except Exception:
                        pass

            # 2. 清理 APPDATA 下大于 1MB 的超长旧日志
            for app_name in ('BigFishTitanConsole', 'DshPetConsole'):
                appdata_log = Path(os.environ.get('APPDATA', '')) / app_name
                if appdata_log.is_dir():
                    for lf in appdata_log.glob('*.log*'):
                        try:
                            sz = lf.stat().st_size
                            if sz > 1024 * 1024:
                                freed_bytes += sz
                                with open(lf, 'w', encoding='utf-8') as f:
                                    f.write('')
                                cleaned_items += 1
                        except Exception:
                            pass
        except Exception as e:
            log.warning('清理缓存异常: %s', e)

        freed_mb = freed_bytes / (1024.0 * 1024.0)
        QMessageBox.information(
            self,
            "缓存与临时文件清理完成",
            f"✅ 缓存清理完毕！\n\n共扫描并释放了 {freed_mb:.2f} MB 临时素材、转码碎片与冗余日志，系统处于最优化轻量状态。"
        )

    def _on_reset_config(self):
        res = QMessageBox.question(
            self, "确认重置", "确定要将所有设置恢复为出厂默认值吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if res == QMessageBox.Yes:
            if self.settings:
                self.settings.update(
                    scale=1.0,
                    bg_mode='dots',
                    bg_value='#0D1117',
                    pushing=True,
                    hide_desktop_pet=True,
                    ball_snap=True,
                    ball_peek=True
                )
                self._sync_settings()

    # 固件管理动作
    def _on_change_wallpaper(self, path_str: str):
        if not self.flash_bridge:
            QMessageBox.warning(self, "提示", "固件管理模块未就绪")
            return
        try:
            from PIL import Image, ImageOps
            with Image.open(path_str) as im:
                im = im.convert("RGB")
                im = ImageOps.fit(im, (640, 480), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=85, progressive=False)
                jpeg_bytes = buf.getvalue()

            backup_dir = Path(__file__).resolve().parent.parent / 'assets' / 'defaults'
            backup_dir.mkdir(parents=True, exist_ok=True)
            self.flash_bridge.write_standby(jpeg_bytes, backup_dir)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"图片转换失败：{e}")

    def _on_change_animation(self, path_str: str):
        if not self.flash_bridge:
            QMessageBox.warning(self, "提示", "固件管理模块未就绪")
            return
        try:
            from convert_media import cached_build_asset, unpack_boot  # type: ignore
            asset_bytes = cached_build_asset(path_str, quality=75, fill_screen=True)
            frames = unpack_boot(asset_bytes, inspect_jpeg=False)
            backup_dir = Path(__file__).resolve().parent.parent / 'assets' / 'defaults'
            self.flash_bridge.write_boot(frames, backup_dir)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"动画解析转换失败：{e}")

    def _on_reset_flash(self):
        if not self.flash_bridge:
            return
        defaults_dir = Path(__file__).resolve().parent.parent / 'assets' / 'defaults'
        if not (defaults_dir / 'standby.bin').exists():
            QMessageBox.warning(self, "出厂素材不存在", "未在 defaults 目录中找到出厂备份文件")
            return
        self.flash_bridge.restore_factory(defaults_dir)

    def jump_to_tab(self, tab_idx: int):
        if 0 <= tab_idx < len(self._nav_buttons):
            self._on_nav_selected(tab_idx)
