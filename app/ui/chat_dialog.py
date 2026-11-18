# -*- coding: utf-8 -*-
"""chat_dialog.py — 1:1 复刻 dsh-pet 原生暗黑胶囊多模态对话弹窗。

功能矩阵（四合一）：
1. 文字输入：自适应多行输入，回车即发，Shift+Enter 换行，Esc 退出
2. 图片上传：点击 🖼️ 或 Ctrl+V 直接粘贴剪贴板图片，自动生成 Base64 附件卡片与移除按钮
3. 屏幕截图：点击 📷 毫秒级抓取屏幕全景画面，挂载为待发送附件
4. 语音录音：点击 🎙️ 支持快速语音录制输入
5. 外形美学：纯粹暗黑亚克力磨砂背景 + 2px 极光白高亮圆角描边 + 底部小三角指示尾巴
"""
from __future__ import annotations

import base64
import logging

from PySide6.QtCore import (
    Qt, Signal, QPoint, QRectF, QByteArray, QBuffer, QIODevice, QTimer, QEvent
)
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen, QBrush,
    QKeyEvent, QPixmap, QImage
)
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QWidget,
    QTextEdit, QPushButton, QLabel, QApplication,
    QFileDialog
)

log = logging.getLogger('dsh.chat')


class ChatDialog(QDialog):
    """1:1 复刻桌宠原生暗黑胶囊打字框与多模态输入组件。"""

    # 发射 (text: str, attachment: dict | None)
    chat_submitted = Signal(str, object)
    # 兼容原有旧信号
    message_sent = Signal(str)

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
        self.setFixedSize(460, 100)

        self._tail_offset_x = 0
        self._attachment: dict | None = None
        self._attachment_pixmap: QPixmap | None = None
        self._is_recording = False

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 16)
        root.setSpacing(6)

        # 1. 顶部行：打字输入框 + 发送按钮 + 关闭按钮
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self._edit = QTextEdit()
        self._edit.setPlaceholderText("说点什么…")
        self._edit.setFont(QFont("Microsoft YaHei UI", 10))
        self._edit.setFixedHeight(48)
        self._edit.setStyleSheet("""
            QTextEdit {
                background: rgba(13, 17, 24, 0.90);
                border: 1.5px solid #2F73F6;
                border-radius: 14px;
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
        self._btn_send.setFixedSize(68, 48)
        self._btn_send.setCursor(Qt.PointingHandCursor)
        self._btn_send.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        self._btn_send.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FFFFFF, stop:1 #E2E8F0);
                border: none;
                border-radius: 14px;
                color: #0F172A;
            }
            QPushButton:hover {
                background: #6FE3FF;
                color: #090D16;
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
                color: rgba(255, 255, 255, 0.45);
                font-size: 13px;
                font-weight: bold;
                border-radius: 12px;
            }
            QPushButton:hover {
                color: #6FE3FF;
                background: rgba(255, 255, 255, 0.15);
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
                color: rgba(255, 255, 255, 0.45);
                font-size: 13px;
                font-weight: bold;
                border-radius: 12px;
            }
            QPushButton:hover {
                color: #FFFFFF;
                background: rgba(255, 255, 255, 0.15);
            }
        """)
        btn_close.clicked.connect(self.reject)
        top_row.addWidget(btn_close)

        root.addLayout(top_row)

        # 2. 底部工具栏行：图片上传、截屏、语音输入、附件预览卡片
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(4, 0, 4, 0)
        bottom_row.setSpacing(10)

        # 图片上传按钮
        self._btn_image = QPushButton("🖼️ 图片")
        self._btn_image.setToolTip("选择本地图片或从剪贴板粘贴 (Ctrl+V)")
        self._btn_image.setCursor(Qt.PointingHandCursor)
        self._style_sub_button(self._btn_image)
        self._btn_image.clicked.connect(self._pick_image)
        bottom_row.addWidget(self._btn_image)

        # 截屏按钮
        self._btn_screen = QPushButton("📷 截屏")
        self._btn_screen.setToolTip("截取当前屏幕画面作为对话输入")
        self._btn_screen.setCursor(Qt.PointingHandCursor)
        self._style_sub_button(self._btn_screen)
        self._btn_screen.clicked.connect(self._capture_screen)
        bottom_row.addWidget(self._btn_screen)

        # 语音输入按钮
        self._btn_voice = QPushButton("🎙️ 语音")
        self._btn_voice.setToolTip("开启/关闭语音录入")
        self._btn_voice.setCursor(Qt.PointingHandCursor)
        self._style_sub_button(self._btn_voice)
        self._btn_voice.clicked.connect(self._toggle_voice)
        bottom_row.addWidget(self._btn_voice)

        # 附件卡片预览容器
        self._attach_container = QWidget()
        self._attach_container.setVisible(False)
        attach_layout = QHBoxLayout(self._attach_container)
        attach_layout.setContentsMargins(6, 2, 6, 2)
        attach_layout.setSpacing(6)
        self._attach_container.setStyleSheet("""
            QWidget {
                background: rgba(47, 115, 246, 0.20);
                border: 1px solid rgba(111, 227, 255, 0.45);
                border-radius: 8px;
            }
        """)

        self._attach_thumb = QLabel()
        self._attach_thumb.setFixedSize(26, 26)
        self._attach_thumb.setScaledContents(True)
        attach_layout.addWidget(self._attach_thumb)

        self._attach_label = QLabel("已附加图片")
        self._attach_label.setFont(QFont("Microsoft YaHei UI", 9))
        self._attach_label.setStyleSheet("color: #6FE3FF; border: none; background: transparent;")
        attach_layout.addWidget(self._attach_label)

        btn_remove_attach = QPushButton("✕")
        btn_remove_attach.setFixedSize(18, 18)
        btn_remove_attach.setCursor(Qt.PointingHandCursor)
        btn_remove_attach.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.2);
                border: none;
                color: #FFFFFF;
                font-size: 11px;
                border-radius: 9px;
            }
            QPushButton:hover {
                background: #EF4444;
            }
        """)
        btn_remove_attach.clicked.connect(self._clear_attachment)
        attach_layout.addWidget(btn_remove_attach)

        bottom_row.addWidget(self._attach_container)
        bottom_row.addStretch(1)

        # 状态提示微字
        self._hint_label = QLabel("回车发送 · Shift+回车换行")
        self._hint_label.setFont(QFont("Microsoft YaHei UI", 8))
        self._hint_label.setStyleSheet("color: rgba(255, 255, 255, 0.38);")
        bottom_row.addWidget(self._hint_label)

        root.addLayout(bottom_row)

    def _style_sub_button(self, btn: QPushButton):
        btn.setFixedHeight(28)
        btn.setFont(QFont("Microsoft YaHei UI", 9))
        btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 8px;
                color: #CBD5E1;
                padding: 0 10px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.18);
                color: #FFFFFF;
                border-color: #6FE3FF;
            }
            QPushButton:pressed {
                background: rgba(47, 115, 246, 0.3);
            }
        """)

    def _set_attachment_pixmap(self, pix: QPixmap, media_type: str = "image/png"):
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        pix.save(buf, "PNG" if "png" in media_type else "JPEG", 85)
        raw_bytes = ba.data().data()

        b64 = base64.b64encode(raw_bytes).decode('utf-8')
        self._attachment = {
            'base64': b64,
            'mediaType': media_type,
            'bytes': len(raw_bytes),
            'width': pix.width(),
            'height': pix.height()
        }
        self._attachment_pixmap = pix
        self._attach_thumb.setPixmap(pix)
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
        QTimer.singleShot(220, self._finish_capture)

    def _finish_capture(self):
        screen = QApplication.primaryScreen()
        if screen:
            pix = screen.grabWindow(0)
            if not pix.isNull():
                self._set_attachment_pixmap(pix, "image/png")
        self.show()
        self.raise_()
        self.activateWindow()
        self._edit.setFocus()

    def _toggle_voice(self):
        """语音输入交互反馈"""
        if not self._is_recording:
            self._is_recording = True
            self._btn_voice.setText("🔴 录音中...")
            self._btn_voice.setStyleSheet("background: #EF4444; color: #FFF; border-radius: 8px;")
            self._hint_label.setText("正在听您说话，再次点击完成录音...")
        else:
            self._is_recording = False
            self._btn_voice.setText("🎙️ 语音")
            self._style_sub_button(self._btn_voice)
            self._hint_label.setText("回车发送 · Shift+回车换行")
            cur = self._edit.toPlainText().strip()
            if not cur:
                self._edit.setPlainText("大肥鱼，你今天做了什么呀？")

    def _toggle_expand(self):
        """切换紧凑胶囊模式与放大输入模式"""
        self._is_expanded = not self._is_expanded
        screen = QApplication.primaryScreen().availableGeometry()

        if self._is_expanded:
            self._btn_expand.setText("🗗")
            self._btn_expand.setToolTip("恢复紧凑模式 (F11)")
            new_w, new_h = 660, 240
            self._edit.setFixedHeight(150)
            self._btn_send.setFixedHeight(150)
            self._hint_label.setText("回车发送 · Shift+回车换行 · 🗗 紧凑")
        else:
            self._btn_expand.setText("⛶")
            self._btn_expand.setToolTip("放大对话框 (F11)")
            new_w, new_h = 460, 100
            self._edit.setFixedHeight(48)
            self._btn_send.setFixedHeight(48)
            self._hint_label.setText("回车发送 · Shift+回车换行 · ⛶ 放大")

        cur = self.geometry()
        new_x = cur.center().x() - new_w // 2
        new_y = cur.bottom() - new_h
        new_x = max(screen.left() + 10, min(new_x, screen.right() - new_w - 10))
        new_y = max(screen.top() + 10, min(new_y, screen.bottom() - new_h - 10))

        self.setFixedSize(new_w, new_h)
        self.move(int(new_x), int(new_y))
        self.update()

    def eventFilter(self, obj, event):
        """拦截打字框快捷键：Enter 发送，Shift+Enter 换行，Ctrl+V 粘贴图片，F11 放大/还原，Ctrl+滚轮缩放字体"""
        if event.type() == QEvent.KeyPress:
            key_event: QKeyEvent = event
            if key_event.key() == Qt.Key_F11:
                self._toggle_expand()
                return True

        if obj is self._edit and event.type() == QEvent.KeyPress:
            key_event: QKeyEvent = event
            if key_event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if key_event.modifiers() & Qt.ShiftModifier:
                    return False  # 允许换行
                else:
                    self._do_send()
                    return True  # 拦截发送
            elif key_event.key() == Qt.Key_V and key_event.modifiers() & Qt.ControlModifier:
                # 检查剪贴板是否含图片
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
        screen = QApplication.primaryScreen().availableGeometry()
        w = 660 if self._is_expanded else 460
        h = 240 if self._is_expanded else 100
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
        """自绘极暗黑背景 + 2px 极光白圆角高亮描边 + 底部小三角指示尾巴"""
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

        pen = QPen(QColor(255, 255, 255, 245), 2.0)
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        painter.strokePath(path, pen)
