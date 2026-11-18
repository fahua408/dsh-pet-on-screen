# tokens.py — 配色常量与 QSS 样式表生成器
# 视觉设计令牌，所有 UI 模块从此处导入，禁止硬编码颜色

# ——— 配色令牌（Design Tokens）———
SURFACE          = "rgba(22, 24, 29, 0.92)"
SURFACE_HOVER    = "rgba(38, 41, 50, 0.95)"
SURFACE_ACTIVE   = "rgba(55, 58, 68, 0.98)"
BALL_IDLE        = "rgba(50, 52, 60, 0.65)"
BALL_HOVER       = "rgba(68, 71, 83, 0.88)"
BORDER           = "rgba(255, 255, 255, 0.08)"
ACCENT           = "#6FE3FF"
TEXT_PRIMARY     = "#F0F3F8"
TEXT_MUTED       = "#8C95A3"
TEXT_ACCENT      = "#6FE3FF"
ICON_DEFAULT     = "rgba(255, 255, 255, 0.90)"
DANGER           = "#FF5B5B"

# ——— 尺寸令牌 ———
BALL_SIZE   = 46
MENU_R      = 62
MENU_BTN    = 38
PANEL_W     = 340        # 面板宽度
PANEL_H     = 460        # 面板高度
RADIUS      = 14
PREVIEW_W   = 160        # 实时缩略图宽度（像素，4:3 等比 640×480）
PREVIEW_H   = 120        # 实时缩略图高度（像素）

# ——— 体型缩放档位 ———
SCALES = (1.0, 1.25, 1.6, 2.0, 2.5, 3.2)


def build_qss() -> str:
    """返回完整的 Qt StyleSheet 字符串。
    覆盖 QSlider、QCheckBox、QPushButton、QLabel、QScrollBar 等控件风格。
    严格遵循极简磨砂设计规范，禁止渐变、发光、box-shadow 等。
    """
    return f"""
/* ===== 全局字体 ===== */
* {{
    font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif;
    font-size: 13px;
    color: {TEXT_PRIMARY};
    outline: none;
    border: none;
}}

/* ===== QLabel ===== */
QLabel {{
    background: transparent;
    color: {TEXT_PRIMARY};
}}
QLabel[class="muted"] {{
    color: {TEXT_MUTED};
    font-size: 11px;
    letter-spacing: 1px;
}}
QLabel[class="accent"] {{
    color: {TEXT_ACCENT};
}}

/* ===== QPushButton ===== */
QPushButton {{
    background: {SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 5px 14px;
    font-size: 13px;
}}
QPushButton:hover {{
    background: {SURFACE_HOVER};
    border: 1px solid rgba(255,255,255,0.14);
}}
QPushButton:pressed {{
    background: {SURFACE_ACTIVE};
}}
QPushButton:disabled {{
    color: {TEXT_MUTED};
    background: rgba(22, 24, 29, 0.50);
    border-color: rgba(255,255,255,0.04);
}}
QPushButton:checked {{
    background: rgba(111, 227, 255, 0.15);
    border: 1px solid rgba(111, 227, 255, 0.45);
    color: {ACCENT};
}}
QPushButton[class="danger"] {{
    border-color: rgba(255, 91, 91, 0.45);
    color: {DANGER};
}}
QPushButton[class="danger"]:hover {{
    background: rgba(255, 91, 91, 0.12);
}}

/* ===== QSlider ===== */
QSlider::groove:horizontal {{
    height: 4px;
    background: rgba(255,255,255,0.10);
    border-radius: 2px;
    margin: 0px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
    height: 4px;
}}
QSlider::add-page:horizontal {{
    background: rgba(255,255,255,0.08);
    border-radius: 2px;
    height: 4px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    border: none;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{
    background: #9AEEFF;
    width: 18px;
    height: 18px;
    margin: -7px 0;
    border-radius: 9px;
}}

/* ===== QCheckBox ===== */
QCheckBox {{
    color: {TEXT_PRIMARY};
    spacing: 8px;
    font-size: 13px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1.5px solid rgba(255,255,255,0.20);
    background: rgba(255,255,255,0.05);
}}
QCheckBox::indicator:hover {{
    border-color: rgba(111,227,255,0.50);
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    image: none;
}}
QCheckBox::indicator:checked:hover {{
    background: #9AEEFF;
    border-color: #9AEEFF;
}}

/* ===== QScrollBar Vertical ===== */
QScrollBar:vertical {{
    background: transparent;
    width: 4px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(255,255,255,0.14);
    border-radius: 2px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(255,255,255,0.28);
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: transparent;
}}

/* ===== QScrollBar Horizontal ===== */
QScrollBar:horizontal {{
    background: transparent;
    height: 4px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: rgba(255,255,255,0.14);
    border-radius: 2px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: rgba(255,255,255,0.28);
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ===== QProgressBar ===== */
QProgressBar {{
    background: rgba(255,255,255,0.08);
    border: 1px solid {BORDER};
    border-radius: 5px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 4px;
}}

/* ===== QColorDialog / QFileDialog ===== */
QDialog {{
    background: rgb(28, 30, 36);
}}

/* ===== ToolTip ===== */
QToolTip {{
    background: rgb(38, 41, 50);
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 12px;
}}
"""
