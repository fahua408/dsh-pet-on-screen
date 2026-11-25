# -*- coding: utf-8 -*-
"""dsh_client.py — DeepSeek Harness (dsh-pet) 本地 HTTP 接口客户端与状态订阅守护。

功能：
- 自动探测 DSH 动态端口（优先读取 ~/.dsh/surfcore/pet/host.json，其次扫描 logs.txt 尾部 128KB，最后快速探测候选端口）
- /state 长轮询（Long Polling）实时状态总线订阅
- 动作投递：查余额 (/balance)、触发碎碎念 (/whisper)、查天气 (/environment)、查待办 (/todos)、多模态对话 (/chat)
- 睡眠状态同步与交互前自动唤醒（避免 sleepGated 静默拦截）
- 独占演出锁 (/lock, /lock/release)
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
from typing import Any

from PySide6.QtCore import QObject, Signal

log = logging.getLogger('dsh.client')

DEFAULT_TIMEOUT_SEC = 2.0
LONG_POLL_TIMEOUT_MS = 2000
COMMON_PORTS = [4655, 4275, 12375, 13242, 11682, 7753, 1477, 3080]


def _query_weather_quick(city: str, region: str = '') -> str:
    target = city or region or ''
    if not target or target == '当前城市':
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
    # sleep_changed (is_sleeping: bool)
    sleep_changed = Signal(bool)


class DshClient:
    """与本地 DSH / dsh-pet-7340 交互的工作服务。"""

    def __init__(self, signals: DshSignals | None = None):
        self.signals = signals or DshSignals()
        self.port: int | None = None
        self.base_url: str = ''
        self._counter: int = 0
        self._running: bool = False
        self._thread: threading.Thread | None = None
        self._lock_id: str | None = None
        self._warned_offline: bool = False

        # 缓存最新状态数据
        self.is_sleeping: bool = False
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

    @property
    def is_connected(self) -> bool:
        return bool(self.base_url and self.port)

    # ---- 端口发现 --------------------------------------------------------

    @staticmethod
    def find_active_port() -> int | None:
        """从 DSH 宿主配置、运行日志或常用端口中探测当前活动的 dsh-pet 端口。"""
        tried: set[int] = set()

        # 1. 首选读取 ~/.dsh/surfcore/pet/host.json（DSH 宿主实时更新的权威端口文件）
        host_json_path = os.path.expanduser(r'~/.dsh/surfcore/pet/host.json')
        if os.path.isfile(host_json_path):
            try:
                with open(host_json_path, 'r', encoding='utf-8', errors='ignore') as f:
                    info = json.load(f)
                base_url = str(info.get('baseUrl', ''))
                m = re.search(r'127\.0\.0\.1:(\d+)', base_url)
                if m:
                    candidate = int(m.group(1))
                    tried.add(candidate)
                    if DshClient.probe_port(candidate, timeout=0.4):
                        log.info('DshClient: 从 host.json 成功探测到端口 %d', candidate)
                        return candidate
            except Exception as e:
                log.debug('读取 host.json 探测端口失败: %s', e)

        # 2. 从 ~/.dsh/dsh-pet/logs.txt 尾部 128KB 检索历史端口（避免因长时间运行碎碎念刷屏而漏检）
        log_path = os.path.expanduser(r'~/.dsh/dsh-pet/logs.txt')
        if os.path.isfile(log_path):
            try:
                file_size = os.path.getsize(log_path)
                with open(log_path, 'rb') as f:
                    if file_size > 131072:
                        f.seek(file_size - 131072)
                    chunk = f.read().decode('utf-8', errors='ignore')
                matches = re.findall(r'http://127\.0\.0\.1:(\d+)/dsh-pet-7340', chunk)
                for port_str in reversed(matches):
                    candidate = int(port_str)
                    if candidate in tried:
                        continue
                    tried.add(candidate)
                    if DshClient.probe_port(candidate, timeout=0.35):
                        log.info('DshClient: 从 logs.txt 成功探测到端口 %d', candidate)
                        return candidate
            except Exception as e:
                log.debug('读取 dsh-pet 日志探测端口失败: %s', e)

        # 3. 依次快速测试候选端口
        for p in COMMON_PORTS:
            if p in tried:
                continue
            tried.add(p)
            if DshClient.probe_port(p, timeout=0.25):
                log.info('DshClient: 候选端口探测命中 %d', p)
                return p

        return None

    @staticmethod
    def probe_port(port: int, timeout: float = 0.4) -> bool:
        """测试特定端口是否响应 dsh-pet 的 /state 接口。"""
        url = f'http://127.0.0.1:{port}/dsh-pet-7340/state'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'BigFishTitanConsole/1.2'})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
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
            if not self._warned_offline:
                log.warning('DshClient: 未发现可用的 dsh-pet 服务端口（后台将继续静默探测）')
                self._warned_offline = True
            self.signals.connection_changed.emit(False, 0, '未检测到正在运行的 dsh-pet')
            return False

        self._warned_offline = False
        self.port = target_port
        self.base_url = f'http://127.0.0.1:{target_port}/dsh-pet-7340'
        log.info('DshClient: 已连接到 %s', self.base_url)
        self.signals.connection_changed.emit(True, self.port, f'已连接 (:{self.port})')
        return True

    # ---- 基础 HTTP 交互 --------------------------------------------------

    def _get_json(self, path: str, timeout: float = DEFAULT_TIMEOUT_SEC, *, auto_connect: bool = True) -> dict[str, Any] | None:
        if not self.base_url:
            if not auto_connect or not self.connect():
                return None
        url = f'{self.base_url}{path}'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'BigFishTitanConsole/1.2'})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode('utf-8'))
        except urllib.error.URLError as e:
            log.debug('DshClient GET %s 失败: %s', path, e)
        except Exception as e:
            log.debug('DshClient GET %s 解析异常: %s', path, e)
        return None

    def _post_json(self, path: str, data: dict | None = None, timeout: float = DEFAULT_TIMEOUT_SEC, *, auto_connect: bool = True) -> dict[str, Any] | None:
        if not self.base_url:
            if not auto_connect or not self.connect():
                return None
        url = f'{self.base_url}{path}'
        body = json.dumps(data or {}).encode('utf-8')
        try:
            req = urllib.request.Request(url, data=body, headers={
                'Content-Type': 'application/json',
                'User-Agent': 'BigFishTitanConsole/1.2'
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            log.debug('DshClient POST %s 失败: %s', path, e)
        return None

    def _ensure_awake(self, pet_id: str = 'main'):
        """如果桌宠处于睡眠状态，先自动唤醒，避免宿主 sleepGated 拒绝互动请求。"""
        if self.is_sleeping:
            self.trigger_wake(pet_id)

    # ---- 业务动作方法 ----------------------------------------------------

    def broadcast_say(self, text: str, image: str = '', duration: int = 5000, pet_id: str = 'main') -> bool:
        """向 DSH 状态总线投喂一条气泡台词（支持配图）。"""
        if not text:
            return False
        payload: dict[str, Any] = {'text': text, 'duration': duration}
        if image:
            payload['image'] = image
        res = self._post_json(f'/broadcast?pet={urllib.parse.quote(pet_id)}&surface=any', payload, timeout=2.5, auto_connect=False)
        if not (res and res.get('ok')):
            # 即使宿主离线或拒绝，也通过本地信号确保水冷屏即时弹出气泡
            self.signals.say_changed.emit(text, image)
            return False
        return True

    def trigger_balance(self, pet_id: str = 'main') -> tuple[bool, str, str]:
        """触发刷新 DeepSeek 账户余额，返回 (成功, 余额字符串, 档位)。"""
        self._ensure_awake(pet_id)
        res = self._post_json(f'/balance?pet={urllib.parse.quote(pet_id)}&surface=any', timeout=4.0)
        time.sleep(0.12)
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
        if bal_str:
            self.signals.balance_changed.emit(bal_str, tier)
        return bool(res and res.get('ok')), bal_str, tier

    def trigger_whisper(self, meme_name: str = '', pet_id: str = 'main') -> bool:
        """手动触发一次碎碎念 (可选指定 meme 配图)。"""
        self._ensure_awake(pet_id)
        path = f'/whisper?pet={urllib.parse.quote(pet_id)}&surface=any'
        if meme_name:
            path += f'&image={urllib.parse.quote(meme_name)}'
        res = self._post_json(path, timeout=6.0)
        if res and res.get('ok'):
            text = res.get('text', '')
            img = res.get('image', '') or meme_name
            if text:
                self.signals.say_changed.emit(text, img)
            return True
        return False

    def trigger_environment(self, pet_id: str = 'main') -> tuple[bool, str, str]:
        """强制刷新环境与天气数据，并在水冷屏弹出天气气泡。"""
        self._ensure_awake(pet_id)
        res = self._post_json(f'/environment?pet={urllib.parse.quote(pet_id)}&surface=any&fresh=1', timeout=6.0)
        city = ''
        region = ''
        weather_raw: Any = ''
        if res and isinstance(res, dict):
            city = res.get('city', '')
            region = res.get('region', '')
            weather_raw = res.get('weather', '')

        if not city and not weather_raw:
            state = self._get_json('/state', timeout=2.0)
            if state:
                env_data = state.get('sections', {}).get('env', {}).get('data', {})
                if isinstance(env_data, dict):
                    city = env_data.get('city', '')
                    region = env_data.get('region', '')
                    weather_raw = env_data.get('weather', '')

        weather_desc = ''
        if isinstance(weather_raw, str) and weather_raw:
            weather_desc = weather_raw
        elif isinstance(weather_raw, dict):
            parts = []
            for k in ('summary', 'weather', 'condition', 'text', 'temp', 'temperature'):
                v = weather_raw.get(k)
                if v is not None and str(v).strip():
                    parts.append(str(v).strip())
            weather_desc = ' '.join(parts)

        display_city = city or region or ''
        if not weather_desc and display_city:
            weather_desc = _query_weather_quick(city, region)

        if not display_city:
            display_city = '本地环境'
        if not weather_desc:
            weather_desc = '晴朗舒适'

        self.signals.env_changed.emit(display_city, weather_desc)
        self.signals.say_changed.emit(f'⛅ {display_city} · {weather_desc}', '可爱')
        return bool(res and res.get('ok')), display_city, weather_desc

    # 兼容别名：修复 main.py 调用 trigger_weather 报 AttributeError 的问题
    trigger_weather = trigger_environment

    def trigger_todos(self, pet_id: str = 'main') -> tuple[bool, list[dict]]:
        """读取 DSH 待办事项清单并在水冷屏气泡展示。"""
        self._ensure_awake(pet_id)
        res = self._get_json('/todos', timeout=3.0)
        todos: list[dict] = []
        if res and isinstance(res, dict) and isinstance(res.get('todos'), list):
            todos = res['todos']
        pending = [t for t in todos if isinstance(t, dict) and not t.get('done')]
        if pending:
            preview_items = [str(t.get('text', '')).strip() for t in pending[:3] if t.get('text')]
            summary = '；'.join(f'{i+1}. {txt}' for i, txt in enumerate(preview_items))
            more = f' 等共 {len(pending)} 项' if len(pending) > 3 else f' (共 {len(pending)} 项)'
            msg = f'📋 待办提醒{more}：{summary}'
            self.signals.say_changed.emit(msg, '先养着吧')
        else:
            self.signals.say_changed.emit('📋 当前没有未完成的待办事项，轻松摸鱼吧~', '吃饱饱摸肚子')
        return True, pending

    def trigger_anim(self, anim_name: str, pet_id: str = 'main') -> bool:
        """点播特定动画。"""
        self._ensure_awake(pet_id)
        path = f'/anim?pet={urllib.parse.quote(pet_id)}&surface=any'
        res = self._post_json(path, {'name': anim_name})
        return bool(res and res.get('ok'))

    def trigger_sleep(self, pet_id: str = 'main') -> bool:
        """让桌宠进入睡眠模式。"""
        self.is_sleeping = True
        self.signals.sleep_changed.emit(True)
        path = f'/sleep?pet={urllib.parse.quote(pet_id)}'
        res = self._post_json(path, auto_connect=False)
        return bool(res and res.get('ok'))

    def trigger_wake(self, pet_id: str = 'main') -> bool:
        """唤醒桌宠。"""
        self.is_sleeping = False
        self.signals.sleep_changed.emit(False)
        path = f'/wake?pet={urllib.parse.quote(pet_id)}'
        res = self._post_json(path, auto_connect=False)
        return bool(res and res.get('ok'))

    def set_display(self, display: str = 'both', pet_id: str = 'main') -> bool:
        """切换桌宠显示模式：'web' (仅网页/隐藏桌面), 'both' (双屏显示), 'desktop', 'none'。"""
        if not self.base_url:
            return False
        res = self._post_json('/pet-display', {'id': pet_id, 'display': display}, timeout=1.5, auto_connect=False)
        return bool(res and isinstance(res, dict))

    def send_chat(self, text: str, attachment: dict | None = None, pet_id: str = 'main', surface: str = 'any') -> bool:
        """向本地 DSH 发送对话信息 (支持文字及图片附件，严格对齐 dsh-pet parseImageAttachment 协议)。"""
        self._ensure_awake(pet_id)
        clean_text = (text or '').strip()
        if not clean_text and attachment:
            clean_text = '看看这张图片'
        if not clean_text:
            return False

        payload: dict[str, Any] = {'text': clean_text}
        if attachment and isinstance(attachment, dict):
            b64_data = attachment.get('data') or attachment.get('base64') or ''
            media_type = attachment.get('mediaType') or 'image/jpeg'
            if b64_data:
                payload['attachment'] = {
                    'mediaType': media_type,
                    'data': b64_data,
                }

        path = f'/chat?pet={urllib.parse.quote(pet_id)}&surface={urllib.parse.quote(surface)}'
        res = self._post_json(path, payload, timeout=25.0)
        if res and isinstance(res, dict):
            if res.get('ok'):
                reply_text = str(res.get('text', '')).strip()
                reply_img = str(res.get('image', '') or '').strip()
                if reply_text:
                    self.signals.say_changed.emit(reply_text, reply_img)
                return True
            else:
                err_msg = str(res.get('message') or res.get('reason') or '对话请求未成功')
                log.warning('DshClient /chat 返回失败: %s', err_msg)
                self.signals.say_changed.emit(f'唔…{err_msg}', '压力一只大肥鱼')
        return False

    def acquire_lock(self, pet: str = 'main') -> str | None:
        """申请独占演出锁，防止系统事件打断特定动画。"""
        path = f'/lock?pet={urllib.parse.quote(pet)}&surface=any'
        body: dict[str, Any] = {}
        if self._lock_id:
            body['lockId'] = self._lock_id
        res = self._post_json(path, body)
        if res and res.get('ok') and 'lockId' in res:
            self._lock_id = res['lockId']
            return self._lock_id
        return None

    def release_lock(self, pet: str = 'main') -> bool:
        """释放独占锁。"""
        if not self._lock_id:
            return True
        path = f'/lock/release?pet={urllib.parse.quote(pet)}'
        res = self._post_json(path, {'lockId': self._lock_id})
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

            path = f'/state?since={self._counter}&timeout={LONG_POLL_TIMEOUT_MS}'
            data = self._get_json(path, timeout=LONG_POLL_TIMEOUT_MS / 1000.0 + 2.0, auto_connect=False)

            if not data:
                self.base_url = ''
                self.port = None
                self.signals.connection_changed.emit(False, 0, '与 dsh-pet 失去连接，正在重连...')
                time.sleep(2.0)
                continue

            new_counter = data.get('counter', 0)
            if new_counter != self._counter:
                self._counter = new_counter
                self._dispatch_state(data)

            time.sleep(0.04)

    def _dispatch_state(self, state: dict[str, Any]):
        """解析 state 数据并触发 Qt 信号。"""
        pet_main = state.get('pets', {}).get('main', {})

        # 0. 解析 main pet 的 sleep 状态
        sleep_leaf = pet_main.get('sleep', {})
        sleep_data = sleep_leaf.get('data')
        new_sleeping = bool(isinstance(sleep_data, dict) and (sleep_data.get('loop') or sleep_data.get('start')))
        if new_sleeping != self.is_sleeping:
            self.is_sleeping = new_sleeping
            self.signals.sleep_changed.emit(new_sleeping)

        # 1. 解析 main pet 的 say 气泡
        say_leaf = pet_main.get('say', {})
        say_counter = say_leaf.get('counter', 0)
        say_data = say_leaf.get('data')
        if isinstance(say_data, dict):
            if say_data.get('clear') is True:
                self.last_say_counter = say_counter
                self.signals.say_changed.emit('', '')
            else:
                text = say_data.get('text', '')
                image = say_data.get('image', '') or say_data.get('meme', '')
                if text and (say_counter != self.last_say_counter or text != self.last_say_text or image != self.last_say_meme):
                    self.last_say_counter = say_counter
                    self.last_say_text = text
                    self.last_say_meme = image
                    log.info('DshClient 收到台词气泡: %s (配图: %s)', text, image)
                    self.signals.say_changed.emit(text, image)

        # 2. 解析 main pet 的 anim 动画
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
                log.info('DshClient 收到新动画指令: %s', anim_name)
                self.signals.anim_changed.emit(anim_name)

        # 3. 解析 sections.balance 余额
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
                if bal_str != self.last_balance or tier != self.last_tier or (balance_counter and balance_counter != self.last_balance_counter):
                    self.last_balance = bal_str
                    self.last_tier = tier
                    self.last_balance_counter = balance_counter
                    log.info('DshClient 收到余额更新: %s (档位: %s)', bal_str, tier)
                    self.signals.balance_changed.emit(bal_str, tier)

        # 4. 解析 sections.workStatus
        work_leaf = state.get('sections', {}).get('workStatus', {})
        work_data = work_leaf.get('data')
        if isinstance(work_data, dict):
            status = work_data.get('state', '')
            if status:
                self.signals.work_status_changed.emit(status)

        # 5. 解析 sections.env
        env_leaf = state.get('sections', {}).get('env', {})
        env_data = env_leaf.get('data')
        if isinstance(env_data, dict):
            city = env_data.get('city', '')
            region = env_data.get('region', '')
            weather = env_data.get('weather', '')
            display_loc = city or region
            if isinstance(weather, dict):
                weather_str = str(weather.get('summary') or weather.get('weather') or '')
            else:
                weather_str = str(weather) if weather else ''
            env_key = (display_loc, weather_str)
            if (display_loc or weather_str) and env_key != self._last_env_tuple:
                self._last_env_tuple = env_key
                self.signals.env_changed.emit(display_loc, weather_str)
