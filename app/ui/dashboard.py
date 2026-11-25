# -*- coding: utf-8 -*-
"""dashboard.py — 大肥鱼桌宠钛坦屏投放工具 · 可视化控制中心（920×600 极简现代暗黑工作台）。

左侧 5 大核心导航模块：
1. 📊 实时概览（400×300 实时监视画幅、快捷模式与互动、推流性能仪表、双端服务状态栏）
2. 🚀 投放布局（单宠/双宠模式选卡、双宠分屏比例、悬浮球控制目标、双端引擎状态与一键拉起）
3. 🎭 桌宠工坊（3 大子页：🎬 动作与互动 [全量 114 款动作] / 💬 表情与气泡 [27 款 Meme] / 🎨 外观与背景 [双宠体型位移 + 壁纸画廊]）
4. ⚡ 固件与硬件（冷头待机壁纸/开机动画刷写与恢复出厂 + USB 复合总线状态与重置）
5. ⚙️ 偏好设置（开机自启、托盘驻留、悬浮球贴边磁吸与半隐、缓存清理与配置目录）
"""
from __future__ import annotations

import io
import logging
import os
import socket
import subprocess
import tempfile
import shutil
import time
from pathlib import Path

from PySide6.QtCore import (
    Qt, QTimer, QPoint, QRectF, Signal
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath,
    QPixmap
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QCheckBox, QColorDialog,
    QFileDialog, QFrame, QStackedWidget, QMessageBox,
    QScrollArea, QGridLayout, QRadioButton
)

from .tokens import (
    SURFACE, SURFACE_HOVER, SURFACE_ACTIVE,
    BORDER, ACCENT, TEXT_PRIMARY, TEXT_MUTED, TEXT_ACCENT,
    DANGER, SCALES
)
from .preview import PreviewWidget
from .flash_widget import FlashWidget
from .ball_menu import ACTION_CATEGORIES
try:
    from core.autostart import is_autostart_enabled, set_autostart
except ImportError:
    from ..core.autostart import is_autostart_enabled, set_autostart

log = logging.getLogger('tcomas.ui.dashboard')

DASHBOARD_W = 920
DASHBOARD_H = 600

# 预设背景定义
PRESET_BACKGROUNDS = [
    ('dots', '深空点阵', 'bg_1_dots.jpg', '经典微光点阵'),
    ('gradient', '暗夜极光', 'bg_2_gradient.jpg', '深邃暗夜流光'),
    ('starry', '璀璨星河', 'bg_3_starry.jpg', '微茫星宿散落'),
    ('underwater', '幽蓝深海', 'bg_4_underwater.jpg', '清爽深海水下'),
    ('cyber', '赛博碳纤', 'bg_5_cyber.jpg', '机械矩阵纹理'),
    ('midnight', '午夜纯黑', 'bg_6_midnight.jpg', '纯粹暗黑沉浸'),
]

# 默认展示的合规表情包清单（运行时会自动扫描并合并本地 assets/memes 目录下的全部表情）
MEMES_DIALOG = [
    '吃白饭的大肥鱼', '大的要来啦', '大的药来了', '深度睡眠', '先养着吧',
    '吃饱饱摸肚子', '誓死践行开源精神', '电死你', '可爱', 'token给妈妈保管',
    '假如给我三天多模态', '厉害了我的鲸', '哦鲸鲸', '压力一只大肥鱼',
    '黎曼猜想没证明喵', '我不更新你们用什么'
]

MEMES_OTHER = [
    '大师这个区是什么意思', '就一碗', 'Ciallo'
]

_CARD_QSS = """
QFrame#SectionCard {
    background: rgba(25, 28, 36, 0.92);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
}
"""


def _make_card() -> QFrame:
    card = QFrame()
    card.setObjectName("SectionCard")
    card.setStyleSheet(_CARD_QSS)
    return card


def _is_port_open(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.15)
            return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False


class _DashboardTitleBar(QWidget):
    """控制中心顶部自定义标题栏，支持原生 Windows 丝滑拖拽。"""

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

    def __init__(self, settings=None, renderer=None, pusher=None, flash_bridge=None, dsh_client=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.renderer = renderer
        self.pusher = pusher
        self.flash_bridge = flash_bridge
        self.dsh_client = dsh_client

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
        self._coop_online = False
        self._dsh_online = False
        self._dsh_port = 0
        self._probe_tick = 0

        self._build_ui()

        # 状态定时刷新 (500ms)
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._on_timer_tick)
        self._timer.start()

        self._sync_settings()
        self._probe_services_async()

    # ================================================================
    # 窗口外观绘制
    # ================================================================

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(rect, 14.0, 14.0)

        painter.fillPath(path, QBrush(QColor(16, 18, 24, 248)))

        pen = QPen(QColor(255, 255, 255, 24), 1.0)
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

        root.addWidget(self._make_titlebar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        body.addWidget(self._make_sidebar())

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("background: rgba(255,255,255,0.06); max-width: 1px;")
        body.addWidget(sep)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")

        self._stack.addWidget(self._make_page_overview())     # 0: 实时概览
        self._stack.addWidget(self._make_page_cast())         # 1: 投放布局
        self._stack.addWidget(self._make_page_pet())          # 2: 桌宠工坊
        self._stack.addWidget(self._make_page_firmware())     # 3: 固件与硬件
        self._stack.addWidget(self._make_page_settings())     # 4: 偏好设置

        body.addWidget(self._stack, 1)
        root.addLayout(body, 1)

    # ---------------------------------------------------------------- 标题栏
    def _make_titlebar(self) -> QWidget:
        tb = _DashboardTitleBar(self)
        tb.setFixedHeight(48)
        tb.setStyleSheet("""
            QWidget {
                background: rgba(22, 25, 32, 0.96);
                border-top-left-radius: 14px;
                border-top-right-radius: 14px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.06);
            }
        """)

        layout = QHBoxLayout(tb)
        layout.setContentsMargins(18, 0, 14, 0)
        layout.setSpacing(10)

        icon_lbl = QLabel()
        ico_file = Path(__file__).resolve().parent.parent / 'assets' / 'app_icon.ico'
        if ico_file.is_file():
            icon_lbl.setPixmap(QPixmap(str(ico_file)).scaled(22, 22, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            icon_lbl.setText("🐟")
            icon_lbl.setStyleSheet("font-size: 16px;")
        layout.addWidget(icon_lbl)

        title = QLabel("大肥鱼钛坦屏控制台")
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {TEXT_PRIMARY};")
        layout.addWidget(title)

        tag = QLabel("LG700 双宠中枢")
        tag.setStyleSheet("""
            background: rgba(111, 227, 255, 0.12);
            color: #6FE3FF;
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 6px;
            border: 1px solid rgba(111, 227, 255, 0.28);
        """)
        layout.addWidget(tag)

        layout.addStretch()

        self._status_badge = QLabel("● 水冷屏检测中…")
        self._status_badge.setStyleSheet("""
            color: #8C95A3;
            font-size: 12px;
            padding: 4px 12px;
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.05);
        """)
        layout.addWidget(self._status_badge)

        btn_min = QPushButton("—")
        btn_min.setFixedSize(30, 30)
        btn_min.setToolTip("最小化")
        btn_min.setCursor(Qt.PointingHandCursor)
        btn_min.setStyleSheet("""
            QPushButton {
                background: transparent; color: #8C95A3; font-size: 13px; border-radius: 6px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.08); color: #FFF; }
        """)
        btn_min.clicked.connect(self.showMinimized)
        layout.addWidget(btn_min)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(30, 30)
        btn_close.setToolTip("隐藏至系统托盘（保持后台运行）")
        btn_close.setCursor(Qt.PointingHandCursor)
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
        sidebar.setFixedWidth(168)
        sidebar.setStyleSheet("background: rgba(16, 18, 24, 0.98);")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 16, 10, 14)
        layout.setSpacing(6)

        self._nav_buttons = []
        nav_items = [
            ("📊  实时概览", 0),
            ("🚀  投放布局", 1),
            ("🎭  桌宠工坊", 2),
            ("⚡  固件与硬件", 3),
            ("⚙️  偏好设置", 4),
        ]

        for text, idx in nav_items:
            btn = QPushButton(text)
            btn.setFixedHeight(40)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
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
                    background: rgba(111, 227, 255, 0.13);
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

        ver_lbl = QLabel("BigFishTitan v1.2\nDirectIO · 640×480")
        ver_lbl.setStyleSheet("color: rgba(140,149,163,0.45); font-size: 11px; padding: 6px;")
        layout.addWidget(ver_lbl)

        return sidebar

    def _on_nav_selected(self, index: int):
        if self._stack.currentIndex() == index:
            return
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)
        self._stack.setCurrentIndex(index)
        if index == 0 and hasattr(self, '_last_jpeg_bytes') and self._last_jpeg_bytes:
            self._overview_preview.update_frame(self._last_jpeg_bytes)

    # ---------------------------------------------------------------- 页 0：实时概览
    def _make_page_overview(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.setSpacing(14)

        # 左侧：400×300 实时预览画幅卡片
        preview_card = _make_card()
        pv_layout = QVBoxLayout(preview_card)
        pv_layout.setContentsMargins(12, 10, 12, 12)
        pv_layout.setSpacing(8)

        pv_header = QHBoxLayout()
        pv_title = QLabel("实时画面预览  ·  640×480")
        pv_title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
        pv_header.addWidget(pv_title)
        pv_header.addStretch()

        self._btn_reload = QPushButton("↻ 刷新舞台")
        self._btn_reload.setFixedHeight(24)
        self._btn_reload.setCursor(Qt.PointingHandCursor)
        self._btn_reload.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.07);
                border: 1px solid rgba(255, 255, 255, 0.12);
                color: #CBD5E1;
                border-radius: 6px;
                padding: 0 10px;
                font-size: 11px;
            }
            QPushButton:hover { background: rgba(111, 227, 255, 0.18); color: #6FE3FF; }
        """)
        self._btn_reload.clicked.connect(self._on_reload_page)
        pv_header.addWidget(self._btn_reload)
        pv_layout.addLayout(pv_header)

        self._overview_preview = PreviewWidget()
        self._overview_preview.setFixedSize(400, 300)
        pv_layout.addWidget(self._overview_preview, 0, Qt.AlignCenter)

        top_row.addWidget(preview_card, 0)

        # 右侧：快捷控制 + 性能指标列
        right_col = QVBoxLayout()
        right_col.setSpacing(12)

        # 卡片 1：投放开关、模式速切与快捷互动
        ctrl_card = _make_card()
        ctrl_layout = QVBoxLayout(ctrl_card)
        ctrl_layout.setContentsMargins(16, 12, 16, 12)
        ctrl_layout.setSpacing(10)

        self._chk_display_mode = QCheckBox("🖥️ 水冷屏投放运作（自动隐藏主桌面原版桌宠）")
        self._chk_display_mode.setChecked(True)
        self._chk_display_mode.setCursor(Qt.PointingHandCursor)
        self._chk_display_mode.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: bold;")
        self._chk_display_mode.toggled.connect(self._on_toggle_display_mode)
        ctrl_layout.addWidget(self._chk_display_mode)

        # 概览页一键模式速切胶囊行
        quick_mode_row = QHBoxLayout()
        quick_mode_row.setSpacing(6)
        self._ov_btn_coop = QPushButton("🐟 大肥鱼")
        self._ov_btn_dsh  = QPushButton("👧 蓝毛女仆")
        self._ov_btn_dual = QPushButton("🌟 双宠同台")
        for b, m in ((self._ov_btn_coop, 'coopanion'), (self._ov_btn_dsh, 'dsh'), (self._ov_btn_dual, 'dual')):
            b.setCheckable(True)
            b.setFixedHeight(28)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.05);
                    color: {TEXT_MUTED};
                    border: 1px solid rgba(255, 255, 255, 0.10);
                    border-radius: 7px;
                    font-size: 12px;
                }}
                QPushButton:hover {{ color: {TEXT_PRIMARY}; background: rgba(255, 255, 255, 0.10); }}
                QPushButton:checked {{
                    background: rgba(111, 227, 255, 0.16);
                    color: {ACCENT};
                    border: 1px solid {ACCENT};
                    font-weight: bold;
                }}
            """)
            b.clicked.connect(lambda _, mode=m: self._set_cast_mode(mode))
            quick_mode_row.addWidget(b)
        ctrl_layout.addLayout(quick_mode_row)

        # 概览页快捷互动按钮行
        quick_act_row = QHBoxLayout()
        quick_act_row.setSpacing(6)
        for label, cb in (
            ("👋 摸头", lambda: self.pet_action.emit('touch')),
            ("💬 对话", self.chat_requested.emit),
            ("💰 余额", lambda: self.pet_action.emit('balance')),
            ("⛅ 天气", lambda: self.pet_action.emit('weather')),
        ):
            ab = QPushButton(label)
            ab.setFixedHeight(30)
            ab.setCursor(Qt.PointingHandCursor)
            ab.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(111, 227, 255, 0.09);
                    border: 1px solid rgba(111, 227, 255, 0.25);
                    color: {TEXT_PRIMARY};
                    border-radius: 7px;
                    font-size: 12px;
                    font-weight: 500;
                }}
                QPushButton:hover {{
                    background: rgba(111, 227, 255, 0.22);
                    color: {ACCENT};
                }}
            """)
            ab.clicked.connect(cb)
            quick_act_row.addWidget(ab)
        ctrl_layout.addLayout(quick_act_row)

        right_col.addWidget(ctrl_card)

        # 卡片 2：推流性能指标
        stats_card = _make_card()
        stats_layout = QGridLayout(stats_card)
        stats_layout.setContentsMargins(16, 14, 16, 14)
        stats_layout.setHorizontalSpacing(16)
        stats_layout.setVerticalSpacing(6)

        self._lbl_fps_val = QLabel("0.0 FPS")
        self._lbl_fps_val.setStyleSheet(f"font-size: 19px; font-weight: bold; color: {ACCENT};")
        self._lbl_fps_tip = QLabel("实时推流帧率")
        self._lbl_fps_tip.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")

        self._lbl_bw_val = QLabel("0.0 KB")
        self._lbl_bw_val.setStyleSheet(f"font-size: 19px; font-weight: bold; color: {TEXT_PRIMARY};")
        self._lbl_bw_tip = QLabel("单帧画面体积")
        self._lbl_bw_tip.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")

        self._lbl_pkt_val = QLabel("0 包/帧")
        self._lbl_pkt_val.setStyleSheet(f"font-size: 19px; font-weight: bold; color: {TEXT_PRIMARY};")
        self._lbl_pkt_tip = QLabel("HID 分包 (1025B)")
        self._lbl_pkt_tip.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")

        self._lbl_status_val = QLabel("等待数据")
        self._lbl_status_val.setStyleSheet("font-size: 15px; font-weight: bold; color: #8C95A3;")
        self._lbl_status_tip = QLabel("USB 管道状态")
        self._lbl_status_tip.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")

        stats_layout.addWidget(self._lbl_fps_val, 0, 0)
        stats_layout.addWidget(self._lbl_fps_tip, 1, 0)
        stats_layout.addWidget(self._lbl_bw_val, 0, 1)
        stats_layout.addWidget(self._lbl_bw_tip, 1, 1)
        stats_layout.addWidget(self._lbl_pkt_val, 2, 0)
        stats_layout.addWidget(self._lbl_pkt_tip, 3, 0)
        stats_layout.addWidget(self._lbl_status_val, 2, 1)
        stats_layout.addWidget(self._lbl_status_tip, 3, 1)

        right_col.addWidget(stats_card, 1)
        top_row.addLayout(right_col, 1)
        layout.addLayout(top_row)

        # 底部双端服务实时状态栏
        bottom_box = QFrame()
        bottom_box.setStyleSheet("""
            QFrame {
                background: rgba(22, 25, 32, 0.85);
                border-radius: 10px;
                border: 1px solid rgba(255,255,255,0.06);
            }
        """)
        b_lay = QHBoxLayout(bottom_box)
        b_lay.setContentsMargins(14, 8, 14, 8)
        b_lay.setSpacing(18)

        self._ov_coop_badge = QLabel("🐟 Coopanion (7797): 检测中…")
        self._ov_coop_badge.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        b_lay.addWidget(self._ov_coop_badge)

        self._ov_dsh_badge = QLabel("👧 DeepSeek dsh-pet: 检测中…")
        self._ov_dsh_badge.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        b_lay.addWidget(self._ov_dsh_badge)

        b_lay.addStretch()
        btn_go_cast = QPushButton("投放与引擎管理 ➔")
        btn_go_cast.setFixedHeight(24)
        btn_go_cast.setCursor(Qt.PointingHandCursor)
        btn_go_cast.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {ACCENT};
                font-size: 12px;
                border: none;
            }}
            QPushButton:hover {{ text-decoration: underline; }}
        """)
        btn_go_cast.clicked.connect(lambda: self._on_nav_selected(1))
        b_lay.addWidget(btn_go_cast)

        layout.addWidget(bottom_box)
        layout.addStretch()
        return page

    # ---------------------------------------------------------------- 页 1：投放布局
    def _make_page_cast(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

        # 1. 投放模式选择卡片
        mode_box = _make_card()
        mb_layout = QVBoxLayout(mode_box)
        mb_layout.setContentsMargins(18, 14, 18, 14)
        mb_layout.setSpacing(10)

        mb_title = QLabel("1. 选择水冷屏投放模式")
        mb_title.setStyleSheet(f"color: {ACCENT}; font-size: 13px; font-weight: bold;")
        mb_layout.addWidget(mb_title)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)

        self._btn_mode_coop = QPushButton("🐟 仅投放大肥鱼\nCoopanion 原生视口")
        self._btn_mode_dsh = QPushButton("👧 仅投放蓝毛女仆\nDeepSeek dsh-pet 全屏")
        self._btn_mode_dual = QPushButton("🌟 双桌宠同台投放\n大肥鱼 + 蓝毛女仆同屏")

        for btn in (self._btn_mode_coop, self._btn_mode_dsh, self._btn_mode_dual):
            btn.setFixedHeight(56)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
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

        # 2. 双宠同台分屏比例 & 悬浮球默认交互靶心
        self._dual_layout_box = _make_card()
        dl_layout = QVBoxLayout(self._dual_layout_box)
        dl_layout.setContentsMargins(18, 14, 18, 14)
        dl_layout.setSpacing(10)

        dl_title = QLabel("2. 双宠同台画面比例与默认交互目标")
        dl_title.setStyleSheet(f"color: {ACCENT}; font-size: 13px; font-weight: bold;")
        dl_layout.addWidget(dl_title)

        layout_row = QHBoxLayout()
        layout_row.setSpacing(8)

        self._btn_layout_side = QPushButton("左右并排 (50 : 50)")
        self._btn_layout_coop = QPushButton("大肥鱼主位 (65 : 35)")
        self._btn_layout_dsh  = QPushButton("蓝毛女仆主位 (35 : 65)")
        self._btn_layout_over = QPushButton("同台叠层 (Overlay)")

        for b in (self._btn_layout_side, self._btn_layout_coop, self._btn_layout_dsh, self._btn_layout_over):
            b.setFixedHeight(36)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.04);
                    color: {TEXT_PRIMARY};
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 8px;
                    font-size: 12px;
                }}
                QPushButton:hover {{ background: rgba(111, 227, 255, 0.08); }}
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

        target_row = QHBoxLayout()
        target_row.setContentsMargins(0, 4, 0, 0)
        target_row.setSpacing(18)
        target_lbl = QLabel("悬浮球当前交互对象:")
        target_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        target_row.addWidget(target_lbl)

        self._radio_target_coop = QRadioButton("🐟 控制大肥鱼 (摸头 / 语音 / 对话)")
        self._radio_target_dsh  = QRadioButton("👧 控制蓝毛小女仆 (摸头 / 114动作转盘 / 状态)")
        self._radio_target_coop.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        self._radio_target_dsh.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        self._radio_target_coop.toggled.connect(lambda c: c and self._set_control_target('coopanion'))
        self._radio_target_dsh.toggled.connect(lambda c: c and self._set_control_target('dsh'))
        target_row.addWidget(self._radio_target_coop)
        target_row.addWidget(self._radio_target_dsh)
        target_row.addStretch()
        dl_layout.addLayout(target_row)

        layout.addWidget(self._dual_layout_box)

        # 3. 桌宠后台服务状态与一键拉起
        svc_box = _make_card()
        sb_layout = QVBoxLayout(svc_box)
        sb_layout.setContentsMargins(18, 14, 18, 14)
        sb_layout.setSpacing(10)

        sb_title = QLabel("3. 桌宠引擎连接状态与快捷拉起")
        sb_title.setStyleSheet(f"color: {ACCENT}; font-size: 13px; font-weight: bold;")
        sb_layout.addWidget(sb_title)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)

        # 卡片 A: 大肥鱼
        card_coop = QFrame()
        card_coop.setStyleSheet("background: rgba(18, 22, 30, 0.75); border: 1px solid rgba(111, 227, 255, 0.18); border-radius: 10px;")
        cc_layout = QVBoxLayout(card_coop)
        cc_layout.setContentsMargins(14, 12, 14, 12)
        cc_layout.setSpacing(8)

        coop_head = QLabel("🐟 大肥鱼客户端 (Coopanion)")
        coop_head.setStyleSheet(f"color: {ACCENT}; font-size: 13px; font-weight: bold; border: none;")
        cc_layout.addWidget(coop_head)

        self._lbl_coop_status = QLabel("● 正在检测本地 7797 端口…")
        self._lbl_coop_status.setStyleSheet("color: #8C95A3; font-size: 12px; border: none;")
        cc_layout.addWidget(self._lbl_coop_status)

        self._btn_launch_coop = QPushButton("🚀 启动 / 唤醒 Coopanion")
        self._btn_launch_coop.setFixedHeight(30)
        self._btn_launch_coop.setCursor(Qt.PointingHandCursor)
        self._btn_launch_coop.setStyleSheet("""
            QPushButton {
                background: rgba(111, 227, 255, 0.12);
                color: #6FE3FF;
                border: 1px solid rgba(111, 227, 255, 0.30);
                border-radius: 7px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover { background: rgba(111, 227, 255, 0.24); }
        """)
        self._btn_launch_coop.clicked.connect(self._on_launch_coopanion)
        cc_layout.addWidget(self._btn_launch_coop)
        cards_row.addWidget(card_coop)

        # 卡片 B: 蓝毛女仆
        card_dsh = QFrame()
        card_dsh.setStyleSheet("background: rgba(18, 22, 30, 0.75); border: 1px solid rgba(96, 165, 250, 0.22); border-radius: 10px;")
        cd_layout = QVBoxLayout(card_dsh)
        cd_layout.setContentsMargins(14, 12, 14, 12)
        cd_layout.setSpacing(8)

        dsh_head = QLabel("👧 蓝毛小女仆 (DeepSeek Harness)")
        dsh_head.setStyleSheet("color: #60A5FA; font-size: 13px; font-weight: bold; border: none;")
        cd_layout.addWidget(dsh_head)

        self._lbl_dsh_status = QLabel("● 正在检测 DSH 状态总线…")
        self._lbl_dsh_status.setStyleSheet("color: #8C95A3; font-size: 12px; border: none;")
        cd_layout.addWidget(self._lbl_dsh_status)

        self._btn_launch_dsh = QPushButton("🚀 启动 / 重连 DeepSeek Harness")
        self._btn_launch_dsh.setFixedHeight(30)
        self._btn_launch_dsh.setCursor(Qt.PointingHandCursor)
        self._btn_launch_dsh.setStyleSheet("""
            QPushButton {
                background: rgba(96, 165, 250, 0.14);
                color: #93C5FD;
                border: 1px solid rgba(96, 165, 250, 0.35);
                border-radius: 7px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover { background: rgba(96, 165, 250, 0.26); }
        """)
        self._btn_launch_dsh.clicked.connect(self._on_launch_dsh)
        cd_layout.addWidget(self._btn_launch_dsh)
        cards_row.addWidget(card_dsh)

        sb_layout.addLayout(cards_row)
        layout.addWidget(svc_box)
        layout.addStretch()

        self._sync_cast_ui_state()
        return page

    def _set_cast_mode(self, mode: str):
        if not self.settings:
            return
        c_coop = mode in ('coopanion', 'dual')
        c_dsh = mode in ('dsh', 'dual')
        self.settings.update(cast_mode=mode, cast_coopanion=c_coop, cast_dsh=c_dsh)
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
        d_layout = s.get('dual_layout', 'side_by_side')
        c_target = s.get('control_target', 'coopanion')

        for b_coop, b_dsh, b_dual in (
            (getattr(self, '_btn_mode_coop', None), getattr(self, '_btn_mode_dsh', None), getattr(self, '_btn_mode_dual', None)),
            (getattr(self, '_ov_btn_coop', None), getattr(self, '_ov_btn_dsh', None), getattr(self, '_ov_btn_dual', None)),
        ):
            if b_coop and b_dsh and b_dual:
                b_coop.setChecked(mode == 'coopanion')
                b_dsh.setChecked(mode == 'dsh')
                b_dual.setChecked(mode == 'dual')

        if hasattr(self, '_dual_layout_box'):
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
        candidates = [
            Path(r"D:\Program Files\Coopanion\Coopanion.exe"),
            Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Coopanion' / 'Coopanion.exe',
        ]
        for p in candidates:
            if p.is_file():
                subprocess.Popen([str(p)], cwd=str(p.parent))
                QTimer.singleShot(1500, self._probe_services_async)
                return
        QMessageBox.information(self, "提示", "未找到 Coopanion.exe，请确认安装路径。")

    def _on_launch_dsh(self):
        # 1. 若 DSH 已在后台运行，立即重连端口并唤醒
        if self.dsh_client and self.dsh_client.connect():
            self._probe_services_async()
            return
        # 2. 否则尝试启动 DeepSeek Harness 客户端
        candidates = [
            Path(r"D:\Program Files\deepseek\DeepSeek Harness.exe"),
            Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'deepseek' / 'DeepSeek Harness.exe',
        ]
        for p in candidates:
            if p.is_file():
                subprocess.Popen([str(p)], cwd=str(p.parent))
                QTimer.singleShot(2500, self._probe_services_async)
                return
        try:
            from core.win32_guard import trigger_dsh_chat
            trigger_dsh_chat()
        except Exception:
            pass

    # ---------------------------------------------------------------- 页 2：桌宠工坊（3 大清晰子页）
    def _make_page_pet(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(20, 14, 20, 14)
        page_layout.setSpacing(10)

        # 顶部 3 段式二级导航条
        tab_row = QHBoxLayout()
        tab_row.setSpacing(8)

        self._btn_subtab_anim = QPushButton("🎬 动作与互动 (114款动作库)")
        self._btn_subtab_meme = QPushButton("💬 表情与气泡 (27款Meme配图)")
        self._btn_subtab_look = QPushButton("🎨 外观与背景 (双宠体型 · 舞台壁纸)")

        self._subtab_btns = [self._btn_subtab_anim, self._btn_subtab_meme, self._btn_subtab_look]
        for idx, btn in enumerate(self._subtab_btns):
            btn.setFixedHeight(34)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.05);
                    color: {TEXT_MUTED};
                    border: 1px solid rgba(255, 255, 255, 0.10);
                    border-radius: 8px;
                    font-size: 12px;
                    font-weight: 500;
                    padding: 0 12px;
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
            btn.clicked.connect(lambda _, i=idx: self._switch_pet_subtab(i))
            tab_row.addWidget(btn, 1)

        page_layout.addLayout(tab_row)

        self._pet_substack = QStackedWidget()
        self._pet_substack.setStyleSheet("background: transparent;")
        self._pet_substack.addWidget(self._make_subpage_actions())     # 0: 动作与互动
        self._pet_substack.addWidget(self._make_subpage_memes())       # 1: 表情与气泡
        self._pet_substack.addWidget(self._make_subpage_appearance())  # 2: 外观与背景

        page_layout.addWidget(self._pet_substack, 1)
        self._switch_pet_subtab(0)
        return page

    def _switch_pet_subtab(self, idx: int):
        for i, btn in enumerate(self._subtab_btns):
            btn.setChecked(i == idx)
        self._pet_substack.setCurrentIndex(idx)

    # ---------------- 子页 0：动作与互动 (全量 114 款动作 + 快捷交互)
    def _make_subpage_actions(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(10)

        # 1. 双宠快捷互动栏
        act_card = _make_card()
        act_lay = QVBoxLayout(act_card)
        act_lay.setContentsMargins(14, 10, 14, 10)
        act_lay.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(6)

        for text, cb, is_coop in (
            ("🐟 摸大肥鱼", self.coopanion_touch.emit, True),
            ("🎙️ 肥鱼语音", self.coopanion_voice.emit, True),
            ("👧 摸小女仆", lambda: self.pet_action.emit('touch'), False),
            ("💬 发送对话", self.chat_requested.emit, False),
            ("💰 查余额", lambda: self.pet_action.emit('balance'), False),
            ("⛅ 查天气", lambda: self.pet_action.emit('weather'), False),
            ("📋 查待办", lambda: self.pet_action.emit('todo'), False),
            ("💤 睡/醒", lambda: self.pet_action.emit('sleep_toggle'), False),
            ("💭 碎碎念", lambda: self.pet_action.emit('whisper'), False),
        ):
            b = QPushButton(text)
            b.setFixedHeight(30)
            b.setCursor(Qt.PointingHandCursor)
            c_rgb = "111, 227, 255" if is_coop else "96, 165, 250"
            b.setStyleSheet(f"""
                QPushButton {{
                    background: rgba({c_rgb}, 0.12);
                    border: 1px solid rgba({c_rgb}, 0.32);
                    color: {TEXT_PRIMARY};
                    border-radius: 7px;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 0 6px;
                }}
                QPushButton:hover {{
                    background: rgba({c_rgb}, 0.24);
                    color: #FFFFFF;
                }}
            """)
            b.clicked.connect(cb)
            row1.addWidget(b)

        act_lay.addLayout(row1)
        layout.addWidget(act_card)

        # 2. 全量 114 款 WebM 动作分类点播卡片
        anim_card = _make_card()
        anim_layout = QVBoxLayout(anim_card)
        anim_layout.setContentsMargins(14, 12, 14, 12)
        anim_layout.setSpacing(8)

        anim_header = QHBoxLayout()
        anim_title = QLabel("🎭 蓝毛女仆 114 款官方动作点播库")
        anim_title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: bold;")
        anim_header.addWidget(anim_title)
        anim_header.addStretch()
        self._lbl_anim_hint = QLabel("点击任意动作立即在水冷屏播放")
        self._lbl_anim_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        anim_header.addWidget(self._lbl_anim_hint)
        anim_layout.addLayout(anim_header)

        # 7 大官方分类 + 全部
        cat_row = QHBoxLayout()
        cat_row.setSpacing(4)
        self._cat_buttons: list[tuple[str, QPushButton]] = []

        cat_defs = [("all", "全部 114")] + [
            (k, f"{v['name']} {len(v['actions'])}") for k, v in ACTION_CATEGORIES.items()
        ]
        for idx, (cat_key, cat_label) in enumerate(cat_defs):
            btn_cat = QPushButton(cat_label)
            btn_cat.setCheckable(True)
            btn_cat.setChecked(idx == 1)  # 默认展示第一分类，秒开清爽
            btn_cat.setFixedHeight(26)
            btn_cat.setCursor(Qt.PointingHandCursor)
            btn_cat.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.06);
                    border: 1px solid rgba(255, 255, 255, 0.10);
                    color: #8E98A8;
                    border-radius: 6px;
                    font-size: 11px;
                    padding: 0 6px;
                }
                QPushButton:hover { color: #FFFFFF; background: rgba(255, 255, 255, 0.12); }
                QPushButton:checked {
                    background: rgba(111, 227, 255, 0.20);
                    border-color: #6FE3FF;
                    color: #6FE3FF;
                    font-weight: bold;
                }
            """)
            btn_cat.clicked.connect(lambda _, ck=cat_key: self._filter_anim_category(ck))
            cat_row.addWidget(btn_cat)
            self._cat_buttons.append((cat_key, btn_cat))
        cat_row.addStretch()
        anim_layout.addLayout(cat_row)

        # 动作网格滚动区
        anim_scroll = QScrollArea()
        anim_scroll.setWidgetResizable(True)
        anim_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._anim_grid_widget = QWidget()
        self._anim_grid = QGridLayout(self._anim_grid_widget)
        self._anim_grid.setContentsMargins(0, 4, 4, 4)
        self._anim_grid.setSpacing(7)
        anim_scroll.setWidget(self._anim_grid_widget)

        anim_layout.addWidget(anim_scroll, 1)
        layout.addWidget(anim_card, 1)

        self._populate_anim_grid("cat_food")
        return page

    # ---------------- 子页 1：表情与气泡 (27 款 Meme 3 列宽敞网格 + 气泡缩放)
    def _make_subpage_memes(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(10)

        # 1. 顶部气泡大小控制栏
        bubble_card = _make_card()
        b_lay = QHBoxLayout(bubble_card)
        b_lay.setContentsMargins(16, 10, 16, 10)
        b_lay.setSpacing(12)

        lbl_b_tag = QLabel("💬 水冷屏台词气泡缩放:")
        lbl_b_tag.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
        b_lay.addWidget(lbl_b_tag)

        self._slider_bubble = QSlider(Qt.Horizontal)
        self._slider_bubble.setRange(80, 200)
        self._slider_bubble.setValue(100)
        self._slider_bubble.valueChanged.connect(self._on_transform_slider_changed)
        b_lay.addWidget(self._slider_bubble, 1)

        self._lbl_bubble_num = QLabel("100%")
        self._lbl_bubble_num.setFixedWidth(44)
        self._lbl_bubble_num.setStyleSheet(f"color: {ACCENT}; font-size: 12px; font-weight: bold;")
        b_lay.addWidget(self._lbl_bubble_num)

        self._btn_test_bubble = QPushButton("💬 试看气泡")
        self._btn_test_bubble.setFixedHeight(26)
        self._btn_test_bubble.setCursor(Qt.PointingHandCursor)
        self._btn_test_bubble.setStyleSheet(f"""
            QPushButton {{
                background: rgba(111, 227, 255, 0.14);
                border: 1px solid rgba(111, 227, 255, 0.35);
                color: {ACCENT};
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
                padding: 0 10px;
            }}
            QPushButton:hover {{ background: rgba(111, 227, 255, 0.25); }}
        """)
        self._btn_test_bubble.clicked.connect(self._on_test_bubble_preview)
        b_lay.addWidget(self._btn_test_bubble)

        layout.addWidget(bubble_card)

        # 2. 27 款表情包配图画廊（3 列宽幅按钮，完整显示长标题）
        meme_card = _make_card()
        meme_outer = QVBoxLayout(meme_card)
        meme_outer.setContentsMargins(16, 12, 16, 12)
        meme_outer.setSpacing(8)

        meme_title = QLabel("🖼️ 27 款官方 Meme 表情包点播（点击即在水冷屏弹出对应图文气泡）")
        meme_title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: bold;")
        meme_outer.addWidget(meme_title)

        meme_scroll = QScrollArea()
        meme_scroll.setWidgetResizable(True)
        meme_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        meme_content = QWidget()
        mc_lay = QVBoxLayout(meme_content)
        mc_lay.setContentsMargins(0, 2, 6, 4)
        mc_lay.setSpacing(8)

        grid_all = QGridLayout()
        grid_all.setSpacing(8)
        self._populate_meme_grid(grid_all, MEMES_DIALOG + MEMES_OTHER, cols=3)
        mc_lay.addLayout(grid_all)
        mc_lay.addStretch()

        meme_scroll.setWidget(meme_content)
        meme_outer.addWidget(meme_scroll, 1)
        layout.addWidget(meme_card, 1)
        return page

    # ---------------- 子页 2：外观与背景 (双宠体型微调 + 舞台背景画廊)
    def _make_subpage_appearance(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 6, 10)
        layout.setSpacing(12)

        # 1. 双宠体型与位置微调合一卡片
        transform_card = _make_card()
        t_layout = QVBoxLayout(transform_card)
        t_layout.setContentsMargins(16, 12, 16, 12)
        t_layout.setSpacing(8)

        t_header = QHBoxLayout()
        t_title = QLabel("📐 水冷屏双宠体型与位置微调")
        t_title.setStyleSheet(f"color: {ACCENT}; font-size: 13px; font-weight: bold;")
        t_header.addWidget(t_title)
        t_header.addStretch()

        self._btn_reset_transform = QPushButton("↺ 恢复默认体型与位置")
        self._btn_reset_transform.setFixedHeight(24)
        self._btn_reset_transform.setCursor(Qt.PointingHandCursor)
        self._btn_reset_transform.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
                color: #CBD5E1;
                border-radius: 6px;
                font-size: 11px;
                padding: 0 10px;
            }
            QPushButton:hover { background: rgba(255, 255, 255, 0.16); color: #FFFFFF; }
        """)
        self._btn_reset_transform.clicked.connect(self._on_reset_transform)
        t_header.addWidget(self._btn_reset_transform)
        t_layout.addLayout(t_header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)

        # 大肥鱼 DPR 缩放
        init_scale = getattr(self.settings, 'coopanion_scale', 1.6) if self.settings else 1.6
        lbl_coop_s = QLabel("🐟 大肥鱼视口倍率:")
        lbl_coop_s.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        self._slider_coop_scale = QSlider(Qt.Horizontal)
        self._slider_coop_scale.setRange(0, len(SCALES) - 1)
        try:
            cur_idx = SCALES.index(init_scale)
        except ValueError:
            cur_idx = 2
        self._slider_coop_scale.setValue(cur_idx)
        self._lbl_coop_scale_val = QLabel(f"{init_scale}×")
        self._lbl_coop_scale_val.setFixedWidth(54)
        self._lbl_coop_scale_val.setStyleSheet(f"color: {ACCENT}; font-size: 12px; font-weight: bold;")
        grid.addWidget(lbl_coop_s, 0, 0)
        grid.addWidget(self._slider_coop_scale, 0, 1)
        grid.addWidget(self._lbl_coop_scale_val, 0, 2)

        # 蓝毛女仆体型缩放
        lbl_s_tag = QLabel("👧 蓝毛女仆缩放:")
        lbl_s_tag.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        self._slider_scale = QSlider(Qt.Horizontal)
        self._slider_scale.setRange(50, 150)
        self._slider_scale.setValue(100)
        self._lbl_scale_num = QLabel("100%")
        self._lbl_scale_num.setFixedWidth(54)
        self._lbl_scale_num.setStyleSheet(f"color: {ACCENT}; font-size: 12px; font-weight: bold;")
        grid.addWidget(lbl_s_tag, 1, 0)
        grid.addWidget(self._slider_scale, 1, 1)
        grid.addWidget(self._lbl_scale_num, 1, 2)

        # 蓝毛女仆水平偏移
        lbl_x_tag = QLabel("↔ 女仆水平偏移:")
        lbl_x_tag.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        self._slider_pos_x = QSlider(Qt.Horizontal)
        self._slider_pos_x.setRange(-150, 150)
        self._slider_pos_x.setValue(0)
        self._lbl_pos_x_num = QLabel("0 px")
        self._lbl_pos_x_num.setFixedWidth(54)
        self._lbl_pos_x_num.setStyleSheet(f"color: {ACCENT}; font-size: 12px; font-weight: bold;")
        grid.addWidget(lbl_x_tag, 2, 0)
        grid.addWidget(self._slider_pos_x, 2, 1)
        grid.addWidget(self._lbl_pos_x_num, 2, 2)

        # 蓝毛女仆垂直偏移
        lbl_y_tag = QLabel("↕ 女仆垂直偏移:")
        lbl_y_tag.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        self._slider_pos_y = QSlider(Qt.Horizontal)
        self._slider_pos_y.setRange(-150, 150)
        self._slider_pos_y.setValue(0)
        self._lbl_pos_y_num = QLabel("0 px")
        self._lbl_pos_y_num.setFixedWidth(54)
        self._lbl_pos_y_num.setStyleSheet(f"color: {ACCENT}; font-size: 12px; font-weight: bold;")
        grid.addWidget(lbl_y_tag, 3, 0)
        grid.addWidget(self._slider_pos_y, 3, 1)
        grid.addWidget(self._lbl_pos_y_num, 3, 2)

        t_layout.addLayout(grid)

        self._slider_coop_scale.valueChanged.connect(self._on_coop_scale_slider_changed)
        self._slider_scale.valueChanged.connect(self._on_transform_slider_changed)
        self._slider_pos_x.valueChanged.connect(self._on_transform_slider_changed)
        self._slider_pos_y.valueChanged.connect(self._on_transform_slider_changed)

        layout.addWidget(transform_card)

        # 2. 舞台通用背景画廊卡片
        layout.addWidget(self._make_background_card())

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def _on_coop_scale_slider_changed(self, idx: int):
        if 0 <= idx < len(SCALES):
            val = SCALES[idx]
            self._lbl_coop_scale_val.setText(f"{val}×")
            if self.settings:
                self.settings.update(coopanion_scale=val)
            self.coopanion_scale_changed.emit(val)

    def _make_background_card(self) -> QWidget:
        """舞台预设背景质感画廊卡片（全模式通用）"""
        bg_card = _make_card()
        bg_layout = QVBoxLayout(bg_card)
        bg_layout.setContentsMargins(16, 12, 16, 12)
        bg_layout.setSpacing(10)

        bg_header = QHBoxLayout()
        bg_title = QLabel("🖼️ 舞台背景画廊（640×480 通用壁纸）")
        bg_title.setStyleSheet(f"color: {ACCENT}; font-size: 13px; font-weight: bold;")
        bg_header.addWidget(bg_title)
        bg_header.addStretch()

        btn_pick_img = QPushButton("📁 自定义图片…")
        btn_pick_color = QPushButton("🎨 纯色背景…")
        btn_reset_bg = QPushButton("↺ 默认点阵")
        for b in (btn_pick_img, btn_pick_color, btn_reset_bg):
            b.setFixedHeight(26)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("""
                QPushButton {
                    background: rgba(255,255,255,0.08);
                    color: #F0F3F8;
                    border: 1px solid rgba(255,255,255,0.12);
                    border-radius: 6px;
                    padding: 0 10px;
                    font-size: 11px;
                }
                QPushButton:hover { background: rgba(111,227,255,0.20); color: #6FE3FF; }
            """)
            bg_header.addWidget(b)

        btn_pick_img.clicked.connect(self._on_choose_custom_image)
        btn_pick_color.clicked.connect(self._on_choose_custom_color)
        btn_reset_bg.clicked.connect(lambda: self._apply_preset_bg('dots', ''))
        bg_layout.addLayout(bg_header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        assets_bg_dir = Path(__file__).resolve().parent.parent / 'assets' / 'backgrounds'

        for idx, (b_key, b_name, b_file, b_desc) in enumerate(PRESET_BACKGROUNDS):
            cell = QFrame()
            cell.setStyleSheet("""
                QFrame {
                    background: rgba(32, 36, 46, 0.85);
                    border: 1px solid rgba(255,255,255,0.08);
                    border-radius: 8px;
                }
                QFrame:hover { border-color: rgba(111,227,255,0.40); }
            """)
            c_lay = QHBoxLayout(cell)
            c_lay.setContentsMargins(8, 6, 8, 6)
            c_lay.setSpacing(8)

            thumb = QLabel()
            thumb.setFixedSize(64, 48)
            img_path = assets_bg_dir / b_file
            if img_path.is_file():
                px = QPixmap(str(img_path)).scaled(64, 48, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                thumb.setPixmap(px)
            thumb.setStyleSheet("border-radius: 4px; background: #000; border: none;")
            c_lay.addWidget(thumb)

            info_col = QVBoxLayout()
            info_col.setSpacing(2)
            name_lbl = QLabel(b_name)
            name_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold; border: none;")
            desc_lbl = QLabel(b_desc)
            desc_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; border: none;")
            info_col.addWidget(name_lbl)
            info_col.addWidget(desc_lbl)
            c_lay.addLayout(info_col, 1)

            btn_apply = QPushButton("应用")
            btn_apply.setFixedSize(46, 26)
            btn_apply.setCursor(Qt.PointingHandCursor)
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
        return bg_card

    # ---------------------------------------------------------------- 页 3：固件与硬件
    def _make_page_firmware(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 16, 22, 16)
        layout.setSpacing(12)

        # 1. Flash 固件刷写区
        fw_card = _make_card()
        fw_lay = QVBoxLayout(fw_card)
        fw_lay.setContentsMargins(18, 14, 18, 14)
        fw_lay.setSpacing(10)

        title = QLabel("⚡ TCOMAS LG700 冷头 Flash 固件资产刷写（断电待机壁纸 & 开机动画）")
        title.setStyleSheet(f"color: {ACCENT}; font-size: 13px; font-weight: bold;")
        fw_lay.addWidget(title)

        self._flash_widget = FlashWidget(parent=self)
        self._wire_flash_widget()
        fw_lay.addWidget(self._flash_widget)
        layout.addWidget(fw_card)

        # 2. USB 复合总线状态与重置卡片
        diag_card = _make_card()
        d_lay = QHBoxLayout(diag_card)
        d_lay.setContentsMargins(18, 12, 18, 12)
        d_lay.setSpacing(16)

        info_text = QLabel(
            "🩺 <b>硬件总线信息</b>：TCOMAS LG700 (VID: 0x1A2C / PID: 0x151C)  ·  "
            "控制口 MI_00 (0xFF06:01)  ·  数据口 MI_01 (0xFF06:02 DirectIO)"
        )
        info_text.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        d_lay.addWidget(info_text, 1)

        btn_reconnect = QPushButton("🔄 重置 USB 推流总线")
        btn_reconnect.setFixedHeight(30)
        btn_reconnect.setCursor(Qt.PointingHandCursor)
        btn_reconnect.setStyleSheet("""
            QPushButton {
                background: rgba(111,227,255,0.14);
                color: #6FE3FF;
                border: 1px solid rgba(111,227,255,0.35);
                border-radius: 8px;
                padding: 0 14px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover { background: rgba(111,227,255,0.25); }
        """)
        btn_reconnect.clicked.connect(self._on_reconnect_bus)
        d_lay.addWidget(btn_reconnect)

        layout.addWidget(diag_card)
        layout.addStretch()
        return page

    def _wire_flash_widget(self):
        self._flash_widget.wallpaper_change_requested.connect(self._on_change_wallpaper)
        self._flash_widget.animation_change_requested.connect(self._on_change_animation)
        self._flash_widget.wallpaper_reset_requested.connect(self._on_reset_flash)
        self._flash_widget.animation_reset_requested.connect(self._on_reset_flash)

    # ---------------------------------------------------------------- 页 4：偏好设置
    def _make_page_settings(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

        s_card = _make_card()
        s_lay = QVBoxLayout(s_card)
        s_lay.setContentsMargins(20, 16, 20, 16)
        s_lay.setSpacing(14)

        title = QLabel("⚙️ 系统与悬浮球行为设置")
        title.setStyleSheet(f"color: {ACCENT}; font-size: 13px; font-weight: bold;")
        s_lay.addWidget(title)

        self._chk_autostart = QCheckBox("开机自动启动大肥鱼桌宠钛坦屏投放工具（后台自动推流水冷屏）")
        self._chk_autostart.setChecked(is_autostart_enabled())
        self._chk_autostart.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        self._chk_autostart.toggled.connect(self._on_toggle_autostart)
        s_lay.addWidget(self._chk_autostart)

        self._chk_close_tray = QCheckBox("关闭控制中心窗口时隐藏到系统托盘（不退出程序，保持水冷屏运作）")
        self._chk_close_tray.setChecked(True)
        self._chk_close_tray.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        s_lay.addWidget(self._chk_close_tray)

        self._chk_ball_snap = QCheckBox("桌面悬浮球靠近屏幕边缘时自动磁吸贴边")
        self._chk_ball_snap.setChecked(True)
        self._chk_ball_snap.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        self._chk_ball_snap.toggled.connect(self._on_toggle_ball_snap)
        s_lay.addWidget(self._chk_ball_snap)

        self._chk_ball_peek = QCheckBox("桌面悬浮球闲置时平滑半隐入屏幕边缘（悬停即刻滑出）")
        self._chk_ball_peek.setChecked(True)
        self._chk_ball_peek.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        self._chk_ball_peek.toggled.connect(self._on_toggle_ball_peek)
        s_lay.addWidget(self._chk_ball_peek)

        layout.addWidget(s_card)

        tool_row = QHBoxLayout()
        tool_row.setSpacing(10)

        btn_open_appdata = QPushButton("📂 打开配置与日志目录")
        btn_open_appdata.setCursor(Qt.PointingHandCursor)
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

        btn_clear_cache = QPushButton("🧹 清理运行缓存与旧日志")
        btn_clear_cache.setCursor(Qt.PointingHandCursor)
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

        btn_reset_cfg = QPushButton("↺ 恢复所有默认设置")
        btn_reset_cfg.setCursor(Qt.PointingHandCursor)
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
    # 窗口拖拽
    # ================================================================

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            local_pos = self.mapFromGlobal(event.globalPosition().toPoint())
            if local_pos.y() <= 48:
                wh = self.windowHandle()
                if wh and hasattr(wh, 'startSystemMove') and wh.startSystemMove():
                    event.accept()
                    return
                self._dragging_header = True
                self._drag_offset = event.globalPosition().toPoint() - self.pos()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
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
        self._dragging_header = False
        super().changeEvent(event)

    def leaveEvent(self, event):
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
        coop_sc = getattr(self.settings, 'coopanion_scale', 1.6)
        try:
            c_idx = SCALES.index(coop_sc)
            if hasattr(self, '_slider_coop_scale'):
                self._slider_coop_scale.blockSignals(True)
                self._slider_coop_scale.setValue(c_idx)
                self._slider_coop_scale.blockSignals(False)
            if hasattr(self, '_lbl_coop_scale_val'):
                self._lbl_coop_scale_val.setText(f"{coop_sc}×")
        except ValueError:
            pass
        if hasattr(self, '_chk_display_mode'):
            is_screen_mode = bool(pushing and getattr(self.settings, 'hide_desktop_pet', True))
            self._chk_display_mode.blockSignals(True)
            self._chk_display_mode.setChecked(is_screen_mode)
            self._chk_display_mode.blockSignals(False)
        if hasattr(self, '_chk_ball_snap'):
            self._chk_ball_snap.blockSignals(True)
            self._chk_ball_snap.setChecked(getattr(self.settings, 'ball_snap', True))
            self._chk_ball_snap.blockSignals(False)
        if hasattr(self, '_chk_ball_peek'):
            self._chk_ball_peek.blockSignals(True)
            self._chk_ball_peek.setChecked(getattr(self.settings, 'ball_peek', True))
            self._chk_ball_peek.blockSignals(False)
        self._sync_cast_ui_state()

    def _probe_services_async(self):
        """后台非阻塞探测 Coopanion 7797 与 DSH 状态端口。"""
        import threading
        def _job():
            self._coop_online = _is_port_open(7797)
            if self.dsh_client:
                self._dsh_online = self.dsh_client.is_connected
                self._dsh_port = self.dsh_client.port or 0
        threading.Thread(target=_job, daemon=True).start()

    def _on_timer_tick(self):
        fps = self._status.get('fps', 0.0)
        kb = self._status.get('kb', 0.0)
        pkt = self._status.get('pkt', 0)
        ok = self._status.get('ok', False)
        msg = self._status.get('msg', '等待设备')

        self._lbl_fps_val.setText(f"{fps:.1f} FPS")
        self._lbl_bw_val.setText(f"{kb:.1f} KB")
        self._lbl_pkt_val.setText(f"{pkt} 包/帧")
        self._lbl_status_val.setText(msg)

        # 每 3 秒后台刷新一次双桌宠引擎在线状态
        self._probe_tick += 1
        if self._probe_tick >= 6:
            self._probe_tick = 0
            self._probe_services_async()

        # 更新双宠在线状态徽标
        if self._coop_online:
            coop_txt = "● Coopanion (7797): 在线"
            coop_col = "#10B981"
        else:
            coop_txt = "○ Coopanion (7797): 未启动"
            coop_col = "#8C95A3"
        self._lbl_coop_status.setText(coop_txt)
        self._lbl_coop_status.setStyleSheet(f"color: {coop_col}; font-size: 12px; border: none;")
        self._ov_coop_badge.setText(f"🐟 {coop_txt}")
        self._ov_coop_badge.setStyleSheet(f"color: {coop_col}; font-size: 12px;")

        if self._dsh_online and self._dsh_port:
            dsh_txt = f"● DeepSeek dsh-pet: 已连接 (:{self._dsh_port})"
            dsh_col = "#10B981"
        else:
            dsh_txt = "○ DeepSeek dsh-pet: 未连接"
            dsh_col = "#8C95A3"
        self._lbl_dsh_status.setText(dsh_txt)
        self._lbl_dsh_status.setStyleSheet(f"color: {dsh_col}; font-size: 12px; border: none;")
        self._ov_dsh_badge.setText(f"👧 {dsh_txt}")
        self._ov_dsh_badge.setStyleSheet(f"color: {dsh_col}; font-size: 12px;")

        if ok:
            self._status_badge.setText(f"● LG700 已连接 ({fps:.1f} FPS)")
        else:
            self._status_badge.setText("○ 等待水冷屏连接")

        if not hasattr(self, '_last_ok_status') or self._last_ok_status != ok:
            self._last_ok_status = ok
            if ok:
                self._lbl_status_val.setStyleSheet("font-size: 15px; font-weight: bold; color: #6FE3FF;")
                self._status_badge.setStyleSheet("""
                    color: #6FE3FF;
                    font-size: 12px;
                    padding: 4px 12px;
                    border-radius: 12px;
                    background: rgba(111, 227, 255, 0.12);
                    border: 1px solid rgba(111, 227, 255, 0.25);
                """)
            else:
                self._lbl_status_val.setStyleSheet("font-size: 15px; font-weight: bold; color: #FF5B5B;")
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
        if self.isVisible() and self._stack.currentIndex() == 0:
            self._overview_preview.update_frame(jpeg_bytes)

    def _on_toggle_display_mode(self, checked: bool):
        if self.settings:
            self.settings.update(pushing=checked, hide_desktop_pet=checked)
        self.stream_toggled.emit(checked)

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
        pct = self._slider_bubble.value() if hasattr(self, '_slider_bubble') else 100
        msg = f"气泡缩放 {pct}% 预览：主人能看清我说话吗？"
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
        if hasattr(self, '_slider_coop_scale'):
            default_idx = SCALES.index(1.6) if 1.6 in SCALES else 2
            self._slider_coop_scale.setValue(default_idx)
        self._slider_scale.setValue(100)
        self._slider_pos_x.setValue(0)
        self._slider_pos_y.setValue(0)
        self._slider_scale.blockSignals(False)
        self._slider_pos_x.blockSignals(False)
        self._slider_pos_y.blockSignals(False)
        self._on_transform_slider_changed()

    def _filter_anim_category(self, cat_key: str):
        for ck, btn in self._cat_buttons:
            btn.setChecked(ck == cat_key)
        self._populate_anim_grid(cat_key)

    def _populate_anim_grid(self, cat_key: str):
        while self._anim_grid.count():
            item = self._anim_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if cat_key == "all":
            all_actions = []
            for cat in ACTION_CATEGORIES.values():
                for a in cat['actions']:
                    if a not in all_actions:
                        all_actions.append(a)
            items = all_actions
        else:
            items = ACTION_CATEGORIES.get(cat_key, {}).get('actions', [])

        cols = 4
        for idx, name in enumerate(items):
            btn = QPushButton(name)
            btn.setFixedHeight(28)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(f"点播动作: {name}")
            btn.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.05);
                    border: 1px solid rgba(255, 255, 255, 0.09);
                    color: #CBD5E1;
                    border-radius: 6px;
                    font-size: 11px;
                    padding: 0 6px;
                }
                QPushButton:hover {
                    background: rgba(111, 227, 255, 0.18);
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
        self._lbl_anim_hint.setText(f"✓ 已点播: {anim_name}")
        self._lbl_anim_hint.setStyleSheet("color: #6FE3FF; font-size: 11px;")
        self.anim_requested.emit(anim_name)

    def _populate_meme_grid(self, grid: QGridLayout, memes_list: list[str], cols: int = 3):
        memes_dir = Path(__file__).resolve().parent.parent / 'assets' / 'memes'
        for idx, meme_name in enumerate(memes_list):
            btn = QPushButton()
            btn.setFixedHeight(36)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(f"在水冷屏展示配图: {meme_name}")

            btn_layout = QHBoxLayout(btn)
            btn_layout.setContentsMargins(8, 2, 8, 2)
            btn_layout.setSpacing(8)

            icon_lbl = QLabel()
            icon_lbl.setFixedSize(26, 26)
            icon_lbl.setScaledContents(True)
            img_path = memes_dir / f"{meme_name}.png"
            if img_path.is_file():
                icon_lbl.setPixmap(QPixmap(str(img_path)))
            btn_layout.addWidget(icon_lbl)

            txt_lbl = QLabel(meme_name)
            txt_lbl.setStyleSheet("color: #E2E8F0; font-size: 12px; border: none; background: transparent;")
            btn_layout.addWidget(txt_lbl, 1)

            btn.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.05);
                    border: 1px solid rgba(255, 255, 255, 0.09);
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background: rgba(111, 227, 255, 0.16);
                    border-color: #6FE3FF;
                }
            """)
            btn.clicked.connect(lambda _, m=meme_name: self.meme_requested.emit(m))
            grid.addWidget(btn, idx // cols, idx % cols)

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

    def _on_reload_page(self):
        if self.renderer:
            self.renderer.send_command('reload')

    def _on_reconnect_bus(self):
        if self.pusher:
            log.info("用户请求手动重置 USB 推流总线...")
            self.pusher.pause()
            QTimer.singleShot(500, self.pusher.resume)

    def _on_toggle_autostart(self, checked: bool):
        ok = set_autostart(checked)
        if not ok:
            QMessageBox.warning(self, "设置失败", "修改 Windows 开机自启注册表项失败，请检查系统权限。")
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
        p.mkdir(parents=True, exist_ok=True)
        os.startfile(str(p))

    def _on_clear_cache(self):
        freed_bytes = 0
        try:
            temp_dir = Path(tempfile.gettempdir())
            for pat in ('tcomas_*', 'bigfish_*', 'playwright_*', 'tmp*tcomas*', 'lg700_convert_*'):
                for p in temp_dir.glob(pat):
                    try:
                        if p.is_file():
                            freed_bytes += p.stat().st_size
                            p.unlink(missing_ok=True)
                        elif p.is_dir():
                            for sub in p.rglob('*'):
                                if sub.is_file():
                                    freed_bytes += sub.stat().st_size
                            shutil.rmtree(p, ignore_errors=True)
                    except Exception:
                        pass

            appdata_log = Path(os.environ.get('APPDATA', '')) / 'BigFishTitanConsole'
            if appdata_log.is_dir():
                for lf in appdata_log.glob('*.log*'):
                    try:
                        sz = lf.stat().st_size
                        if sz > 256 * 1024:
                            freed_bytes += sz
                            with open(lf, 'w', encoding='utf-8') as f:
                                f.write('')
                    except Exception:
                        pass
        except Exception as e:
            log.warning('清理缓存异常: %s', e)

        freed_mb = freed_bytes / (1024.0 * 1024.0)
        QMessageBox.information(
            self,
            "清理完成",
            f"✅ 缓存与冗余日志清理完毕，共释放 {freed_mb:.2f} MB 空间。"
        )

    def _on_reset_config(self):
        res = QMessageBox.question(
            self, "确认重置", "确定要将所有设置恢复为出厂默认值吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if res == QMessageBox.Yes:
            if self.settings:
                self.settings.update(
                    cast_mode='dual',
                    cast_coopanion=True,
                    cast_dsh=True,
                    dual_layout='side_by_side',
                    control_target='coopanion',
                    coopanion_scale=1.6,
                    scale=1.0,
                    offset_x=0,
                    offset_y=0,
                    bubble_scale=1.0,
                    bg_mode='dots',
                    bg_value='#0D1117',
                    pushing=True,
                    hide_desktop_pet=True,
                    ball_snap=True,
                    ball_peek=True
                )
                self._sync_settings()
                self._on_reset_transform()

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
