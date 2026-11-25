# flash_widget.py — 开机/待机动画更换子面板
#
# FlashWidget:
#   - 集成到 PanelWindow 中的固件管理子页
#   - A. 待机壁纸区：缩略图 + 更换 + 恢复出厂
#   - B. 开机动画区：缩略图 + 帧数 + 更换 + 恢复出厂
#   - C. 进度条（刷写时才显示）

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QFileDialog,
    QSizePolicy, QFrame
)
from PySide6.QtCore import Qt, QTimer, QRectF, Signal
from PySide6.QtGui import (
    QPainter, QColor, QPixmap, QBrush, QPen,
    QPainterPath, QFont
)

from .tokens import (
    SURFACE, SURFACE_HOVER, BORDER, ACCENT,
    TEXT_PRIMARY, TEXT_MUTED, DANGER,
    RADIUS, build_qss
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


# ——— 缩略图占位控件 ———

class _ThumbWidget(QWidget):
    """120×90 固定尺寸的图片缩略图显示控件"""

    def __init__(self, placeholder: str = "默认", parent=None):
        super().__init__(parent)
        self.setFixedSize(120, 90)
        self._pixmap: QPixmap | None = None
        self._placeholder = placeholder

    def set_pixmap(self, px: QPixmap | None):
        self._pixmap = px
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        rr = 7.0
        rect = QRectF(0, 0, 120, 90)
        path = QPainterPath()
        path.addRoundedRect(rect, rr, rr)

        painter.setClipPath(path)
        bg = _parse_rgba(SURFACE)
        painter.fillPath(path, QBrush(bg))

        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                120, 90,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            ox = (120 - scaled.width())  // 2
            oy = (90  - scaled.height()) // 2
            painter.drawPixmap(ox, oy, scaled)
        else:
            painter.setClipping(False)
            painter.setPen(QColor(TEXT_MUTED))
            font = QFont("Microsoft YaHei UI", 10)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, self._placeholder)

        # 描边
        painter.setClipping(False)
        border_c = _parse_rgba(BORDER)
        border_c.setAlphaF(0.20)
        painter.setPen(QPen(border_c, 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), rr, rr)
        painter.end()


# ——— 危险按钮样式 ———
_DANGER_BTN_STYLE = f"""
QPushButton {{
    background: transparent;
    border: 1px solid rgba(255,91,91,0.40);
    border-radius: 10px;
    color: {DANGER};
    font-size: 12px;
    padding: 4px 10px;
}}
QPushButton:hover {{
    background: rgba(255,91,91,0.10);
    border-color: rgba(255,91,91,0.65);
}}
QPushButton:pressed {{
    background: rgba(255,91,91,0.18);
}}
"""

_NORMAL_BTN_STYLE = f"""
QPushButton {{
    background: rgba(38,41,50,0.80);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 10px;
    color: {TEXT_PRIMARY};
    font-size: 12px;
    padding: 4px 10px;
}}
QPushButton:hover {{
    background: rgba(55,58,68,0.95);
    border-color: rgba(255,255,255,0.18);
}}
QPushButton:pressed {{
    background: rgba(70,74,86,0.98);
}}
"""


# ================================================================
# FlashWidget
# ================================================================

class FlashWidget(QWidget):
    """固件管理子页：待机壁纸 & 开机动画更换，含刷写进度条。

    Signals:
        wallpaper_change_requested(str):  用户选择的壁纸文件路径
        wallpaper_reset_requested():      恢复默认壁纸
        animation_change_requested(str):  用户选择的动画文件路径
        animation_reset_requested():      恢复默认动画
    """

    wallpaper_change_requested  = Signal(str)
    wallpaper_reset_requested   = Signal()
    animation_change_requested  = Signal(str)
    animation_reset_requested   = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(build_qss())

        self._progress_visible = False

        self._build_ui()
        self._load_defaults()

    def _load_defaults(self):
        """加载当前实际应用的壁纸素材缩略图与信息（若有硬件读取/当前生效壁纸则优先展示当前应用者）"""
        try:
            import os
            from pathlib import Path
            defaults_dir = Path(__file__).resolve().parents[1] / "assets/defaults"
            appdata_cur = Path(os.environ.get('APPDATA', '')) / 'BigFishTitanConsole' / 'current_standby.jpg'
            
            # 优先从 APPDATA 或 assets/defaults 读取当前应用中的壁纸
            cur_wp = defaults_dir / "current_standby.jpg"
            if appdata_cur.is_file():
                cur_wp = appdata_cur
            elif not cur_wp.exists():
                cur_wp = defaults_dir / "standby_preview.jpg"
                if not cur_wp.exists():
                    cur_wp = defaults_dir / "standby.bin"

            if cur_wp.exists():
                px = QPixmap(str(cur_wp))
                if not px.isNull():
                    self._wallpaper_thumb.set_pixmap(px)
                    size_kb = cur_wp.stat().st_size / 1024.0
                    is_current = "current_standby" in cur_wp.name
                    desc = f"当前应用待机壁纸 · 640×480 ({size_kb:.1f} KB)" if is_current else "出厂备份待机壁纸 · 640×480 (102.8 KB)"
                    if hasattr(self, '_lbl_wallpaper_info'):
                        self._lbl_wallpaper_info.setText(desc)

            # 开机动画第一帧缩略图
            bf = defaults_dir / "boot_first_frame.jpg"
            if bf.exists():
                px = QPixmap(str(bf))
                if not px.isNull():
                    self._anim_thumb.set_pixmap(px)
                    self._anim_frame_label.setText("270 帧 (出厂就绪)")
                    if hasattr(self, '_lbl_anim_info'):
                        self._lbl_anim_info.setText("出厂备份已就绪 · 270 帧 (5.4 MB)")
        except Exception:
            pass

    # ================================================================
    # UI 构建
    # ================================================================

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # A. 待机壁纸区
        layout.addLayout(self._make_wallpaper_section())

        # 分割线
        layout.addWidget(self._make_divider())

        # B. 开机动画区
        layout.addLayout(self._make_animation_section())

        # C. 进度条（默认隐藏）
        self._progress_container = self._make_progress_section()
        layout.addLayout(self._progress_container)

        layout.addStretch()

    def _make_wallpaper_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(8)

        # 标题
        title = QLabel("待机壁纸")
        font  = QFont("Microsoft YaHei UI", 12)
        font.setWeight(QFont.Medium)
        title.setFont(font)
        title.setStyleSheet(f"color: {TEXT_PRIMARY};")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(10)

        # 缩略图
        self._wallpaper_thumb = _ThumbWidget("默认")
        row.addWidget(self._wallpaper_thumb)

        # 操作按钮列
        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)

        self._lbl_wallpaper_info = QLabel("出厂备份已就绪 · 640×480 (102.8 KB)")
        self._lbl_wallpaper_info.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        btn_col.addWidget(self._lbl_wallpaper_info)

        btns_h = QHBoxLayout()
        btns_h.setSpacing(8)

        self._btn_wallpaper_change = QPushButton("更换壁纸")
        self._btn_wallpaper_change.setStyleSheet(_NORMAL_BTN_STYLE)
        self._btn_wallpaper_change.clicked.connect(self._on_wallpaper_change)
        btns_h.addWidget(self._btn_wallpaper_change)

        self._btn_wallpaper_reset = QPushButton("恢复出厂")
        self._btn_wallpaper_reset.setStyleSheet(_DANGER_BTN_STYLE)
        self._btn_wallpaper_reset.clicked.connect(self.wallpaper_reset_requested.emit)
        btns_h.addWidget(self._btn_wallpaper_reset)
        btn_col.addLayout(btns_h)

        btn_col.addStretch()
        row.addLayout(btn_col)
        row.addStretch()

        layout.addLayout(row)
        return layout

    def _make_animation_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(8)

        # 标题
        title = QLabel("开机动画")
        font  = QFont("Microsoft YaHei UI", 12)
        font.setWeight(QFont.Medium)
        title.setFont(font)
        title.setStyleSheet(f"color: {TEXT_PRIMARY};")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(10)

        # 缩略图 + 帧数
        thumb_col = QVBoxLayout()
        thumb_col.setSpacing(4)
        self._anim_thumb = _ThumbWidget("默认")
        thumb_col.addWidget(self._anim_thumb)

        self._anim_frame_label = QLabel("— 帧")
        self._anim_frame_label.setAlignment(Qt.AlignCenter)
        self._anim_frame_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        thumb_col.addWidget(self._anim_frame_label)
        row.addLayout(thumb_col)

        # 操作按钮列
        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)

        self._lbl_anim_info = QLabel("出厂备份已就绪 · 270 帧 (5.4 MB)")
        self._lbl_anim_info.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        btn_col.addWidget(self._lbl_anim_info)

        btns_h = QHBoxLayout()
        btns_h.setSpacing(8)

        self._btn_anim_change = QPushButton("更换动画")
        self._btn_anim_change.setStyleSheet(_NORMAL_BTN_STYLE)
        self._btn_anim_change.clicked.connect(self._on_animation_change)
        btns_h.addWidget(self._btn_anim_change)

        self._btn_anim_reset = QPushButton("恢复出厂")
        self._btn_anim_reset.setStyleSheet(_DANGER_BTN_STYLE)
        self._btn_anim_reset.clicked.connect(self.animation_reset_requested.emit)
        btns_h.addWidget(self._btn_anim_reset)
        btn_col.addLayout(btns_h)

        btn_col.addStretch()
        row.addLayout(btn_col)
        row.addStretch()

        layout.addLayout(row)
        return layout

    def _make_progress_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(5)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: rgba(255,255,255,0.08);
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background: {ACCENT};
                border-radius: 4px;
            }}
        """)
        self._progress_bar.hide()
        layout.addWidget(self._progress_bar)

        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self._progress_label.hide()
        layout.addWidget(self._progress_label)

        return layout

    def _make_divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background: rgba(255,255,255,0.07); max-height: 1px;")
        return line

    # ================================================================
    # 槽函数
    # ================================================================

    def _on_wallpaper_change(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择待机壁纸", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if path:
            import os, shutil
            from pathlib import Path
            # 显示缩略图预览
            px = QPixmap(path)
            if not px.isNull():
                self._wallpaper_thumb.set_pixmap(px)
                size_kb = os.path.getsize(path) / 1024.0
                if hasattr(self, '_lbl_wallpaper_info'):
                    self._lbl_wallpaper_info.setText(f"当前应用待机壁纸 · 640×480 ({size_kb:.1f} KB)")
                try:
                    appdata_dir = Path(os.environ.get('APPDATA', '')) / 'BigFishTitanConsole'
                    appdata_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, appdata_dir / "current_standby.jpg")
                except Exception:
                    pass
            self.wallpaper_change_requested.emit(path)

    def _on_animation_change(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择开机动画", "",
            "媒体文件 (*.mp4 *.gif *.png *.jpg *.jpeg)"
        )
        if path:
            # 对于图片，直接显示缩略图；视频/gif 仅显示路径提示
            ext = path.rsplit('.', 1)[-1].lower()
            if ext in ('png', 'jpg', 'jpeg'):
                px = QPixmap(path)
                if not px.isNull():
                    self._anim_thumb.set_pixmap(px)
                    self._anim_frame_label.setText("1 帧")
            elif ext == 'gif':
                # GIF：尝试加载首帧
                px = QPixmap(path)
                if not px.isNull():
                    self._anim_thumb.set_pixmap(px)
                self._anim_frame_label.setText("GIF 动画")
            else:
                self._anim_thumb.set_pixmap(None)
                self._anim_frame_label.setText("视频文件")
            self.animation_change_requested.emit(path)

    # ================================================================
    # 外部调用槽（由 FlashSignals 触发）
    # ================================================================

    def on_progress(self, percent: int, msg: str):
        """刷写进度更新，显示进度条"""
        self._progress_bar.show()
        self._progress_label.show()
        self._progress_bar.setValue(max(0, min(100, percent)))
        self._progress_label.setText(msg)

        # 禁用操作按钮
        for btn in (self._btn_wallpaper_change, self._btn_wallpaper_reset,
                    self._btn_anim_change, self._btn_anim_reset):
            btn.setEnabled(False)

    def on_completed(self, success: bool, msg: str):
        """刷写完成回调"""
        self._progress_bar.setValue(100 if success else self._progress_bar.value())
        self._progress_label.setText(msg)

        # 恢复操作按钮
        for btn in (self._btn_wallpaper_change, self._btn_wallpaper_reset,
                    self._btn_anim_change, self._btn_anim_reset):
            btn.setEnabled(True)

        # 2 秒后隐藏进度条
        QTimer.singleShot(2000, self._hide_progress)

    def _hide_progress(self):
        self._progress_bar.hide()
        self._progress_label.hide()
        self._progress_bar.setValue(0)

    # ================================================================
    # 外部更新缩略图（由 Flash 读取当前固件数据后调用）
    # ================================================================

    def set_wallpaper_thumb(self, px: QPixmap | None):
        """设置当前待机壁纸缩略图（从 Flash 读取后调用）"""
        self._wallpaper_thumb.set_pixmap(px)

    def set_animation_thumb(self, px: QPixmap | None, frame_count: int = 0):
        """设置当前开机动画首帧缩略图"""
        self._anim_thumb.set_pixmap(px)
        if frame_count > 0:
            self._anim_frame_label.setText(f"{frame_count} 帧")
        else:
            self._anim_frame_label.setText("— 帧")

    # ================================================================
    # 背景绘制（磨砂卡片）
    # ================================================================

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), RADIUS, RADIUS)

        bg = _parse_rgba(SURFACE)
        painter.fillPath(path, QBrush(bg))

        border_c = _parse_rgba(BORDER)
        painter.setPen(QPen(border_c, 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        painter.end()
