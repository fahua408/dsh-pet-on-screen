# -*- coding: utf-8 -*-
r"""main.py — 大肥鱼桌宠钛坦屏投放工具主控制器
主入口：初始化 Qt Application，装配多桌宠投放调度中心、Playwright 舞台渲染与 HID 推流引擎，装配自适应悬浮球与控制面板。

用法（开发阶段）：
    python E:\big_fish\screen\tcomas\unified_work\app\main.py
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

# ---- 确保 app/ 目录在 sys.path，并将 bin/ 加入 PATH ----
_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

_BIN_DIR = _APP_DIR / 'bin'
if _BIN_DIR.exists():
    os.environ['PATH'] = str(_BIN_DIR) + os.pathsep + os.environ.get('PATH', '')
if hasattr(sys, '_MEIPASS'):
    _internal_bin = Path(sys._MEIPASS) / 'bin'
    if _internal_bin.exists():
        os.environ['PATH'] = str(_internal_bin) + os.pathsep + os.environ.get('PATH', '')

# ---- 核心配置与底层模块 ----
from config import AppConfig, Settings, load_config, save_config, get_settings
from core.device import DeviceLock
from core.pusher import DataPusher, PusherSignals
from core.dsh_client import DshClient, DshSignals
from core.dsh_renderer import DshRendererThread, DshRenderSignals
from core.flash_bridge import FlashBridge, FlashSignals
from core.win32_guard import (
    sync_desktop_pets,
    restore_all_desktop_pets,
    trigger_coopanion_voice,
    trigger_dsh_chat,
    trigger_dsh_voice,
    trigger_dsh_sleep,
    touch_desktop_pet
)

# ---- UI 模块 ----
from ui.ball import BallWindow
from ui.ball_menu import BallMenu
from ui.panel import PanelWindow
from ui.dashboard import DashboardWindow
from ui.chat_dialog import ChatDialog

_LOG_DIR = Path(os.environ.get('APPDATA', '.')) / 'BigFishTitanConsole'
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / 'app.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(str(_LOG_FILE), encoding='utf-8', mode='a'),
        logging.StreamHandler(sys.stdout) if sys.stdout else logging.NullHandler(),
    ],
)
log = logging.getLogger('bigfish.main')


class BigFishTitanApp:
    """大肥鱼桌宠钛坦屏投放工具主控制器。"""

    def __init__(self):
        self.qapp = QtWidgets.QApplication(sys.argv)
        self.qapp.setQuitOnLastWindowClosed(False)
        self.qapp.setApplicationName('BigFishTitanConsole')
        self.qapp.setApplicationDisplayName('大肥鱼桌宠钛坦屏投放工具')
        self.qapp.setWindowIcon(self._resolve_icon())

        # ---- 单实例 IPC 唤醒机制 ----
        from PySide6.QtNetwork import QLocalServer, QLocalSocket
        _IPC_KEY = 'BigFishTitanConsole_IPC_Wakeup'

        probe_sock = QLocalSocket()
        probe_sock.connectToServer(_IPC_KEY)
        if probe_sock.waitForConnected(400):
            probe_sock.write(b'SHOW_ALL\n')
            probe_sock.waitForBytesWritten(1000)
            probe_sock.disconnectFromServer()
            sys.exit(0)

        self._ipc_server = QLocalServer()
        self._ipc_server.removeServer(_IPC_KEY)
        self._ipc_server.listen(_IPC_KEY)
        self._ipc_server.newConnection.connect(self._on_ipc_incoming)

        # ---- 持久化配置与共享状态 ----
        self.cfg = load_config()
        self.settings = get_settings()

        # ---- 硬件锁守护 ----
        self.device_lock = DeviceLock()
        if not self.device_lock.acquire():
            log.warning('DeviceLock acquire 失败：其他程序可能正占用 USB 总线')

        # ---- 核心工作管线 ----
        self.pusher_signals = PusherSignals()
        self.pusher = DataPusher(self.pusher_signals)

        self.renderer_signals = DshRenderSignals()
        self.renderer = DshRendererThread(self.pusher, self.renderer_signals)

        self.dsh_signals = DshSignals()
        self.dsh_client = DshClient(self.dsh_signals)

        self.flash_signals = FlashSignals()
        self.flash_bridge = FlashBridge(self.pusher, self.flash_signals)

        # ---- UI 表现层 ----
        self.ball = BallWindow(config=self.cfg)
        self.menu = BallMenu()
        self.chat_dialog = ChatDialog()
        self.dashboard = DashboardWindow(
            settings=self.settings,
            renderer=self.renderer,
            pusher=self.pusher,
            flash_bridge=self.flash_bridge
        )
        self.panel = PanelWindow(
            settings=self.settings,
            renderer=self.renderer,
            flash_bridge=self.flash_bridge
        )
        self.panel.open_dashboard_requested.connect(self._show_dashboard)

        # 初始同步桌宠模式与控制目标
        cast_mode = getattr(self.settings, 'cast_mode', 'dual')
        control_target = getattr(self.settings, 'control_target', 'coopanion')
        self.ball.set_pet_mode(cast_mode, control_target)
        self.menu.set_pet_mode(cast_mode, control_target)

        # ---- 托盘图标 ----
        self._init_tray()

        # ---- 信号总线装配 ----
        self._wire_signals()

        # ---- 桌面端互斥定时看门狗 ----
        self._pet_visible_timer = QtCore.QTimer()
        self._pet_visible_timer.timeout.connect(self._sync_desktop_pet_visibility)
        self._pet_visible_timer.start(2000)

    def _resolve_icon(self) -> QtGui.QIcon:
        ico_path = _APP_DIR / 'assets' / 'app_icon.ico'
        if ico_path.exists():
            return QtGui.QIcon(str(ico_path))
        png_path = _APP_DIR / 'assets' / 'deepseek_fish_emperor.png'
        if png_path.exists():
            return QtGui.QIcon(str(png_path))
        return self.qapp.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon)

    def _init_tray(self):
        self.tray = QtWidgets.QSystemTrayIcon(self._resolve_icon(), self.qapp)
        self.tray.setToolTip('大肥鱼桌宠钛坦屏投放工具')

        menu = QtWidgets.QMenu()
        act_ball = menu.addAction('🔘 展开 / 隐藏悬浮球')
        act_ball.triggered.connect(self._toggle_ball)

        act_dash = menu.addAction('🗖 打开控制中心')
        act_dash.triggered.connect(self._show_dashboard)

        act_balance = menu.addAction('💰 刷新 DeepSeek 余额')
        act_balance.triggered.connect(self._on_action_balance)

        act_weather = menu.addAction('⛅ 查询实时环境与天气')
        act_weather.triggered.connect(self._on_action_weather)

        act_whisper = menu.addAction('💬 触发大肥鱼碎碎念')
        act_whisper.triggered.connect(self._on_action_whisper)

        menu.addSeparator()

        self.act_stream = menu.addAction('🖥️ 双屏模式切换（水冷屏 / 桌面）')
        self.act_stream.setCheckable(True)
        self.act_stream.setChecked(bool(self.settings.pushing and self.settings.hide_desktop_pet))
        self.act_stream.triggered.connect(lambda: self._on_toggle_display_mode())

        menu.addSeparator()
        act_quit = menu.addAction('✕ 完全退出')
        act_quit.triggered.connect(self.quit_app)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _wire_signals(self):
        """装配所有跨组件信号槽。"""
        # 1. 悬浮球与扇形菜单联动
        self.ball.action_triggered.connect(self._on_ball_action)
        self.ball.drag_started.connect(self.menu.hide_menu)
        self.menu.item_picked.connect(self._on_menu_item)
        self.menu.menu_closed.connect(lambda: self.ball.set_menu_open(False) if self.ball else None)

        # 2. 对话框输入投递 (文字及多模态附件)
        self.chat_dialog.chat_submitted.connect(self._on_chat_submitted)

        # 3. 控制中心交互与画面微调信号绑定
        self.dashboard.chat_requested.connect(self._open_chat_dialog)
        self.dashboard.pet_action.connect(self._on_pet_action)
        self.dashboard.coopanion_touch.connect(
            lambda: (self.renderer.send_command('touch', target='coopanion'), touch_desktop_pet())
        )
        self.dashboard.coopanion_voice.connect(trigger_coopanion_voice)
        self.dashboard.coopanion_chat.connect(self._open_chat_dialog)
        self.dashboard.coopanion_scale_changed.connect(
            lambda sc: self.renderer.send_command('coopanion_scale', scale=sc)
        )
        self.dashboard.transform_changed.connect(self._on_transform_changed)
        self.dashboard.bubble_scale_changed.connect(self._on_bubble_scale_changed)
        self.dashboard.anim_requested.connect(self._on_anim_requested)
        self.dashboard.meme_requested.connect(self._on_meme_requested)
        self.dashboard.reload_requested.connect(lambda: self.renderer.send_command('reload'))
        self.dashboard.stream_toggled.connect(self._on_toggle_display_mode)
        self.dashboard.hide_pet_toggled.connect(self._on_toggle_display_mode)
        self.dashboard.ball_snap_toggled.connect(self.ball.set_snap_enabled)
        self.dashboard.ball_peek_toggled.connect(self.ball.set_peek_enabled)
        self.panel.stream_toggled.connect(self._on_toggle_display_mode)
        self.panel.hide_pet_toggled.connect(self._on_toggle_display_mode)

        # 4. 多桌宠投放调度绑定
        self.dashboard.cast_mode_changed.connect(self._on_cast_mode_changed)
        self.dashboard.selective_cast_changed.connect(self._on_selective_cast_changed)
        self.dashboard.dual_layout_changed.connect(self._on_dual_layout_changed)
        self.dashboard.control_target_changed.connect(self._on_control_target_changed)
        self.menu.control_target_changed.connect(self._on_menu_control_target_changed)

        # 5. DSH 状态流 -> 水冷屏舞台
        self.dsh_signals.say_changed.connect(
            lambda text, meme: self.renderer.send_command('say', text=text, meme=meme)
        )
        self.dsh_signals.anim_changed.connect(
            lambda name: self.renderer.send_command('anim', name=name)
        )
        self.dsh_signals.balance_changed.connect(
            lambda bal, tier: self.renderer.send_command('balance', balance=bal, tier=tier)
        )
        self.dsh_signals.env_changed.connect(self._on_env_changed)

        # 6. 渲染预览帧传递给控制中心与微型面板
        self.renderer_signals.preview_frame_ready.connect(
            self.dashboard.on_frame_ready, QtCore.Qt.QueuedConnection
        )
        self.renderer_signals.preview_frame_ready.connect(
            self.panel.on_frame_ready, QtCore.Qt.QueuedConnection
        )

        # 7. 推流器状态广播给控制中心与微型面板
        self.pusher_signals.status_updated.connect(
            self.dashboard.on_status_updated, QtCore.Qt.QueuedConnection
        )
        self.pusher_signals.status_updated.connect(
            self.panel.on_status_updated, QtCore.Qt.QueuedConnection
        )

        # 8. Flash 刷写进度
        self.flash_signals.progress_updated.connect(
            self.dashboard._flash_widget.on_progress, QtCore.Qt.QueuedConnection
        )
        self.flash_signals.completed.connect(
            self.dashboard._flash_widget.on_completed, QtCore.Qt.QueuedConnection
        )

        # 9. 控制中心背景变更 -> 舞台更新
        self.dashboard.background_changed.connect(self._on_bg_changed)

    def _on_cast_mode_changed(self, mode: str):
        log.info('切换桌宠投放模式: %s', mode)
        layout = getattr(self.settings, 'dual_layout', 'side_by_side')
        target = getattr(self.settings, 'control_target', 'coopanion')

        # 1. 通知渲染器与 Web 舞台
        self.renderer.send_command('mode_change', mode=mode, layout=layout)

        # 2. 悬浮球自适应当前桌宠主题与按键
        self.ball.set_pet_mode(mode, target)
        self.menu.set_pet_mode(mode, target)

        # 3. 桌面桌宠互斥同步
        self._sync_desktop_pet_visibility()

    def _on_selective_cast_changed(self, cast_coop: bool, cast_dsh: bool):
        log.info('选择性投放变更: 大肥鱼=%s, 蓝毛女仆=%s', cast_coop, cast_dsh)
        self._sync_desktop_pet_visibility()

    def _on_dual_layout_changed(self, layout: str):
        log.info('双宠同台布局变更: %s', layout)
        mode = getattr(self.settings, 'cast_mode', 'dual')
        self.renderer.send_command('mode_change', mode=mode, layout=layout)

    def _on_control_target_changed(self, target: str):
        log.info('控制中心切换悬浮球交互控制靶心: %s', target)
        mode = getattr(self.settings, 'cast_mode', 'dual')
        self.ball.set_pet_mode(mode, target)
        self.menu.set_pet_mode(mode, target)

    def _on_menu_control_target_changed(self, target: str):
        log.info('悬浮球切换控制目标: %s', target)
        self.settings.update(control_target=target)
        mode = getattr(self.settings, 'cast_mode', 'dual')
        self.ball.set_pet_mode(mode, target)
        self.dashboard.update_control_target_from_ball(target)

    def _on_ball_action(self, action: str):
        if action == 'toggle_menu':
            if self.menu.isVisible():
                self.menu.hide_menu()
                self.ball.set_menu_open(False)
            else:
                self.ball.set_menu_open(True)
                is_screen = bool(self.settings.pushing and self.settings.hide_desktop_pet)
                self.menu.set_screen_mode(is_screen)
                self.menu.show_at(self.ball)

    def _open_chat_dialog(self):
        anchor = self.ball if self.ball.isVisible() else self.dashboard
        self.chat_dialog.popup_at(anchor)

    def _on_chat_submitted(self, text: str, attachment: dict | None):
        target = getattr(self.settings, 'control_target', 'coopanion') if getattr(self.settings, 'cast_mode', 'dual') == 'dual' else getattr(self.settings, 'cast_mode', 'coopanion')
        log.info('发送多模态对话 [目标: %s]: %s', target, text[:20])

        if target == 'coopanion':
            self.renderer.send_command('chat_text', target='coopanion', text=text)
        else:
            self.renderer.send_command('say', text=text, meme='吃白饭的大肥鱼' if not attachment else '')
            threading.Thread(target=self.dsh_client.send_chat, args=(text, attachment), daemon=True).start()

    def _on_transform_changed(self, scale: float, x: int, y: int):
        self.renderer.send_command('transform', scale=scale, x=x, y=y)

    def _on_bubble_scale_changed(self, scale: float):
        self.renderer.send_command('bubble_scale', scale=scale)

    def _on_anim_requested(self, anim_name: str):
        log.info('请求播放动作: %s', anim_name)
        self.renderer.send_command('anim', name=anim_name)
        threading.Thread(target=self.dsh_client.trigger_anim, args=(anim_name,), daemon=True).start()

    def _on_meme_requested(self, meme_name: str):
        log.info('请求展示表情包: %s', meme_name)
        self.renderer.send_command('say', text=f'主人看：{meme_name}！', meme=meme_name)
        threading.Thread(target=self.dsh_client.trigger_whisper, kwargs={'meme_name': meme_name}, daemon=True).start()

    def _on_pet_action(self, action: str):
        target = getattr(self.settings, 'control_target', 'coopanion') if getattr(self.settings, 'cast_mode', 'dual') == 'dual' else getattr(self.settings, 'cast_mode', 'coopanion')

        if action == 'touch':
            self.renderer.send_command('touch', target=target)
            if target in ('coopanion', 'all'):
                touch_desktop_pet()
        elif action == 'balance':
            self._on_action_balance()
        elif action == 'weather':
            self._on_action_weather()
        elif action == 'todo':
            trigger_dsh_chat()
        elif action == 'sleep_toggle':
            self._is_sleeping = not getattr(self, '_is_sleeping', False)
            if self._is_sleeping:
                self.dsh_client.trigger_sleep()
                self.renderer.send_command('sleep', sleep=True)
            else:
                self.dsh_client.trigger_wake()
                self.renderer.send_command('sleep', sleep=False)
        elif action == 'whisper':
            self._on_action_whisper()

    def _on_menu_item(self, key: str):
        self.menu.hide_menu()
        self.ball.set_menu_open(False)

        target = getattr(self.settings, 'control_target', 'coopanion') if getattr(self.settings, 'cast_mode', 'dual') == 'dual' else getattr(self.settings, 'cast_mode', 'coopanion')

        if key == 'touch':
            self.renderer.send_command('touch', target=target)
            if target in ('coopanion', 'all'):
                touch_desktop_pet()
        elif key == 'voice':
            trigger_coopanion_voice()
        elif key == 'chat':
            self._open_chat_dialog()
        elif key == 'toggle_display':
            self._on_toggle_display_mode()
        elif key == 'panel':
            self._show_dashboard()
        # 二级状态与生活入口
        elif key == 'status_balance':
            self._on_action_balance()
        elif key == 'status_weather':
            self._on_action_weather()
        elif key == 'status_todo':
            self._on_pet_action('todo')
        elif key == 'status_sleep':
            self._on_pet_action('sleep_toggle')
        # 二级表演与动作入口
        elif key == 'action_random':
            self._on_anim_requested('原地专心玩魔方')
        elif key == 'action_whisper':
            self._on_action_whisper()
        elif key == 'action_rice':
            self._on_anim_requested('吃白饭')
        elif key == 'action_dance':
            self._on_anim_requested('可爱宅舞')
        elif key == 'action_rub':
            self._on_meme_requested('吃饱饱摸肚子')
        # 三级动作转盘点播 (全量 114 款动作)
        elif key.startswith('anim:'):
            anim_name = key[len('anim:'):]
            self._on_anim_requested(anim_name)

    def _on_action_balance(self):
        log.info('用户请求刷新余额')
        bal = getattr(self.dsh_client, 'last_balance', '') or '¥22.74'
        tier = getattr(self.dsh_client, 'last_tier', 'normal') or 'normal'

        self.renderer.send_command('say', text=f'💰 DeepSeek 账户余额：{bal}', meme='token给妈妈保管')
        self.renderer.send_command('anim', name='余额-金袋叮当')
        self.renderer.send_command('balance', balance=bal, tier=tier)

        def _fetch():
            try:
                ok, new_bal, new_tier = self.dsh_client.trigger_balance()
                if ok and new_bal:
                    self.renderer.send_command('say', text=f'💰 DeepSeek 账户余额：{new_bal}', meme='token给妈妈保管')
                    self.renderer.send_command('balance', balance=new_bal, tier=new_tier)
            except Exception as e:
                log.warning('异步刷新余额异常: %s', e)

        threading.Thread(target=_fetch, daemon=True).start()

    def _on_action_weather(self):
        log.info('用户请求查询天气')
        threading.Thread(target=self.dsh_client.trigger_weather, daemon=True).start()

    def _on_env_changed(self, city: str, weather: str):
        log.info('环境状态更新: %s · %s', city, weather)

    def _on_action_whisper(self):
        log.info('用户请求触发碎碎念')
        threading.Thread(target=self.dsh_client.trigger_whisper, daemon=True).start()

    def _on_chat_sent(self, text: str):
        self.renderer.send_command('say', text=text, meme='吃白饭的大肥鱼')

    def _on_toggle_display_mode(self, target: bool | None = None):
        """双屏模式切换：
        target=True:  水冷屏运作模式（推流开启，主桌面桌宠自动隐藏）
        target=False: 主桌面运作模式（推流待机，主桌面桌宠恢复显示）
        """
        if target is None:
            is_screen_mode = bool(self.settings.pushing and self.settings.hide_desktop_pet)
            target = not is_screen_mode

        log.info('双屏模式切换: %s (推流=%s, 隐藏桌面=%s)',
                 '水冷屏模式' if target else '主桌面模式', target, target)

        self.settings.update(pushing=target, hide_desktop_pet=target)

        if target:
            self.pusher.start_pushing()
            self.renderer.is_active = True
        else:
            self.pusher.stop_pushing()
            self.renderer.is_active = False

        if hasattr(self, 'act_stream'):
            self.act_stream.setChecked(target)

        if hasattr(self, 'dashboard') and hasattr(self.dashboard, '_chk_display_mode'):
            self.dashboard._chk_display_mode.blockSignals(True)
            self.dashboard._chk_display_mode.setChecked(target)
            self.dashboard._chk_display_mode.blockSignals(False)

        self._sync_desktop_pet_visibility()

    def _on_bg_changed(self, mode: str, value: Any):
        if mode == 'dots' or mode == 'color':
            self.renderer.send_command('background', type=mode, val=value if mode == 'color' else '')
        elif mode == 'image' and isinstance(value, str):
            filename = os.path.basename(value)
            self.renderer.send_command('background', type='image', val=f'/assets/backgrounds/{filename}')

    def _sync_desktop_pet_visibility(self):
        """定时看门狗：根据推流开关、投放模式与互斥开关，原子同步桌面桌宠。"""
        s = self.settings.snapshot()
        mode = s.get('cast_mode', 'dual')
        c_coop = s.get('cast_coopanion', True)
        c_dsh = s.get('cast_dsh', True)
        pushing = s.get('pushing', True)
        hide_desktop = s.get('hide_desktop_pet', True)

        if not pushing:
            sync_desktop_pets(False, False, False, dsh_client=self.dsh_client)
            return

        sync_desktop_pets(c_coop, c_dsh, hide_desktop, dsh_client=self.dsh_client)

    def _toggle_ball(self):
        if self.ball.isVisible():
            self.ball.hide()
            self.menu.hide_menu()
        else:
            self.ball.show()

    def _show_dashboard(self):
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.DoubleClick:
            self._show_dashboard()

    def _on_ipc_incoming(self):
        client = self._ipc_server.nextPendingConnection()
        if client:
            client.waitForReadyRead(500)
            cmd = bytes(client.readAll()).decode('utf-8', errors='ignore').strip()
            if cmd == 'SHOW_ALL':
                self.ball.show()
                self._show_dashboard()
            client.disconnectFromServer()

    def start(self):
        """拉起后台线程与前端界面。"""
        log.info('BigFishTitanConsole 正在启动...')
        # 1. 启动硬件推流
        self.pusher.start()

        # 2. 启动舞台无头渲染
        self.renderer.start()
        init_bubble = getattr(self.settings, 'bubble_scale', 1.0)
        self.renderer.send_command('bubble_scale', scale=init_bubble)

        # 3. 启动 DSH 状态长轮询
        self.dsh_client.start_polling()

        # 4. 显示桌面悬浮球
        self.ball.show()

        # 5. 初始同步桌面端桌宠显隐
        QtCore.QTimer.singleShot(500, self._sync_desktop_pet_visibility)

        log.info('BigFishTitanConsole 启动成功，就绪。')
        return self.qapp.exec()

    def quit_app(self):
        """安全停止并退出应用。"""
        log.info('BigFishTitanConsole 正在安全退出...')
        self._pet_visible_timer.stop()

        # 恢复桌面桌宠
        restore_all_desktop_pets(self.dsh_client)

        # 停止 DSH 监听
        self.dsh_client.stop_polling()

        # 停止渲染与推流
        self.renderer.stop()
        self.pusher.stop_pushing()
        self.pusher.stop()

        # 释放硬件锁
        self.device_lock.release()

        self.qapp.quit()


def main():
    app = BigFishTitanApp()
    sys.exit(app.start())


if __name__ == '__main__':
    main()
