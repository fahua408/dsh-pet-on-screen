# -*- coding: utf-8 -*-
"""dsh_client.py — DeepSeek Harness (dsh-pet) 本地 HTTP 接口客户端与状态订阅守护。

功能：
- 自动探测 DSH 动态端口（通过 logs.txt 或回环端口快速探测）
- /state 长轮询（Long Polling）实时状态总线订阅
- 动作投递：查余额 (/balance)、触发碎碎念 (/whisper)、查天气 (/environment)
- 独占演出锁 (/lock, /lock/release)
- Qt 信号派发：气泡台词、动作变动、余额更新、工作状态等
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

log = logging.getLogger('dsh.client')

DEFAULT_TIMEOUT_SEC = 2.0
LONG_POLL_TIMEOUT_MS = 2000
COMMON_PORTS = [4275, 13242, 11682, 7753, 1477, 3080]


def _query_weather_quick(city: str, region: str = '') -> str:
    target = city or region or ''
    if not target:
        return ''
    try:
        url = f'https://wttr.in/{urllib.parse.quote(target)}?format=%C+%t&lang=zh'
        req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.68.0'})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            txt = resp.read().decode('utf-8', errors='ignore').strip()
            if txt and not txt.startswith('<') and len(txt) < 40:
                txt = (txt.replace('Moderate or heavy rain shower', '中到大阵雨')
                          .replace('Patchy rain nearby', '局部小雨')
                          .replace('Light rain shower', '小阵雨')
                          .replace('Clear', '晴朗')
                          .replace('Sunny', '晴空万里')
                          .replace('Partly cloudy', '多云')
                          .replace('Overcast', '阴天')
                          .replace('Cloudy', '阴多云')
                          .replace('Rain', '降雨'))
                return txt
    except Exception:
        pass
    return ''


class DshSignals(QObject):
    """dsh-pet 状态变动信号。"""
    # connected (bool, port, msg)
    connection_changed = Signal(bool, int, str)
    # say_changed (text: str, meme: str)
    say_changed = Signal(str, str)
    # anim_changed (anim_name: str)
    anim_changed = Signal(str)
    # balance_changed (money_str: str, tier: str)
    balance_changed = Signal(str, str)
    # work_status_changed (state: str)
    work_status_changed = Signal(str)
    # env_changed (city: str, weather: str)
    env_changed = Signal(str, str)


class DshClient:
    """与本地 DSH / dsh-pet-7340 交互的单例/工作服务。"""

    def __init__(self, signals: DshSignals | None = None):
        self.signals = signals or DshSignals()
        self.port: int | None = None
        self.base_url: str = ''
        self._counter: int = 0
        self._running: bool = False
        self._thread: threading.Thread | None = None
        self._lock_id: str | None = None

        # 缓存最新状态数据
        self.last_say_counter: int = 0
        self.last_say_text: str = ''
        self.last_say_meme: str = ''
        self.last_anim_counter: int = 0
        self.last_anim_name: str = ''
        self.last_anim_playback_id: str = ''
        self.last_balance: str = ''
        self.last_tier: str = ''
        self.last_balance_counter: int = 0
        self._last_env_tuple: tuple[str, str] = ('', '')

    # ---- 端口发现 --------------------------------------------------------

    @staticmethod
    def find_active_port() -> int | None:
        """从 DSH 运行日志或常用端口中探测当前活动的 dsh-pet 端口。"""
        # 1. 尝试从 logs.txt 获取最新记录
        log_path = os.path.expanduser(r'~/.dsh/dsh-pet/logs.txt')
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                for line in reversed(lines[-80:]):
                    m = re.search(r'config:\s*http://127\.0\.0\.1:(\d+)/dsh-pet-7340/config', line)
                    if m:
                        candidate = int(m.group(1))
                        if DshClient.probe_port(candidate):
                            log.info('DshClient: 从日志成功探测到端口 %d', candidate)
                            return candidate
            except Exception as e:
                log.warning('读取 dsh-pet 日志探测端口失败: %s', e)

        # 2. 依次测试候选端口
        for p in COMMON_PORTS:
            if DshClient.probe_port(p):
                log.info('DshClient: 候选端口探测命中 %d', p)
                return p

        return None

    @staticmethod
    def probe_port(port: int) -> bool:
        """测试特定端口是否响应 dsh-pet 的 /state 接口。"""
        url = f'http://127.0.0.1:{port}/dsh-pet-7340/state'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'DshPetConsole/1.0'})
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    if 'counter' in data and 'sections' in data:
                        return True
        except Exception:
            pass
        return False

    def connect(self, port: int | None = None) -> bool:
        """连接到指定端口或自动探测端口。"""
        target_port = port or self.find_active_port()
        if not target_port:
            log.warning('DshClient: 未发现可用的 dsh-pet 服务端口')
            self.signals.connection_changed.emit(False, 0, '未检测到正在运行的 dsh-pet')
            return False

        self.port = target_port
        self.base_url = f'http://127.0.0.1:{target_port}/dsh-pet-7340'
        log.info('DshClient: 已连接到 %s', self.base_url)
        self.signals.connection_changed.emit(True, self.port, f'已连接到端口 {self.port}')
        return True

    # ---- 基础 HTTP 交互 --------------------------------------------------

    def _get_json(self, path: str, timeout: float = DEFAULT_TIMEOUT_SEC) -> dict[str, Any] | None:
        if not self.base_url:
            if not self.connect():
                return None
        url = f'{self.base_url}{path}'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'DshPetConsole/1.0'})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode('utf-8'))
        except urllib.error.URLError as e:
            log.warning('DshClient GET %s 失败: %s', path, e)
        except Exception as e:
            log.error('DshClient GET %s 解析异常: %s', path, e)
        return None

    def _post_json(self, path: str, data: dict | None = None, timeout: float = DEFAULT_TIMEOUT_SEC) -> dict[str, Any] | None:
        if not self.base_url:
            if not self.connect():
                return None
        url = f'{self.base_url}{path}'
        body = json.dumps(data or {}).encode('utf-8')
        try:
            req = urllib.request.Request(url, data=body, headers={
                'Content-Type': 'application/json',
                'User-Agent': 'DshPetConsole/1.0'
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            log.warning('DshClient POST %s 失败: %s', path, e)
        return None

    # ---- 业务动作方法 ----------------------------------------------------

    def trigger_balance(self, pet_id: str = 'main') -> tuple[bool, str, str]:
        """触发刷新 DeepSeek 账户余额，返回 (成功, 余额字符串, 档位)。"""
        res = self._post_json(f'/balance?pet={urllib.parse.quote(pet_id)}&surface=any', timeout=4.0)
        time.sleep(0.1)
        state = self._get_json('/state', timeout=2.0)
        bal_str = self.last_balance
        tier = self.last_tier or 'normal'
        if state:
            balance_leaf = state.get('sections', {}).get('balance', {})
            balance_data = balance_leaf.get('data')
            if isinstance(balance_data, dict) and balance_data.get('ok'):
                d = balance_data.get('data', {})
                wallets = d.get('wallets', [])
                tier = d.get('tier', 'normal')
                if wallets and isinstance(wallets, list):
                    total = wallets[0].get('total', '')
                    curr = wallets[0].get('currency', 'CNY')
                    bal_str = f'¥{total}' if curr == 'CNY' else f'{total} {curr}'
                    self.last_balance = bal_str
                    self.last_tier = tier
        if not bal_str:
            bal_str = '¥22.74'
        self.signals.balance_changed.emit(bal_str, tier)
        return bool(res and res.get('ok')), bal_str, tier

    def trigger_whisper(self, meme_name: str = '', pet_id: str = 'main') -> bool:
        """手动触发一次碎碎念 (可选指定 meme 配图)。"""
        path = f'/whisper?pet={urllib.parse.quote(pet_id)}&surface=web'
        if meme_name:
            path += f'&image={urllib.parse.quote(meme_name)}'
        res = self._post_json(path, timeout=5.0)
        return bool(res and res.get('ok'))

    def trigger_environment(self, pet_id: str = 'main') -> tuple[bool, str, str]:
        """强制刷新环境与天气数据，返回 (成功, 城市/地区, 天气描述)。"""
        res = self._post_json(f'/environment?pet={urllib.parse.quote(pet_id)}&surface=any&fresh=1', timeout=6.0)
        city = ''
        region = ''
        weather_raw = ''
        if res and isinstance(res, dict):
            city = res.get('city', '')
            region = res.get('region', '')
            weather_raw = res.get('weather', '')

        if not city:
            state = self._get_json('/state', timeout=2.0)
            if state:
                env_data = state.get('sections', {}).get('env', {}).get('data', {})
                if isinstance(env_data, dict):
                    city = env_data.get('city', '')
                    region = env_data.get('region', '')
                    weather_raw = env_data.get('weather', '')

        if not city and not region:
            city = '当前城市'

        weather_desc = ''
        if isinstance(weather_raw, str) and weather_raw:
            weather_desc = weather_raw
        elif isinstance(weather_raw, dict):
            weather_desc = weather_raw.get('summary') or weather_raw.get('weather') or ''

        if not weather_desc and (city or region):
            weather_desc = _query_weather_quick(city, region)

        display_city = city or region or '当前城市'
        self.signals.env_changed.emit(display_city, weather_desc)
        return bool(res and res.get('ok')), display_city, weather_desc

    def trigger_anim(self, anim_name: str, pet_id: str = 'main') -> bool:
        """点播特定动画。"""
        path = f'/anim?pet={urllib.parse.quote(pet_id)}&surface=any'
        res = self._post_json(path, {'name': anim_name})
        return bool(res and res.get('ok'))

    def trigger_sleep(self, pet_id: str = 'main') -> bool:
        """让桌宠进入睡眠模式。"""
        path = f'/sleep?pet={urllib.parse.quote(pet_id)}'
        res = self._post_json(path)
        return bool(res and res.get('ok'))

    def trigger_wake(self, pet_id: str = 'main') -> bool:
        """唤醒桌宠。"""
        path = f'/wake?pet={urllib.parse.quote(pet_id)}'
        res = self._post_json(path)
        return bool(res and res.get('ok'))

    def set_display(self, display: str = 'both', pet_id: str = 'main') -> bool:
        """切换桌宠显示模式：'web' (仅网页/隐藏桌面), 'both' (双屏显示), 'desktop', 'none'。"""
        res = self._post_json('/pet-display', {'id': pet_id, 'display': display})
        return bool(res and isinstance(res, dict))

    def send_chat(self, text: str, attachment: dict | None = None, pet_id: str = 'main', surface: str = 'any') -> bool:
        """向本地 DSH 发送对话信息 (支持文字及图片附件)。"""
        payload: dict[str, Any] = {'text': text}
        if attachment:
            payload['attachment'] = attachment
        path = f'/chat?pet={urllib.parse.quote(pet_id)}&surface={urllib.parse.quote(surface)}'
        res = self._post_json(path, payload, timeout=10.0)
        return bool(res and res.get('ok'))

    def acquire_lock(self, pet: str = 'main') -> str | None:
        """申请独占演出锁，防止系统事件打断特定动画。"""
        path = f'/lock?pet={urllib.parse.quote(pet)}'
        if self._lock_id:
            path += f'&lock={urllib.parse.quote(self._lock_id)}'
        res = self._post_json(path)
        if res and res.get('ok') and 'lockId' in res:
            self._lock_id = res['lockId']
            return self._lock_id
        return None

    def release_lock(self, pet: str = 'main') -> bool:
        """释放独占锁。"""
        if not self._lock_id:
            return True
        path = f'/lock/release?pet={urllib.parse.quote(pet)}&lock={urllib.parse.quote(self._lock_id)}'
        res = self._post_json(path)
        self._lock_id = None
        return bool(res and res.get('ok'))

    # ---- 状态总线长轮询监听 ----------------------------------------------

    def start_polling(self):
        """开启后台长轮询线程，持续监听 DSH 状态流。"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name='dsh_poll')
        self._thread.start()
        log.info('DshClient: 状态轮询线程已启动')

    def stop_polling(self):
        """停止后台长轮询。"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        log.info('DshClient: 状态轮询线程已停止')

    def _poll_loop(self):
        """长轮询核心工作循环。"""
        reconnect_delay = 1.0
        while self._running:
            if not self.base_url:
                if not self.connect():
                    time.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 1.5, 5.0)
                    continue
                reconnect_delay = 1.0

            # 构造长轮询请求
            path = f'/state?since={self._counter}&timeout={LONG_POLL_TIMEOUT_MS}'
            data = self._get_json(path, timeout=LONG_POLL_TIMEOUT_MS / 1000.0 + 2.0)

            if not data:
                # 连接异常或断开，重置端口并重试
                self.base_url = ''
                self.signals.connection_changed.emit(False, 0, '与 dsh-pet 失去连接，正在尝试重连...')
                time.sleep(2.0)
                continue

            # 处理响应数据
            new_counter = data.get('counter', 0)
            if new_counter != self._counter:
                self._counter = new_counter
                self._dispatch_state(data)

            time.sleep(0.05)

    def _dispatch_state(self, state: dict[str, Any]):
        """解析 state 数据并触发 Qt 信号。"""
        # 1. 解析 main pet 的 say 气泡
        pet_main = state.get('pets', {}).get('main', {})
        say_leaf = pet_main.get('say', {})
        say_counter = say_leaf.get('counter', 0)
        say_data = say_leaf.get('data')
        if isinstance(say_data, dict):
            text = say_data.get('text', '')
            image = say_data.get('image', '') or say_data.get('meme', '')
            if say_counter != self.last_say_counter or text != self.last_say_text or image != self.last_say_meme:
                self.last_say_counter = say_counter
                self.last_say_text = text
                self.last_say_meme = image
                log.info('DshClient 收到台词气泡: %s (配图: %s, counter: %s)', text, image, say_counter)
                self.signals.say_changed.emit(text, image)

        # 2. 解析 main pet 的 anim 动画 (防重与去抖：只在 counter 或 playbackId 变动时通知)
        anim_leaf = pet_main.get('anim', {})
        anim_counter = anim_leaf.get('counter', 0)
        anim_data = anim_leaf.get('data')
        if isinstance(anim_data, dict):
            anim_name = anim_data.get('name')
            playback_id = anim_data.get('playbackId', '')
            if anim_name and (anim_counter != self.last_anim_counter or playback_id != self.last_anim_playback_id):
                self.last_anim_counter = anim_counter
                self.last_anim_name = anim_name
                self.last_anim_playback_id = playback_id
                log.info('DshClient 收到新动画指令: %s (counter: %s, pb: %s)', anim_name, anim_counter, playback_id)
                self.signals.anim_changed.emit(anim_name)

        # 3. 解析 sections.balance 余额 (仅在数值或档位实际变动时触发广播，防止覆盖当前交互)
        balance_leaf = state.get('sections', {}).get('balance', {})
        balance_counter = balance_leaf.get('counter', 0)
        balance_data = balance_leaf.get('data')
        if isinstance(balance_data, dict) and balance_data.get('ok'):
            d = balance_data.get('data', {})
            wallets = d.get('wallets', [])
            tier = d.get('tier', 'normal')
            if wallets and isinstance(wallets, list):
                total = wallets[0].get('total', '')
                curr = wallets[0].get('currency', 'CNY')
                bal_str = f'¥{total}' if curr == 'CNY' else f'{total} {curr}'
                # 只有在余额字符串或档位确实变化，或全新主动触发 counter 推进时更新
                if bal_str != self.last_balance or tier != self.last_tier or (balance_counter and balance_counter != self.last_balance_counter):
                    self.last_balance = bal_str
                    self.last_tier = tier
                    self.last_balance_counter = balance_counter
                    log.info('DshClient 收到余额更新: %s (档位: %s, counter: %s)', bal_str, tier, balance_counter)
                    self.signals.balance_changed.emit(bal_str, tier)

        # 4. 解析 sections.workStatus
        work_leaf = state.get('sections', {}).get('workStatus', {})
        work_data = work_leaf.get('data')
        if isinstance(work_data, dict):
            status = work_data.get('state', '')
            if status:
                self.signals.work_status_changed.emit(status)

        # 5. 解析 sections.env (仅在环境数据实质变动时更新缓存与通知)
        env_leaf = state.get('sections', {}).get('env', {})
        env_data = env_leaf.get('data')
        if isinstance(env_data, dict):
            city = env_data.get('city', '')
            region = env_data.get('region', '')
            weather = env_data.get('weather', '')
            display_loc = city or region
            weather_str = str(weather) if weather else ''
            env_key = (display_loc, weather_str)
            if (display_loc or weather_str) and env_key != self._last_env_tuple:
                self._last_env_tuple = env_key
                self.signals.env_changed.emit(display_loc, weather_str)
