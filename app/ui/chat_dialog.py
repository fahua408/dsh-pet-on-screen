# -*- coding: utf-8 -*-
"""chat_dialog.py — 现代化暗黑胶囊多模态对话弹窗。

功能矩阵：
1. 文字输入：自适应多行输入，回车即发，Shift+Enter 换行，Esc 退出
2. 目标桌宠指示与一键切换：清晰显示并可切换当前发送目标（🐟 大肥鱼 / 👧 蓝毛女仆）
3. 图片上传：点击 🖼️ 或 Ctrl+V 直接粘贴剪贴板图片，自动智能缩放压缩以符合 DSH 附件协议 (attachment.data)
4. 屏幕截图：点击 📷 抓取屏幕画面，自动压缩并挂载为待发送附件
5. 语音唤醒：点击 🎙️ 触发对应桌宠原生语音录入热键（大肥鱼 Alt×2 / 小女仆 Ctrl+Shift+M）
"""
from __future__ import annotations

import base64
import logging

from PySide6.QtCore import (
    Qt, Signal, QRectF, QByteArray, QBuffer, QIODevice, QTimer, QEvent
)
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen, QBrush,
    QKeyEvent, QPixmap
)
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QWidget,
    QTextEdit, QPushButton, QLabel, QApplication,
    QFileDialog
)

log = logging.getLogger('dsh.chat')

# DSH 宿主 parseImageAttachment 的 base64 长度上限为 900,000 字符
_MAX_B64_CHARS = 820_000


class ChatDialog(QDialog):
    """桌宠暗黑胶囊打字框与多模态输入组件。"""

    # 发射 (text: str, attachment: dict | None)
    chat_submitted = Signal(str, object)
    message_sent = Signal(str)
    voice_triggered = Signal(str)
    target_switched = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._is_expanded = False
        self._font_size = 10
        self._target_pet = 'coopanion'
        self._cast_mode = 'dual'
        self.setFixedSize(480, 104)

        self._tail_offset_x = 0
        self._attachment: dict | None = None
        self._attachment_pixmap: QPixmap | None = None

        self._build_ui()

    def set_target_info(self, cast_mode: str, target_pet: str):
        """同步当前投放模式与对话目标桌宠。"""
        self._cast_mode = cast_mode
        self._target_pet = target_pet if cast_mode == 'dual' else cast_mode
        self._refresh_target_badge()

    def _refresh_target_badge(self):
        is_coop = (self._target_pet == 'coopanion')
        if is_coop:
            self._btn_target.setText("🐟 致: 大肥鱼")
            self._btn_target.setStyleSheet("""
                QPushButton {
                    background: rgba(111, 227, 255, 0.14);
                    border: 1px solid rgba(111, 227, 255, 0.45);
                    border-radius: 8px;
                    color: #6FE3FF;
                    padding: 0 9px;
                    font-weight: bold;
                }
                QPushButton:hover { background: rgba(111, 227, 255, 0.25); }
            """)
            self._edit.setPlaceholderText("和大肥鱼说点什么…")
        else:
            self._btn_target.setText("👧 致: 蓝毛女仆")
            self._btn_target.setStyleSheet("""
                QPushButton {
                    background: rgba(96, 165, 250, 0.16);
                    border: 1px solid rgba(96, 165, 250, 0.48);
                    border-radius: 8px;
                    color: #93C5FD;
                    padding: 0 9px;
                    font-weight: bold;
                }
                QPushButton:hover { background: rgba(96, 165, 250, 0.28); }
            """)
            self._edit.setPlaceholderText("和蓝毛小女仆聊聊天（支持粘贴/上传图片）…")
        self._btn_target.setToolTip("点击切换对话目标桌宠" if self._cast_mode == 'dual' else "当前单宠投放目标")

    def _on_target_clicked(self):
        if self._cast_mode == 'dual':
            self._target_pet = 'dsh' if self._target_pet == 'coopanion' else 'coopanion'
            self._refresh_target_badge()
            self.target_switched.emit(self._target_pet)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 16)
        root.setSpacing(6)

        # 1. 顶部行：打字输入框 + 发送按钮 + 放大/关闭按钮
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self._edit = QTextEdit()
        self._edit.setPlaceholderText("说点什么…")
        self._edit.setFont(QFont("Microsoft YaHei UI", 10))
        self._edit.setFixedHeight(48)
        self._edit.setStyleSheet("""
            QTextEdit {
                background: rgba(13, 17, 24, 0.92);
                border: 1.5px solid rgba(111, 227, 255, 0.55);
                border-radius: 13px;
                color: #FFFFFF;
                padding: 6px 10px;
                selection-background-color: #2F73F6;
                selection-color: #FFFFFF;
            }
            QTextEdit::placeholder {
                color: #8E98A8;
            }
        """)
        self._edit.installEventFilter(self)
        top_row.addWidget(self._edit, 1)

        self._btn_send = QPushButton("发送")
        self._btn_send.setFixedSize(64, 48)
        self._btn_send.setCursor(Qt.PointingHandCursor)
        self._btn_send.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        self._btn_send.setStyleSheet("""
            QPushButton {
                background: #6FE3FF;
                border: none;
                border-radius: 13px;
                color: #090D16;
            }
            QPushButton:hover {
                background: #9AEEFF;
            }
            QPushButton:pressed {
                background: #38BDF8;
            }
        """)
        self._btn_send.clicked.connect(self._do_send)
        top_row.addWidget(self._btn_send)

        self._btn_expand = QPushButton("⛶")
        self._btn_expand.setFixedSize(24, 24)
        self._btn_expand.setCursor(Qt.PointingHandCursor)
        self._btn_expand.setToolTip("放大对话框 (F11)")
        self._btn_expand.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: rgba(255, 255, 255, 0.55);
                font-size: 13px;
                font-weight: bold;
                border-radius: 12px;
            }
            QPushButton:hover {
                color: #6FE3FF;
                background: rgba(255, 255, 255, 0.12);
            }
        """)
        self._btn_expand.clicked.connect(self._toggle_expand)
        top_row.addWidget(self._btn_expand)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(24, 24)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: rgba(255, 255, 255, 0.55);
                font-size: 13px;
                font-weight: bold;
                border-radius: 12px;
            }
            QPushButton:hover {
                color: #FF5B5B;
                background: rgba(255, 91, 91, 0.15);
            }
        """)
        btn_close.clicked.connect(self.reject)
        top_row.addWidget(btn_close)

        root.addLayout(top_row)

        # 2. 底部工具栏行：目标桌宠徽标、图片上传、截屏、语音输入、附件预览卡片
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(2, 0, 2, 0)
        bottom_row.setSpacing(6)

        self._btn_target = QPushButton("🐟 致: 大肥鱼")
        self._btn_target.setFixedHeight(26)
        self._btn_target.setFont(QFont("Microsoft YaHei UI", 9))
        self._btn_target.setCursor(Qt.PointingHandCursor)
        self._btn_target.clicked.connect(self._on_target_clicked)
        bottom_row.addWidget(self._btn_target)

        self._btn_image = QPushButton("🖼️ 图片")
        self._btn_image.setToolTip("选择本地图片或粘贴剪贴板图片 (Ctrl+V)")
        self._btn_image.setCursor(Qt.PointingHandCursor)
        self._style_sub_button(self._btn_image)
        self._btn_image.clicked.connect(self._pick_image)
        bottom_row.addWidget(self._btn_image)

        self._btn_screen = QPushButton("📷 截屏")
        self._btn_screen.setToolTip("截取当前屏幕画面作为多模态附图")
        self._btn_screen.setCursor(Qt.PointingHandCursor)
        self._style_sub_button(self._btn_screen)
        self._btn_screen.clicked.connect(self._capture_screen)
        bottom_row.addWidget(self._btn_screen)

        self._btn_voice = QPushButton("🎙️ 语音")
        self._btn_voice.setToolTip("触发当前桌宠原生语音热键")
        self._btn_voice.setCursor(Qt.PointingHandCursor)
        self._style_sub_button(self._btn_voice)
        self._btn_voice.clicked.connect(self._toggle_voice)
        bottom_row.addWidget(self._btn_voice)

        # 附件卡片预览容器
        self._attach_container = QWidget()
        self._attach_container.setVisible(False)
        attach_layout = QHBoxLayout(self._attach_container)
        attach_layout.setContentsMargins(6, 1, 6, 1)
        attach_layout.setSpacing(5)
        self._attach_container.setStyleSheet("""
            QWidget {
                background: rgba(47, 115, 246, 0.22);
                border: 1px solid rgba(111, 227, 255, 0.45);
                border-radius: 7px;
            }
        """)

        self._attach_thumb = QLabel()
        self._attach_thumb.setFixedSize(22, 22)
        self._attach_thumb.setScaledContents(True)
        attach_layout.addWidget(self._attach_thumb)

        self._attach_label = QLabel("已附图")
        self._attach_label.setFont(QFont("Microsoft YaHei UI", 8))
        self._attach_label.setStyleSheet("color: #6FE3FF; border: none; background: transparent;")
        attach_layout.addWidget(self._attach_label)

        btn_remove_attach = QPushButton("✕")
        btn_remove_attach.setFixedSize(16, 16)
        btn_remove_attach.setCursor(Qt.PointingHandCursor)
        btn_remove_attach.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.2);
                border: none;
                color: #FFFFFF;
                font-size: 10px;
                border-radius: 8px;
            }
            QPushButton:hover { background: #EF4444; }
        """)
        btn_remove_attach.clicked.connect(self._clear_attachment)
        attach_layout.addWidget(btn_remove_attach)

        bottom_row.addWidget(self._attach_container)
        bottom_row.addStretch(1)

        self._hint_label = QLabel("Enter 发送 · Shift+Enter 换行")
        self._hint_label.setFont(QFont("Microsoft YaHei UI", 8))
        self._hint_label.setStyleSheet("color: rgba(255, 255, 255, 0.38);")
        bottom_row.addWidget(self._hint_label)

        root.addLayout(bottom_row)
        self._refresh_target_badge()

    def _style_sub_button(self, btn: QPushButton):
        btn.setFixedHeight(26)
        btn.setFont(QFont("Microsoft YaHei UI", 9))
        btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.07);
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 8px;
                color: #CBD5E1;
                padding: 0 8px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.16);
                color: #FFFFFF;
                border-color: #6FE3FF;
            }
            QPushButton:pressed {
                background: rgba(47, 115, 246, 0.3);
            }
        """)

    def _set_attachment_pixmap(self, pix: QPixmap, media_type: str = "image/png"):
        """编码并自适应压缩图片，确保严格满足 dsh-pet parseImageAttachment 的 data 字段与 900KB Base64 限制。"""
        work_pix = pix
        if work_pix.width() > 1280 or work_pix.height() > 960:
            work_pix = work_pix.scaled(1280, 960, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        fmt = "PNG" if "png" in media_type else "JPEG"
        work_pix.save(buf, fmt, 85)
        raw_bytes = bytes(ba.data())
        b64 = base64.b64encode(raw_bytes).decode('ascii')

        # 若 PNG base64 超过上限，自动转为高画质 JPEG 并按需降尺寸
        if len(b64) > _MAX_B64_CHARS:
            media_type = "image/jpeg"
            for quality, max_w in ((82, 1280), (75, 1024), (68, 800)):
                if work_pix.width() > max_w:
                    work_pix = work_pix.scaled(max_w, int(max_w * 0.75), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                ba.clear()
                buf = QBuffer(ba)
                buf.open(QIODevice.WriteOnly)
                work_pix.save(buf, "JPEG", quality)
                raw_bytes = bytes(ba.data())
                b64 = base64.b64encode(raw_bytes).decode('ascii')
                if len(b64) <= _MAX_B64_CHARS:
                    break

        self._attachment = {
            'data': b64,
            'base64': b64,
            'mediaType': media_type,
            'bytes': len(raw_bytes),
            'width': work_pix.width(),
            'height': work_pix.height()
        }
        self._attachment_pixmap = work_pix
        self._attach_thumb.setPixmap(work_pix)
        self._attach_label.setText(f"{len(raw_bytes) / 1024:.0f}KB")
        self._attach_container.setVisible(True)

    def _clear_attachment(self):
        self._attachment = None
        self._attachment_pixmap = None
        self._attach_container.setVisible(False)

    def _pick_image(self):
        fn, _ = QFileDialog.getOpenFileName(
            self, "选择对话附图", "", "图片文件 (*.png *.jpg *.jpeg *.webp *.gif)"
        )
        if fn:
            pix = QPixmap(fn)
            if not pix.isNull():
                media_type = "image/jpeg" if fn.lower().endswith(('.jpg', '.jpeg')) else "image/png"
                self._set_attachment_pixmap(pix, media_type)

    def _capture_screen(self):
        """截取当前屏幕画面并附加"""
        self.hide()
        QTimer.singleShot(200, self._finish_capture)

    def _finish_capture(self):
        screen = QApplication.primaryScreen()
        if screen:
            pix = screen.grabWindow(0)
            if not pix.isNull():
                self._set_attachment_pixmap(pix, "image/jpeg")
        self.show()
        self.raise_()
        self.activateWindow()
        self._edit.setFocus()

    def _toggle_voice(self):
        """触发对应桌宠的真实全局语音热键。"""
        try:
            from core.win32_guard import trigger_coopanion_voice, trigger_dsh_voice
            if self._target_pet == 'coopanion':
                trigger_coopanion_voice()
                self._hint_label.setText("🎙️ 已唤醒大肥鱼语音 (Alt×2)")
            else:
                trigger_dsh_voice()
                self._hint_label.setText("🎙️ 已切换女仆语音录音 (Ctrl+Shift+M)")
        except Exception as e:
            log.warning('触发语音热键异常: %s', e)
        self.voice_triggered.emit(self._target_pet)

    def _toggle_expand(self):
        """切换紧凑胶囊模式与放大输入模式"""
        self._is_expanded = not self._is_expanded
        sc = QApplication.screenAt(self.geometry().center())
        screen = sc.availableGeometry() if sc else QApplication.primaryScreen().availableGeometry()

        if self._is_expanded:
            self._btn_expand.setText("🗗")
            self._btn_expand.setToolTip("恢复紧凑模式 (F11)")
            new_w, new_h = 660, 240
            self._edit.setFixedHeight(150)
            self._btn_send.setFixedHeight(150)
            self._hint_label.setText("Enter 发送 · Shift+Enter 换行 · F11 紧凑")
        else:
            self._btn_expand.setText("⛶")
            self._btn_expand.setToolTip("放大对话框 (F11)")
            new_w, new_h = 480, 104
            self._edit.setFixedHeight(48)
            self._btn_send.setFixedHeight(48)
            self._hint_label.setText("Enter 发送 · Shift+Enter 换行")

        cur = self.geometry()
        new_x = cur.center().x() - new_w // 2
        new_y = cur.bottom() - new_h
        new_x = max(screen.left() + 10, min(new_x, screen.right() - new_w - 10))
        new_y = max(screen.top() + 10, min(new_y, screen.bottom() - new_h - 10))

        self.setFixedSize(new_w, new_h)
        self.move(int(new_x), int(new_y))
        self.update()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            key_event: QKeyEvent = event
            if key_event.key() == Qt.Key_F11:
                self._toggle_expand()
                return True

        if obj is self._edit and event.type() == QEvent.KeyPress:
            key_event: QKeyEvent = event
            if key_event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if key_event.modifiers() & Qt.ShiftModifier:
                    return False
                else:
                    self._do_send()
                    return True
            elif key_event.key() == Qt.Key_V and key_event.modifiers() & Qt.ControlModifier:
                clipboard = QApplication.clipboard()
                mime = clipboard.mimeData()
                if mime.hasImage():
                    img = clipboard.image()
                    if not img.isNull():
                        pix = QPixmap.fromImage(img)
                        self._set_attachment_pixmap(pix, "image/png")
                        return True
        elif obj is self._edit and event.type() == QEvent.Wheel:
            wheel_event = event
            if wheel_event.modifiers() & Qt.ControlModifier:
                delta = wheel_event.angleDelta().y()
                if delta > 0:
                    self._font_size = min(22, self._font_size + 1)
                else:
                    self._font_size = max(8, self._font_size - 1)
                self._edit.setFont(QFont("Microsoft YaHei UI", self._font_size))
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        elif event.key() == Qt.Key_F11:
            self._toggle_expand()
            return
        super().keyPressEvent(event)

    def _do_send(self):
        text = self._edit.toPlainText().strip()
        if not text and not self._attachment:
            return

        self.chat_submitted.emit(text, self._attachment)
        if text:
            self.message_sent.emit(text)

        self._edit.clear()
        self._clear_attachment()
        self.accept()

    def popup_at(self, anchor_widget=None):
        """弹出输入气泡，智能对齐"""
        if anchor_widget and anchor_widget.isVisible():
            sc = QApplication.screenAt(anchor_widget.geometry().center())
            screen = sc.availableGeometry() if sc else QApplication.primaryScreen().availableGeometry()
        else:
            screen = QApplication.primaryScreen().availableGeometry()

        w = 660 if self._is_expanded else 480
        h = 240 if self._is_expanded else 104
        self.setFixedSize(w, h)

        if anchor_widget and anchor_widget.isVisible():
            geo = anchor_widget.geometry()
            pt = geo.center()
            x = pt.x() - w // 2
            y = geo.top() - h - 10
        else:
            x = screen.left() + (screen.width() - w) // 2
            y = screen.top() + (screen.height() - h) // 2

        x = max(screen.left() + 10, min(x, screen.right() - w - 10))
        if y < screen.top() + 10:
            if anchor_widget:
                y = anchor_widget.geometry().bottom() + 10
            else:
                y = screen.top() + 30

        self.move(int(x), int(y))
        self.show()
        self.raise_()
        self.activateWindow()
        self._edit.setFocus()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        tail_h = 10.0
        tail_w = 16.0
        body_h = h - tail_h - 2.0
        r = 18.0
        pad = 2.0

        tail_cx = max(r + tail_w, min(w - r - tail_w, w / 2.0 + self._tail_offset_x))

        path = QPainterPath()
        path.moveTo(pad + r, pad)
        path.lineTo(w - pad - r, pad)
        path.arcTo(QRectF(w - pad - 2 * r, pad, 2 * r, 2 * r), 90, -90)
        path.lineTo(w - pad, body_h - r)
        path.arcTo(QRectF(w - pad - 2 * r, body_h - 2 * r, 2 * r, 2 * r), 0, -90)

        path.lineTo(tail_cx + tail_w / 2.0, body_h)
        path.lineTo(tail_cx, h - pad)
        path.lineTo(tail_cx - tail_w / 2.0, body_h)
        path.lineTo(pad + r, body_h)
        path.arcTo(QRectF(pad, body_h - 2 * r, 2 * r, 2 * r), 270, -90)
        path.lineTo(pad, pad + r)
        path.arcTo(QRectF(pad, pad, 2 * r, 2 * r), 180, -90)
        path.closeSubpath()

        painter.fillPath(path, QBrush(QColor(18, 22, 31, 248)))

        pen = QPen(QColor(111, 227, 255, 190), 1.6)
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        painter.strokePath(path, pen)
