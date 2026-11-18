# -*- coding: utf-8 -*-
"""panel.py — 控制面板主窗口（340×460，完整 7 区块 + 冷头固件管理子页）。

PanelWindow:
  - 深灰磨砂质感，340×460px，无边框透明背景
  - 双模式分页切换：
      页 0：桌宠控制台（标题栏、160×120实时预览、体型滑块、背景选择、互动按钮、开关、状态栏）
      页 1：屏幕固件管理（待机壁纸更换/恢复出厂、开机动画更换/恢复出厂、刷写进度条）
  - 整窗口可拖动（标题栏区域）
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QCheckBox, QColorDialog,
    QFileDialog, QSizePolicy, QFrame, QSpacerItem,
    QStackedWidget, QMessageBox
)
from PySide6.QtCore import (
    Qt, QTimer, QPointF, QRectF, Signal, QPoint
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath,
    QFont, QPixmap
)

from .tokens import (
    SURFACE, SURFACE_HOVER, SURFACE_ACTIVE,
    BORDER, ACCENT, TEXT_PRIMARY, TEXT_MUTED, TEXT_ACCENT,
    DANGER, ICON_DEFAULT,
    PANEL_W, PANEL_H, RADIUS, SCALES,
    build_qss
)
from .preview import PreviewWidget
from .icons import draw_icon
from .flash_widget import FlashWidget

log = logging.getLogger('tcomas.ui.panel')


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


# ——— 自定义子控件 ———

class _SectionLabel(QLabel):
    """小标题：TEXT_MUTED, 11px, 大写字母间距"""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        font = QFont("Microsoft YaHei UI", 10)
        self.setFont(font)
        self.setStyleSheet(f"color: {TEXT_MUTED}; letter-spacing: 1px;")


class _IconButton(QPushButton):
    """圆形图标按钮（38×38），QPainter 绘制图标"""

    def __init__(self, icon_key: str, tooltip: str, parent=None):
        super().__init__(parent)
        self._icon_key = icon_key
        self.setFixedSize(38, 38)
        self.setToolTip(tooltip)
        self.setStyleSheet(f"""
            QPushButton {{
                background: rgba(38,41,50,0.85);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 19px;
            }}
            QPushButton:hover {{
                background: rgba(55,58,68,0.95);
                border-color: rgba(111,227,255,0.35);
            }}
            QPushButton:pressed {{
                background: rgba(70,74,86,0.98);
            }}
            QPushButton:disabled {{
                background: rgba(28,30,36,0.60);
                border-color: rgba(255,255,255,0.05);
            }}
        """)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        color = (QColor(140, 149, 163, 180) if not self.isEnabled()
                 else QColor(255, 255, 255, 220))
        draw_icon(painter, self._icon_key, cx, cy, 20, color)
        painter.end()


class _CapsuleButton(QPushButton):
    """胶囊形可选按钮"""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setFixedHeight(28)
        self.setStyleSheet(f"""
            QPushButton {{
                background: rgba(38,41,50,0.80);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 14px;
                color: {TEXT_MUTED};
                font-size: 12px;
                padding: 0 10px;
            }}
            QPushButton:hover {{
                background: rgba(55,58,68,0.95);
                color: {TEXT_PRIMARY};
                border-color: rgba(255,255,255,0.18);
            }}
            QPushButton:checked {{
                background: rgba(111,227,255,0.14);
                border: 1px solid rgba(111,227,255,0.45);
                color: {ACCENT};
            }}
            QPushButton:disabled {{
                color: rgba(140,149,163,0.40);
                border-color: rgba(255,255,255,0.04);
            }}
        """)


# ================================================================
# PanelWindow
# ================================================================

class PanelWindow(QWidget):
    """深灰磨砂质感的桌宠控制台，340×460px。

    Signals（由主 App 外部连接）:
        scale_changed(float):   体型滑块值改变
        background_changed(str, any): 背景模式改变 ('dot'/'solid'/'image'/'daily', value)
        pet_action(str):        互动动作 ('touch')
        stream_toggled(bool):   推流开关
        hide_pet_toggled(bool): 隐藏桌宠开关
        close_requested():      用户点击关闭按钮
    """

    scale_changed      = Signal(float)
    background_changed = Signal(str, object)
    pet_action         = Signal(str)
    stream_toggled     = Signal(bool)
    hide_pet_toggled   = Signal(bool)
    close_requested    = Signal()
    open_dashboard_requested = Signal()

    def __init__(self, settings=None, renderer=None, flash_bridge=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.renderer = renderer
        self.flash_bridge = flash_bridge

        # ——— 窗口属性 ———
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(PANEL_W, PANEL_H)
        self.setStyleSheet(build_qss())

        # 拖拽相关
        self._drag_offset = QPoint()
        self._dragging_header = False

        # ——— 构建 UI ———
        self._build_ui()

        # ——— 状态栏刷新定时器 ———
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(500)
        self._status_timer.timeout.connect(self._refresh_status_bar)
        self._status_timer.start()

        # 状态数据
        self._status = dict(fps=0.0, kb=0.0, pkt=0, ok=False, msg="初始化中")

        # 同步初始设置
        self._sync_from_settings()

    # ================================================================
    # UI 构建
    # ================================================================

    def _build_ui(self):
        """构建标题栏 + QStackedWidget 分页（控制台 / 屏幕固件）"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 12, 18, 12)
        outer.setSpacing(8)

        # ① 顶部标题栏（含分页 Pill 切换按钮）
        outer.addLayout(self._make_header())

        # ② 分页堆叠区
        self._stack = QStackedWidget(self)

        # 页面 0：桌宠控制台
        self._console_widget = QWidget(self)
        console_layout = QVBoxLayout(self._console_widget)
        console_layout.setContentsMargins(0, 0, 0, 0)
        console_layout.setSpacing(8)

        # 实时预览（居中显示）
        preview_box = QHBoxLayout()
        preview_box.addStretch()
        self._preview = PreviewWidget(self)
        preview_box.addWidget(self._preview)
        preview_box.addStretch()
        console_layout.addLayout(preview_box)

        # 体型滑块
        console_layout.addLayout(self._make_scale_section())

        # 背景选择
        console_layout.addLayout(self._make_background_section())

        # 互动区
        console_layout.addLayout(self._make_interact_section())

        # 开关区
        console_layout.addLayout(self._make_toggle_section())

        # 状态栏
        console_layout.addLayout(self._make_status_bar())

        self._stack.addWidget(self._console_widget)

        # 页面 1：冷头固件管理（开机/待机动画刷写）
        self.flash_widget = FlashWidget(self)
        self._wire_flash_widget()
        self._stack.addWidget(self.flash_widget)

        outer.addWidget(self._stack)

    def _make_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 2)
        layout.setSpacing(6)

        # 左侧：图标与标题
        ico_file = Path(__file__).resolve().parent.parent / 'assets' / 'app_icon.ico'
        if ico_file.is_file():
            ico_lbl = QLabel()
            ico_lbl.setPixmap(QPixmap(str(ico_file)).scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            layout.addWidget(ico_lbl)
        title_label = QLabel("桌宠之家")
        font = QFont("Microsoft YaHei UI", 13)
        font.setWeight(QFont.DemiBold)
        title_label.setFont(font)
        title_label.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent;")
        layout.addWidget(title_label)

        layout.addStretch()

        # 中间：分页胶囊切换按钮
        self._tab_btn_console = QPushButton("控制台")
        self._tab_btn_flash = QPushButton("屏幕固件")
        for b in (self._tab_btn_console, self._tab_btn_flash):
            b.setCheckable(True)
            b.setFixedHeight(24)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(38,41,50,0.60);
                    border: 1px solid rgba(255,255,255,0.08);
                    border-radius: 12px;
                    color: {TEXT_MUTED};
                    font-size: 11px;
                    padding: 0 8px;
                }}
                QPushButton:hover {{
                    background: rgba(55,58,68,0.85);
                    color: {TEXT_PRIMARY};
                }}
                QPushButton:checked {{
                    background: rgba(111,227,255,0.18);
                    border: 1px solid rgba(111,227,255,0.50);
                    color: {ACCENT};
                }}
            """)
        self._tab_btn_console.setChecked(True)
        self._tab_btn_console.clicked.connect(lambda: self._switch_tab(0))
        self._tab_btn_flash.clicked.connect(lambda: self._switch_tab(1))

        layout.addWidget(self._tab_btn_console)
        layout.addWidget(self._tab_btn_flash)

        # 详细控制中心按钮
        self._dashboard_btn = QPushButton("🗖")
        self._dashboard_btn.setFixedSize(24, 24)
        self._dashboard_btn.setToolTip("打开可视化详细控制中心")
        self._dashboard_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #8C95A3;
                font-size: 13px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.08);
                color: #6FE3FF;
            }
        """)
        self._dashboard_btn.clicked.connect(self.open_dashboard_requested.emit)
        layout.addWidget(self._dashboard_btn)

        # 右侧：关闭按钮
        self._close_btn = QPushButton("×")
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {TEXT_MUTED};
                font-size: 18px;
                font-weight: 300;
                border-radius: 12px;
            }}
            QPushButton:hover {{
                color: {DANGER};
                background: rgba(255,91,91,0.12);
            }}
        """)
        self._close_btn.clicked.connect(self.close_requested.emit)
        self._close_btn.clicked.connect(self.hide)
        layout.addWidget(self._close_btn)

        self._title_bar_height = 36
        return layout

    def _switch_tab(self, index: int):
        self._stack.setCurrentIndex(index)
        self._tab_btn_console.setChecked(index == 0)
        self._tab_btn_flash.setChecked(index == 1)

    def jump_to_section(self, key: str):
        """外部快捷跳转"""
        if key in ('settings', 'firmware'):
            self._switch_tab(1)
        else:
            self._switch_tab(0)

    def _make_scale_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addWidget(_SectionLabel("体  型"))

        row = QHBoxLayout()
        row.setSpacing(10)

        self._scale_slider = QSlider(Qt.Horizontal)
        self._scale_slider.setRange(0, len(SCALES) - 1)
        self._scale_slider.setValue(3)  # 默认 2.0×
        self._scale_slider.setFixedHeight(24)
        row.addWidget(self._scale_slider)

        self._scale_label = QLabel("2.0×")
        self._scale_label.setFixedWidth(38)
        self._scale_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._scale_label.setStyleSheet(f"color: {ACCENT}; font-size: 12px;")
        row.addWidget(self._scale_label)

        self._scale_slider.valueChanged.connect(self._on_scale_changed)
        layout.addLayout(row)
        return layout

    def _make_background_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addWidget(_SectionLabel("背  景"))

        row = QHBoxLayout()
        row.setSpacing(6)

        self._bg_buttons = {}
        bg_defs = [
            ('dot',   '点阵', True),
            ('solid', '纯色', True),
            ('image', '图片', True),
            ('daily', '轮换', False),
        ]
        for key, label, enabled in bg_defs:
            btn = _CapsuleButton(label)
            btn.setEnabled(enabled)
            btn.clicked.connect(lambda checked, k=key: self._on_bg_selected(k))
            row.addWidget(btn)
            self._bg_buttons[key] = btn

        self._bg_buttons['dot'].setChecked(True)
        layout.addLayout(row)
        return layout

    def _make_interact_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addWidget(_SectionLabel("互  动"))

        row = QHBoxLayout()
        row.setSpacing(10)

        self._btn_touch  = _IconButton('touch', '摸头')
        self._btn_talk   = _IconButton('panel', '说话')
        self._btn_sleep  = _IconButton('stream', '睡觉')

        self._btn_talk.setEnabled(False)
        self._btn_sleep.setEnabled(False)

        self._btn_touch.clicked.connect(self._on_touch_clicked)

        row.addWidget(self._btn_touch)
        row.addWidget(self._btn_talk)
        row.addWidget(self._btn_sleep)
        row.addStretch()
        layout.addLayout(row)
        return layout

    def _make_toggle_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._chk_stream = QCheckBox("推流到屏")
        self._chk_stream.setChecked(True)
        self._chk_stream.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        self._chk_stream.toggled.connect(self._on_stream_toggled)
        layout.addWidget(self._chk_stream)

        self._chk_hide_pet = QCheckBox("隐藏桌面桌宠")
        self._chk_hide_pet.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        self._chk_hide_pet.toggled.connect(self._on_hide_pet_toggled)
        layout.addWidget(self._chk_hide_pet)

        return layout

    def _make_status_bar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(6)

        self._status_dot = QLabel("🔴")
        self._status_dot.setFixedWidth(18)
        self._status_dot.setStyleSheet("font-size: 10px;")
        layout.addWidget(self._status_dot)

        self._status_label = QLabel("— fps · — KB · 未连接")
        self._status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(self._status_label)
        layout.addStretch()

        return layout

    # ================================================================
    # 固件管理连接
    # ================================================================

    def _wire_flash_widget(self):
        """将 flash_widget 的操作信号连接至 flash_bridge"""
        self.flash_widget.wallpaper_change_requested.connect(self._on_change_wallpaper)
        self.flash_widget.animation_change_requested.connect(self._on_change_animation)
        self.flash_widget.wallpaper_reset_requested.connect(self._on_reset_flash)
        self.flash_widget.animation_reset_requested.connect(self._on_reset_flash)

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
            # 转换媒体文件为原厂打包动画包
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

    # ================================================================
    # 状态与设置联动
    # ================================================================

    def _sync_from_settings(self):
        if not self.settings:
            return
        scale, bg_mode, bg_val, pushing, *rest = self.settings.snapshot()
        if scale in SCALES:
            idx = SCALES.index(scale)
            self._scale_slider.setValue(idx)
            self._scale_label.setText(f"{scale}×")
        self._chk_stream.setChecked(pushing)
        self._chk_hide_pet.setChecked(self.settings.hide_desktop_pet)

    def _on_scale_changed(self, idx: int):
        value = SCALES[idx]
        self._scale_label.setText(f"{value}×")
        self.scale_changed.emit(value)
        if self.settings:
            self.settings.update(scale=value)

    def _on_bg_selected(self, key: str):
        for k, btn in self._bg_buttons.items():
            btn.setChecked(k == key)

        if key == 'solid':
            color = QColorDialog.getColor(
                QColor(13, 17, 23), self, "选择背景颜色"
            )
            if color.isValid():
                self.background_changed.emit('solid', color)
                if self.settings:
                    self.settings.update(bg_mode='color', bg_value=color.name())
            else:
                self._bg_buttons['dot'].setChecked(True)
        elif key == 'image':
            path, _ = QFileDialog.getOpenFileName(
                self, "选择背景图片", "",
                "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)"
            )
            if path:
                self.background_changed.emit('image', path)
                if self.settings:
                    self.settings.update(bg_mode='image', bg_value=path)
            else:
                self._bg_buttons['dot'].setChecked(True)
        else:
            self.background_changed.emit(key, None)
            if self.settings:
                self.settings.update(bg_mode='dots', bg_value='#0D1117')

    def _on_touch_clicked(self):
        self.pet_action.emit('touch')
        if self.renderer:
            self.renderer.send_command('click', ratio=(0.78, 0.74))

    def _on_stream_toggled(self, checked: bool):
        self.stream_toggled.emit(checked)
        if self.settings:
            self.settings.update(pushing=checked)

    def _on_hide_pet_toggled(self, checked: bool):
        if self.settings:
            self.settings.update(hide_desktop_pet=checked)
        self.hide_pet_toggled.emit(checked)

    def _refresh_status_bar(self):
        s = self._status
        dot = "🟢" if s['ok'] else "🔴"
        self._status_dot.setText(dot)
        if s['ok']:
            text = f"{s['fps']:.1f} fps · {s['kb']:.1f} KB · {s['pkt']} 包 · {s['msg']}"
        else:
            text = s['msg']
        self._status_label.setText(text)

    # ================================================================
    # 外部更新接口
    # ================================================================

    def on_status_updated(self, fps: float, kb: float, pkt: int,
                          ok: bool, msg: str):
        self._status.update(fps=fps, kb=kb, pkt=pkt, ok=ok, msg=msg)

    def on_frame_ready(self, jpeg_bytes: bytes):
        if self.isVisible():
            self._preview.update_frame(jpeg_bytes)

    # ================================================================
    # 绘制（底板磨砂背景）
    # ================================================================

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, PANEL_W, PANEL_H), RADIUS, RADIUS)

        bg = _parse_rgba(SURFACE)
        painter.fillPath(path, QBrush(bg))

        border_c = _parse_rgba(BORDER)
        painter.setPen(QPen(border_c, 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.end()

    # ================================================================
    # 拖拽（优先使用 Windows 原生 startSystemMove）
    # ================================================================

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            local_pos = self.mapFromGlobal(event.globalPosition().toPoint())
            if local_pos.y() <= self._title_bar_height + 14:
                wh = self.windowHandle()
                if wh and hasattr(wh, 'startSystemMove') and wh.startSystemMove():
                    event.accept()
                    return
                self._dragging_header = True
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
            else:
                self._dragging_header = False
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
