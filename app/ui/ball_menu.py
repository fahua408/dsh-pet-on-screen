# -*- coding: utf-8 -*-
"""ball_menu.py — 扇形展开多级子菜单（智能径向外展防遮挡注释、114款动作分类大厅、鼠标滚轮顺逆时针旋转转盘）。

功能架构：
- 一级核心菜单 (main)：
    - 抚摸互动、对话输入、状态与资产 ➔、表演动作工坊 ➔、双屏模式切换、控制中心、收起菜单
- 二级状态菜单 (status)：
    - 查余额、查天气、待办清单、睡觉唤醒、返回主菜单
- 二级动作分类菜单 (actions_cat)：
    - 7 大精选分类（吃货美馔、演艺玩耍、趣味奇幻、互动回应、待机日常、工作财富、作息碎念）+ 返回主菜单
- 三级动作转盘点播 (actions_list)：
    - 承载全量 114 款官方 WebM 动作。
    - 采用【旋转拨盘（Rotary Dial）】：常驻 5 个动作槽位 + 1 个常驻返回槽位。
    - 鼠标滚轮旋转：向上顺时针滚动、向下逆时针滚动，平滑无级循环轮转所有动作。
    - 弧面微光导轨指示当前动作页码区间（如 `1-5 / 24`）。
- 径向外展注释系统 (Radial-Outward Float)：
    - Tooltip 气泡沿“球心 ➔ 按钮”的径向外侧延展向桌面空旷区弹出，配微光连接引线，彻底杜绝遮挡任何按钮！
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    Qt, QTimer, QVariantAnimation, QEasingCurve,
    QPointF, QRectF, Signal, QPoint, QRect
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QRegion, QPainterPath,
    QWheelEvent, QFont
)
from PySide6.QtWidgets import QWidget, QApplication

from .tokens import (
    SURFACE, SURFACE_HOVER, SURFACE_ACTIVE,
    BORDER, ACCENT, TEXT_PRIMARY, TEXT_MUTED,
    DANGER, BALL_SIZE
)
from .icons import draw_icon

if TYPE_CHECKING:
    from .ball import BallWindow

# 几何参数
MENU_R: float = 108.0     # 展开半径
MENU_BTN: float = 34.0    # 按钮直径

# 114 款官方完整动作数据库分类字典
ACTION_CATEGORIES: dict[str, dict] = {
    'cat_food': {
        'name': '吃货美馔',
        'desc': '🍚 吃货美馔 (24款) ➔',
        'icon': 'cat_food',
        'actions': [
            '吃白饭', '吃大闸蟹', '涮火锅', '吃饭·碗饭', '吃饭团', '吃饺子',
            '吃年糕', '吃粽子', '吃汤圆', '吃糖葫芦', '吃冰淇淋融化', '吃西瓜',
            '吃早餐', '吃午餐', '吃晚餐', '吃长寿面', '吃青团', '吃重阳糕',
            '吃腊八粥', '中秋赏月吃月饼', '期待开饭', '大口吃零食', '偷吃零食被抓住', '吃Token'
        ]
    },
    'cat_play': {
        'name': '演艺玩耍',
        'desc': '💃 演艺玩耍 (20款) ➔',
        'icon': 'cat_play',
        'actions': [
            '可爱宅舞', '优雅女仆舞', '轻快摇摆舞', '小提琴演奏', '吹笛子', '吹气球',
            '扑克魔术', '三球抛接', '下五子棋', '原地专心玩魔方', '原地蹲下玩玩具汽车',
            '荡秋千', '踢毽子', '骑木马', '抽陀螺', '玩水枪', '放风筝',
            '玩游戏气急败坏', '堆雪人', '拆礼物'
        ]
    },
    'cat_funny': {
        'name': '趣味奇幻',
        'desc': '🤪 趣味奇幻 (17款) ➔',
        'icon': 'cat_funny',
        'actions': [
            '变鸽子', '萌化小幽灵', '蓝鲸现世', '凭空生花', '动物环绕',
            '蝴蝶蜜蜂环绕头顶开花', '鲸鱼吐泡泡特效', '用鲸鱼尾巴拍打地面',
            '被落叶淹没', '被吓一跳', '装点圣诞树', '讨糖南瓜灯', '放烟花',
            '放孔明灯', '放河灯', '舞狮头', '写福字'
        ]
    },
    'cat_touch': {
        'name': '互动回应',
        'desc': '🐱 互动回应 (12款) ➔',
        'icon': 'cat_touch',
        'actions': [
            '点击回应-开心跃动', '点击回应-挠痒咯咯笑', '点击回应-元气挥手',
            '点击回应-害羞惊讶', '点击回应-傲娇生气', '撸猫', '晨间刷牙', '照镜子',
            '摇扇纳凉', '女仆屈膝礼仪', '原地跳跃抓碎头顶物品', '被鼠标拖拽悬空反馈'
        ]
    },
    'cat_daily': {
        'name': '待机日常',
        'desc': '✨ 待机日常 (16款) ➔',
        'icon': 'cat_daily',
        'actions': [
            '待机呼吸休闲', '悠闲哼歌', '超大伸懒腰', '哈欠连天', '东张西望',
            '原地敲击桌面互动', '原地漂浮踏步', '原地左转奔跑', '侧身急躁跑', '螃蟹走路',
            '开心小跑', '原地重力下蹲压缩', '原地小憩沉眠', '小幅度原地360度旋转展示',
            '整体换装试色', '是啊，吃什么'
        ]
    },
    'cat_work': {
        'name': '工作财富',
        'desc': '💼 工作财富 (16款) ➔',
        'icon': 'cat_work',
        'actions': [
            '写代码', '轻快记录', '深度思考碎碎念', '工作状态-思考冒泡', '工作状态-忙碌点按',
            '工作状态-清点归档', '工作状态-雀跃庆祝', '工作状态-原地踱步张望',
            '工作状态-垂头叹气冒汗', '收红包', '余额-金袋叮当', '余额-钱袋满溢',
            '余额-钱袋如常', '余额-数金皱眉', '余额-分文不剩', '余额-袋空如洗'
        ]
    },
    'cat_sleep': {
        'name': '作息碎念',
        'desc': '💤 作息碎念 (9款) ➔',
        'icon': 'cat_sleep',
        'actions': [
            '睡觉-开始', '睡觉-循环', '睡觉-起来', '打瞌睡被惊醒', '碎碎念-擦桌碎碎念',
            '碎碎念-发呆碎碎念', '碎碎念-对屏碎碎念', '插茱萸赏菊', '穿针乞巧'
        ]
    }
}

_ITEMS_MAIN = [
    ('touch',          '抚摸肥鱼 (摸头)'),
    ('chat',           '对话输入 (💬)'),
    ('sub_status',     '状态与资产 ➔'),
    ('sub_actions',    '表演动作工坊 ➔'),
    ('toggle_display', '双屏模式切换 (🖥️)'),
    ('panel',          '控制中心 (⚙️)'),
    ('collapse',       '收起菜单 (✕)'),
]

_ITEMS_STATUS = [
    ('status_balance', '查询余额 (💰)'),
    ('status_weather', '查询天气 (⛅)'),
    ('status_todo',    '待办事项 (📋)'),
    ('status_sleep',   '睡觉/唤醒 (💤)'),
    ('back_to_main',   '↩️ 返回主菜单'),
]

_ITEMS_ACTIONS_CAT = [
    ('cat_food',       '🍚 吃货美馔 (24款) ➔'),
    ('cat_play',       '💃 演艺玩耍 (20款) ➔'),
    ('cat_funny',      '🤪 趣味奇幻 (17款) ➔'),
    ('cat_touch',      '🐱 互动回应 (12款) ➔'),
    ('cat_daily',      '✨ 待机日常 (16款) ➔'),
    ('cat_work',       '💼 工作财富 (16款) ➔'),
    ('cat_sleep',      '💤 作息碎念 (9款) ➔'),
    ('back_to_main',   '↩️ 返回主菜单'),
]

_ICON_COLOR_DEFAULT = QColor(255, 255, 255, 230)
_ICON_COLOR_ACCENT  = QColor(111, 227, 255, 245)
_ICON_COLOR_GOLD    = QColor(255, 215, 0,   245)
_ICON_COLOR_DANGER  = QColor(255, 91,  91,  240)


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


def _out_back(t: float, s: float = 1.70158) -> float:
    t -= 1.0
    return t * t * ((s + 1.0) * t + s) + 1.0


class _ButtonState:
    """单个子按钮的运行时状态"""
    def __init__(self, key: str, tooltip: str, icon_key: str = ''):
        self.key       = key
        self.tooltip   = tooltip
        self.icon_key  = icon_key or key
        self.angle_deg = 0.0
        self.target_cx = 0.0
        self.target_cy = 0.0
        self.cx        = 0.0
        self.cy        = 0.0
        self.scale     = 0.0
        self.opacity   = 0.0
        self.hovered   = False


class BallMenu(QWidget):
    """扇形多级菜单，支持无遮挡径向外展注释与滚轮顺逆时针旋转转盘。"""

    item_picked = Signal(str)
    menu_closed = Signal()
    control_target_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)

        self._menu_level = 'main'  # 'main' | 'status' | 'actions_cat' | 'actions_list'
        self._current_cat = ''
        self._cat_actions: list[str] = []
        self._rotary_index = 0
        self._is_screen_mode: bool = True
        self._cast_mode: str = 'dual'
        self._control_target: str = 'coopanion'

        self._buttons: list[_ButtonState] = []
        self._load_buttons(self._get_main_items())

        self._ball_cx: float = 0.0
        self._ball_cy: float = 0.0
        self._last_ball_window = None

        self._anims: list[QVariantAnimation] = []
        self._is_open = False
        self._hovered_idx = -1

        self.hide()

    def set_screen_mode(self, is_screen_mode: bool):
        self._is_screen_mode = is_screen_mode

    def set_pet_mode(self, mode: str, control_target: str = 'coopanion'):
        """根据当前投放的桌宠类型与控制目标动态重载菜单。"""
        self._cast_mode = mode
        self._control_target = control_target
        if self._is_open and self._menu_level == 'main':
            self._load_buttons(self._get_main_items())
            self._layout_and_open()

    def _get_main_items(self) -> list[tuple[str, str]]:
        display_desc = (
            '双屏模式：水冷屏运作 (点击切换主桌面)'
            if getattr(self, '_is_screen_mode', True)
            else '双屏模式：主桌面运作 (点击切换水冷屏)'
        )
        items = []

        # 核心需求：要是同时有两个桌宠的话，在此时多显示一个桌宠控制切换按键，要是只开一个的话不用显示
        if getattr(self, '_cast_mode', 'dual') == 'dual':
            target = getattr(self, '_control_target', 'coopanion')
            if target == 'coopanion':
                items.append(('switch_target', '🔄 控制切换: [当前: 大肥鱼 ➔ 切为女仆]'))
            else:
                items.append(('switch_target', '🔄 控制切换: [当前: 蓝毛女仆 ➔ 切为肥鱼]'))

        # 依据当前活跃控制目标填充专属菜单
        active_target = self._control_target if getattr(self, '_cast_mode', 'dual') == 'dual' else self._cast_mode

        if active_target == 'coopanion':
            items.extend([
                ('touch',          '抚摸大肥鱼 (摸头)'),
                ('chat',           '对话输入 (💬)'),
                ('voice',          '语音输入 (🎙️ Alt×2)'),
                ('toggle_display', display_desc),
                ('panel',          '控制中心 (⚙️)'),
                ('collapse',       '收起菜单 (✕)'),
            ])
        else:  # dsh-pet
            items.extend([
                ('touch',          '抚摸小女仆 (摸头)'),
                ('chat',           '对话输入 (💬)'),
                ('sub_status',     '状态与资产 ➔'),
                ('sub_actions',    '表演动作工坊 ➔'),
                ('toggle_display', display_desc),
                ('panel',          '控制中心 (⚙️)'),
                ('collapse',       '收起菜单 (✕)'),
            ])

        return items

    def _load_buttons(self, items: list[tuple[str, str]]):
        self._buttons = [_ButtonState(k, t) for k, t in items]

    def _setup_rotary_action_buttons(self):
        """配置三级动作旋转拨盘的 5 个动作槽位 + 1 个返回槽位"""
        if not self._cat_actions:
            return
        n = len(self._cat_actions)
        slots: list[_ButtonState] = []
        cat_icon = ACTION_CATEGORIES.get(self._current_cat, {}).get('icon', 'anim_action')

        # 5 个旋转展示的动作槽位
        for i in range(min(5, n)):
            act_idx = (self._rotary_index + i) % n
            act_name = self._cat_actions[act_idx]
            btn = _ButtonState(f'anim:{act_name}', act_name, icon_key=cat_icon)
            slots.append(btn)

        # 第 6 个槽位：固定为返回分类
        cat_name = ACTION_CATEGORIES.get(self._current_cat, {}).get('name', '分类')
        slots.append(_ButtonState('back_to_cat', f'↩️ 返回分类 ({cat_name})', icon_key='back_to_cat'))
        self._buttons = slots

    # ================================================================
    # 动态定位与智能扇区展开
    # ================================================================

    def show_at(self, ball_window: 'BallWindow'):
        """根据悬浮球当前所在屏幕绝对位置计算最优扇区并展开"""
        if self._is_open:
            self.hide_menu()
            return

        self._menu_level = 'main'
        self._load_buttons(self._get_main_items())
        self._last_ball_window = ball_window
        self._layout_and_open()

    def _layout_and_open(self):
        if not self._last_ball_window:
            return

        screen = QApplication.primaryScreen().geometry()
        ball_rect = self._last_ball_window.geometry()

        ball_cx_g = ball_rect.x() + self._last_ball_window.width() / 2.0
        ball_cy_g = ball_rect.y() + self._last_ball_window.height() / 2.0

        # 留足 140px 边距，确保外侧径向延展的文字气泡不被窗口剪切
        margin = int(MENU_R + MENU_BTN + 140)
        win_x = max(0, int(ball_cx_g - margin))
        win_y = max(0, int(ball_cy_g - margin))
        win_w = min(screen.width() - win_x, int(margin * 2))
        win_h = min(screen.height() - win_y, int(margin * 2))

        self.setGeometry(win_x, win_y, win_w, win_h)

        self._ball_cx = ball_cx_g - win_x
        self._ball_cy = ball_cy_g - win_y

        # 计算最优扇区角度
        n = max(1, len(self._buttons) - 1)
        if ball_cx_g >= screen.width() / 2.0:
            if ball_cy_g > screen.height() - 170:
                start_angle, span = 165.0, 95.0     # 靠下偏向左上
            elif ball_cy_g < 170:
                start_angle, span = 100.0, 95.0     # 靠上偏向左下
            else:
                start_angle, span = 115.0, 130.0    # 对称向左展开 (跨度 130°)
        else:
            if ball_cy_g > screen.height() - 170:
                start_angle, span = 280.0, 95.0     # 靠下偏向右上
            elif ball_cy_g < 170:
                start_angle, span = -10.0, 95.0     # 靠上偏向右下
            else:
                start_angle, span = -65.0, 130.0    # 对称向右展开

        self._start_angle = start_angle
        self._span = span

        step = span / n
        for i, btn in enumerate(self._buttons):
            deg = start_angle + i * step
            btn.angle_deg = deg
            rad = math.radians(deg)
            btn.target_cx = self._ball_cx + MENU_R * math.cos(rad)
            btn.target_cy = self._ball_cy + MENU_R * math.sin(rad)
            btn.cx = self._ball_cx
            btn.cy = self._ball_cy
            btn.scale = 0.0
            btn.opacity = 0.0
            btn.hovered = False

        self.clearMask()
        self.show()
        self.raise_()
        self._is_open = True
        self._animate_open()

    def hide_menu(self):
        """收起菜单"""
        if not self._is_open:
            return
        self._stop_all_anims()
        self._animate_close()

    def _switch_level(self, level: str, cat_key: str = ''):
        """在多级菜单体系之间平滑切换"""
        self._menu_level = level
        self._hovered_idx = -1

        if level == 'status':
            self._load_buttons(_ITEMS_STATUS)
        elif level == 'actions_cat':
            self._load_buttons(_ITEMS_ACTIONS_CAT)
        elif level == 'actions_list':
            self._current_cat = cat_key
            self._cat_actions = ACTION_CATEGORIES.get(cat_key, {}).get('actions', [])
            self._rotary_index = 0
            self._setup_rotary_action_buttons()
        else:
            self._load_buttons(self._get_main_items())

        self._layout_and_open()

    # ================================================================
    # 鼠标滚轮旋转拨盘 (Rotary Dial)
    # ================================================================

    def wheelEvent(self, event: QWheelEvent):
        """监听鼠标滚轮：在三级动作列表实现顺时针/逆时针旋转转盘"""
        if self._menu_level != 'actions_list' or not self._cat_actions:
            super().wheelEvent(event)
            return

        delta = event.angleDelta().y()
        if abs(delta) < 15:
            return

        # 向上顺时针旋转 (-1 步)，向下逆时针旋转 (+1 步)
        step = -1 if delta > 0 else 1
        self._step_rotary(step)
        event.accept()

    def _step_rotary(self, step: int):
        """旋转拨盘步进：更新 5 个动作槽位并赋予微弹动反馈"""
        n = len(self._cat_actions)
        if n <= 1:
            return

        self._rotary_index = (self._rotary_index + step) % n

        # 重新装配前 5 个插槽并触发触感微弹
        cat_icon = ACTION_CATEGORIES.get(self._current_cat, {}).get('icon', 'anim_action')
        for i in range(min(5, n)):
            act_idx = (self._rotary_index + i) % n
            act_name = self._cat_actions[act_idx]
            btn = self._buttons[i]
            btn.key = f'anim:{act_name}'
            btn.tooltip = act_name
            btn.icon_key = cat_icon
            btn.scale = 1.15  # 模拟机械棘轮顿挫感

        # 刷新遮罩与画面
        self._update_mask()
        self.update()

        # 恢复平滑大小动画
        anim = QVariantAnimation(self)
        anim.setStartValue(1.15)
        anim.setEndValue(1.0)
        anim.setDuration(120)
        anim.setEasingCurve(QEasingCurve.OutQuad)

        def on_step_anim(v):
            for i in range(min(5, n)):
                self._buttons[i].scale = v
            self.update()

        anim.valueChanged.connect(on_step_anim)
        anim.start()
        self._anims.append(anim)

    # ================================================================
    # 动画系统
    # ================================================================

    def _stop_all_anims(self):
        for a in self._anims:
            a.stop()
        self._anims.clear()

    def _animate_open(self):
        """OutBack 弹性展开"""
        self._stop_all_anims()
        self.clearMask()
        total_ms = 260
        delay_per = 16
        finished_count = [0]

        for i, btn in enumerate(self._buttons):
            delay = i * delay_per
            dur = total_ms

            anim = QVariantAnimation(self)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setDuration(dur + delay)
            anim.setEasingCurve(QEasingCurve.Linear)

            def make_handler(b, d, dur_val, tcx, tcy, bcx, bcy):
                def on_val(v):
                    t_local = max(0.0, min(1.0, (v * (dur_val + d) - d) / dur_val))
                    eased = _out_back(t_local)
                    b.cx = bcx + eased * (tcx - bcx)
                    b.cy = bcy + eased * (tcy - bcy)
                    b.scale = max(0.0, min(1.15, eased))
                    b.opacity = min(1.0, t_local * 1.5)
                return on_val

            anim.valueChanged.connect(
                make_handler(btn, delay, dur, btn.target_cx, btn.target_cy, self._ball_cx, self._ball_cy)
            )
            anim.valueChanged.connect(lambda _: self.update())

            def make_open_fin(count_ref, total):
                def on_fin():
                    count_ref[0] += 1
                    if count_ref[0] >= total:
                        self._update_mask()
                return on_fin

            anim.finished.connect(make_open_fin(finished_count, len(self._buttons)))
            anim.start()
            self._anims.append(anim)

    def _animate_close(self):
        """快速向球心收拢"""
        self._stop_all_anims()
        dur = 130
        finished_count = [0]

        for btn in self._buttons:
            anim = QVariantAnimation(self)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setDuration(dur)
            anim.setEasingCurve(QEasingCurve.InQuad)

            def make_close_handler(b, scx, scy, ssc, sop, bcx, bcy):
                def on_val(v):
                    b.cx = scx + v * (bcx - scx)
                    b.cy = scy + v * (bcy - scy)
                    b.scale = max(0.0, ssc * (1.0 - v))
                    b.opacity = max(0.0, sop * (1.0 - v))
                return on_val

            anim.valueChanged.connect(
                make_close_handler(btn, btn.cx, btn.cy, btn.scale, btn.opacity, self._ball_cx, self._ball_cy)
            )
            anim.valueChanged.connect(lambda _: self.update())

            def make_fin(count_ref, total):
                def on_fin():
                    count_ref[0] += 1
                    if count_ref[0] >= total:
                        self._is_open = False
                        self.clearMask()
                        self.hide()
                        self.menu_closed.emit()
                return on_fin

            anim.finished.connect(make_fin(finished_count, len(self._buttons)))
            anim.start()
            self._anims.append(anim)

    # ================================================================
    # 绘制与图标
    # ================================================================

    def _calc_tooltip_rect(self, btn: _ButtonState) -> tuple[int, int, int, int, float, float]:
        """计算外侧径向延展（Radial-Outward）零遮挡注释坐标 (tx, ty, tw, th, ux, uy)"""
        fm = self.fontMetrics()
        tw = fm.horizontalAdvance(btn.tooltip) + 18
        th = 24
        cx = btn.target_cx if btn.target_cx != 0 else btn.cx
        cy = btn.target_cy if btn.target_cy != 0 else btn.cy
        r = (MENU_BTN / 2.0) * max(0.5, btn.scale)

        dx = cx - self._ball_cx
        dy = cy - self._ball_cy
        dist = math.hypot(dx, dy)
        if dist > 1.0:
            ux = dx / dist
            uy = dy / dist
        else:
            ux, uy = -1.0, 0.0

        # 向外侧径向延伸，完全避开圆弧轨迹与相邻按钮
        offset_dist = r + 14.0 + tw / 2.0
        tx_center = cx + ux * offset_dist
        ty_center = cy + uy * (r + 10.0)

        tx = int(tx_center - tw / 2.0)
        ty = int(ty_center - th / 2.0)

        tx = max(6, min(self.width() - tw - 6, tx))
        ty = max(6, min(self.height() - th - 6, ty))
        return tx, ty, tw, th, ux, uy

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 1. 在三级动作转盘状态下绘制微光导轨刻度与旋转提示
        if self._menu_level == 'actions_list' and self._buttons and self._is_open:
            painter.save()
            # 绘制扇形微光导轨
            track_pen = QPen(QColor(111, 227, 255, 55), 1.6, Qt.DashLine)
            painter.setPen(track_pen)
            painter.setBrush(Qt.NoBrush)
            r_track = MENU_R
            arc_rect = QRectF(self._ball_cx - r_track, self._ball_cy - r_track, r_track * 2, r_track * 2)
            # span 跨度画弧
            painter.drawArc(arc_rect, int(-self._start_angle * 16), int(-self._span * 16))

            # 绘制顶部 HUD 旋转提示
            n = len(self._cat_actions)
            cur_start = self._rotary_index + 1
            cur_end = min(self._rotary_index + 5, n) if n >= 5 else n
            cat_name = ACTION_CATEGORIES.get(self._current_cat, {}).get('name', '动作')
            hud_tip = f"⚡ {cat_name} · 滚轮旋钮 ({cur_start}-{cur_end}/{n})"

            font = painter.font()
            font.setPointSize(8)
            font.setBold(True)
            painter.setFont(font)
            fm = painter.fontMetrics()
            htw = fm.horizontalAdvance(hud_tip) + 14
            hth = 20

            # 居中放置在扇面顶端空位
            htx = int(self._ball_cx - MENU_R * 0.75 - htw / 2.0)
            hty = int(self._ball_cy - MENU_R - 16)
            painter.setBrush(QBrush(QColor(15, 23, 42, 220)))
            painter.setPen(QPen(QColor(111, 227, 255, 140), 1))
            painter.drawRoundedRect(QRectF(htx, hty, htw, hth), 5, 5)
            painter.setPen(QColor(111, 227, 255, 230))
            painter.drawText(QRectF(htx, hty, htw, hth), Qt.AlignCenter, hud_tip)
            painter.restore()

        # 2. 绘制各个子按钮
        for btn in self._buttons:
            if btn.opacity <= 0.02:
                continue

            painter.save()
            painter.setOpacity(btn.opacity)

            cx, cy = btn.cx, btn.cy
            r = (MENU_BTN / 2.0) * btn.scale

            # 胶囊圆形底色
            if btn.hovered:
                bg = _parse_rgba(SURFACE_HOVER)
                border_color = QColor(111, 227, 255, 235)
            else:
                bg = _parse_rgba(SURFACE)
                border_color = _parse_rgba(BORDER)

            painter.setBrush(QBrush(bg))
            painter.setPen(QPen(border_color, 1.4))
            painter.drawEllipse(QPointF(cx, cy), r, r)

            # 图标
            if btn.scale > 0.35:
                if btn.key in ('collapse', 'back_to_main', 'back_to_cat'):
                    icon_color = _ICON_COLOR_DANGER
                elif btn.key in ('sub_status', 'status_balance'):
                    icon_color = _ICON_COLOR_GOLD
                elif btn.key in ('panel', 'chat', 'touch', 'sub_actions'):
                    icon_color = _ICON_COLOR_ACCENT
                elif btn.key.startswith('cat_') or btn.key.startswith('anim:'):
                    icon_color = _ICON_COLOR_ACCENT if btn.hovered else _ICON_COLOR_DEFAULT
                else:
                    icon_color = _ICON_COLOR_DEFAULT

                draw_icon(painter, btn.icon_key, cx, cy, r * 1.35, icon_color)

            # 3. 悬停时绘制【外侧径向延展】零遮挡 Tooltip 提示浮字与微光引线
            if btn.hovered and btn.opacity > 0.8:
                tip = btn.tooltip
                tx, ty, tw, th, ux, uy = self._calc_tooltip_rect(btn)

                painter.save()
                painter.setOpacity(1.0)
                font = painter.font()
                font.setPointSize(9)
                font.setBold(True)
                painter.setFont(font)

                # 绘制极客感暗黑磨砂底板 + 极光青色微发光边框
                painter.setBrush(QBrush(QColor(15, 23, 42, 240)))
                painter.setPen(QPen(QColor(111, 227, 255, 210), 1.2))
                painter.drawRoundedRect(QRectF(tx, ty, tw, th), 6, 6)

                # 绘制细线微光指示虚线 (文字气泡 ➔ 对应按钮)
                painter.setPen(QPen(QColor(111, 227, 255, 130), 1.0, Qt.DashLine))
                p_box = QPointF(tx + tw if cx > tx + tw else (tx if cx < tx else cx),
                                ty + th / 2.0)
                p_btn = QPointF(cx - ux * (r + 1), cy - uy * (r + 1))
                painter.drawLine(p_box, p_btn)

                # 绘制文字
                painter.setPen(QColor(255, 255, 255, 245))
                painter.drawText(QRectF(tx, ty, tw, th), Qt.AlignCenter, tip)
                painter.restore()

            painter.restore()

        painter.end()

    # ================================================================
    # 交互与掩码
    # ================================================================

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            idx = self._hit_test(event.position())
            if idx >= 0:
                key = self._buttons[idx].key
                if key == 'collapse':
                    self.hide_menu()
                elif key == 'switch_target':
                    # 切换当前双宠控制目标并原地重绘
                    self._control_target = 'dsh' if self._control_target == 'coopanion' else 'coopanion'
                    self.control_target_changed.emit(self._control_target)
                    self._load_buttons(self._get_main_items())
                    self._layout_and_open()
                elif key == 'sub_status':
                    self._switch_level('status')
                elif key == 'sub_actions':
                    self._switch_level('actions_cat')
                elif key == 'back_to_main':
                    self._switch_level('main')
                elif key == 'back_to_cat':
                    self._switch_level('actions_cat')
                elif key.startswith('cat_'):
                    self._switch_level('actions_list', cat_key=key)
                else:
                    self.hide_menu()
                    self.item_picked.emit(key)
            else:
                self.hide_menu()

    def mouseMoveEvent(self, event):
        idx = self._hit_test(event.position())
        changed = False
        for i, btn in enumerate(self._buttons):
            new_hov = (i == idx)
            if btn.hovered != new_hov:
                btn.hovered = new_hov
                changed = True
        if changed:
            self._update_mask()
            self.update()

    def _hit_test(self, pos) -> int:
        x, y = pos.x(), pos.y()
        for i, btn in enumerate(self._buttons):
            if btn.opacity < 0.15:
                continue
            r = (MENU_BTN / 2.0) + 4.0
            if math.hypot(x - btn.target_cx, y - btn.target_cy) <= r:
                return i
        return -1

    def _update_mask(self):
        """应用掩码：包含所有按钮圆盘 + 外侧径向 Tooltip 浮条，周围区域 100% 透传桌面"""
        if not self._is_open:
            self.clearMask()
            return
        region = QRegion()
        r = int(MENU_BTN / 2.0) + 4
        for btn in self._buttons:
            region = region.united(
                QRegion(int(btn.target_cx - r), int(btn.target_cy - r), r * 2, r * 2, QRegion.Ellipse)
            )
            if btn.hovered:
                tx, ty, tw, th, _, _ = self._calc_tooltip_rect(btn)
                region = region.united(QRegion(tx - 3, ty - 3, tw + 6, th + 6))
        self.setMask(region)
