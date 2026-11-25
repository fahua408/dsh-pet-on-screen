# -*- coding: utf-8 -*-
"""dsh_renderer.py — 大肥鱼桌宠钛坦屏 Playwright 无头 Edge 复合渲染管线与专属舞台控制器。

功能：
- 启动/托管本地 Web 多宠舞台服务 (DshStageServer)
- 原生/复合双模渲染：
  • 仅投放大肥鱼 (coopanion)：优先直接加载 http://127.0.0.1:7797/pet 并应用 1.6x 最佳视口与样式，离线时展示舞台提示并在上线后自动无缝切回。
  • 仅投放蓝毛女仆 (dsh)：直接渲染 http://127.0.0.1:17799/stage.html 全屏 30fps WebM。
  • 双桌宠同台 (dual)：通过复合舞台并排/混排，自适应微缩补偿与居中。
- 待机休眠优化：当处于主桌面运作模式 (is_active=False) 时自动暂停 CDP 截帧，零 CPU/GPU 空耗。
- 高频指令合并去重 (Command Coalescing)：拖动缩放/偏移滑块时单帧合并执行，杜绝命令积压引起投屏卡顿。
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import queue
import socket
import threading
import time
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright
from PySide6.QtCore import QObject, Signal

from .dsh_server import DshStageServer, SERVER_PORT
from .pusher import DataPusher

log = logging.getLogger('bigfish.renderer')

W, H = 640, 480
TARGET_FPS = 30.0
FRAME_INTERVAL = 1.0 / TARGET_FPS
_PREVIEW_EVERY_N = 3  # 每 3 帧向 UI 投递一次预览图

# 可在单帧内合并去重的高频幂等指令
_COALESCABLE_CMDS = frozenset({'transform', 'bubble_scale', 'coopanion_scale', 'background', 'mode_change'})


def _check_port(port: int, host: str = '127.0.0.1') -> bool:
    """快速检测目标端口是否开启。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


class DshRenderSignals(QObject):
    """渲染管线对外派发的 Qt 信号。"""
    preview_frame_ready = Signal(bytes)
    fps_updated = Signal(float)


class DshRendererThread(threading.Thread):
    """无头 Edge 渲染与截帧后台线程。"""

    def __init__(self, pusher: DataPusher, signals: DshRenderSignals | None = None):
        super().__init__(daemon=True, name='dsh_renderer')
        self.pusher = pusher
        self.signals = signals or DshRenderSignals()
        self.commands: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()

        self._stop_event = threading.Event()
        self._server = DshStageServer(port=SERVER_PORT, renderer=self)

        # 状态设置
        self.bg_image_url: str = ''
        self.is_active: bool = True
        self.current_mode: str = 'dual'
        self.current_layout: str = 'side_by_side'
        self.last_jpeg_bytes: bytes = b''
        self.last_fps: float = 0.0
        self.total_frames: int = 0

    def stop(self):
        """通知线程停止。"""
        self._stop_event.set()

    def send_command(self, action: str, **kwargs):
        """向舞台发送交互或渲染指令。"""
        self.commands.put((action, kwargs))

    def _drain_coalesced_commands(self) -> list[tuple[str, dict[str, Any]]]:
        """一次性取出当前队列中的所有指令，并对高频幂等指令合并去重。"""
        raw_list: list[tuple[str, dict[str, Any]]] = []
        while True:
            try:
                raw_list.append(self.commands.get_nowait())
            except queue.Empty:
                break
        if len(raw_list) <= 1:
            return raw_list

        # 反向遍历：对可合并指令仅保留最后一次出现
        seen_coalescable: set[str] = set()
        result_rev: list[tuple[str, dict[str, Any]]] = []
        for cmd, kw in reversed(raw_list):
            if cmd in _COALESCABLE_CMDS:
                if cmd in seen_coalescable:
                    continue
                seen_coalescable.add(cmd)
            result_rev.append((cmd, kw))
        result_rev.reverse()
        return result_rev

    def run(self):
        """线程主执行体。"""
        self._server.start()
        time.sleep(0.15)

        while not self._stop_event.is_set():
            try:
                asyncio.run(self._async_main())
                break
            except Exception as e:
                if self._stop_event.is_set():
                    break
                log.warning('DshRendererThread 渲染循环异常: %s，2 秒后重启渲染器...', e)
                time.sleep(2.0)

        self._server.stop()
        log.info('DshRendererThread: 已完全退出')

    async def _async_main(self):
        log.info('DshRendererThread: 正在拉起无头 Edge 渲染器...')

        browser_args = [
            '--autoplay-policy=no-user-gesture-required',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-background-media-suspend',
            '--disable-ipc-flooding-protection',
            '--disable-infobars',
            '--no-default-browser-check',
            '--disable-web-security',
            '--disable-features=IsolateOrigins,site-per-process,CalculateNativeWinOcclusion,IntensiveWakeUpThrottling',
            '--allow-running-insecure-content',
            '--hide-scrollbars',
            '--mute-audio',
        ]

        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(
                    channel='msedge',
                    headless=True,
                    args=browser_args,
                )
            except Exception as e:
                log.warning('启动 msedge 失败，尝试默认 chromium: %s', e)
                browser = await p.chromium.launch(
                    headless=True,
                    args=browser_args,
                )

            context = await browser.new_context(
                viewport={'width': W, 'height': H},
                device_scale_factor=1.0,
                is_mobile=False,
            )
            await context.add_init_script("""
            (() => {
                try {
                    const origSend = WebSocket.prototype.send;
                    WebSocket.prototype.send = function(...args) {
                        window.__coopanionWs = this;
                        return origSend.apply(this, args);
                    };
                } catch(e) {}
            })();
            """)
            page = await context.new_page()
            cdp = await context.new_cdp_session(page)

            try:
                try:
                    from config import get_settings
                except ImportError:
                    from ..config import get_settings
                s = get_settings()
                init_mode = getattr(s, 'cast_mode', 'dual')
                init_layout = getattr(s, 'dual_layout', 'side_by_side')
                self.is_active = bool(getattr(s, 'pushing', True))
            except Exception:
                init_mode = 'dual'
                init_layout = 'side_by_side'

            await self._apply_mode(page, cdp, init_mode, init_layout)

            preview_counter = 0
            frames = 0
            cdp_fail_streak = 0
            last_fps_t0 = time.monotonic()
            last_coop_probe = time.monotonic()

            while not self._stop_event.is_set():
                loop_t0 = time.monotonic()

                # 1. 批量消费并合并命令队列
                pending_cmds = self._drain_coalesced_commands()
                for cmd, kw in pending_cmds:
                    try:
                        await asyncio.wait_for(self._handle_command(page, cdp, cmd, kw), timeout=3.0)
                    except Exception as e:
                        log.warning('执行舞台指令 [%s] 异常: %s', cmd, e)

                # 2. 若当前处于主桌面待机模式 (is_active=False)，休眠免截帧，彻底释放 CPU/GPU
                if not self.is_active:
                    await asyncio.sleep(0.2)
                    last_fps_t0 = time.monotonic()
                    frames = 0
                    cdp_fail_streak = 0
                    continue

                # 3. 若在单大肥鱼模式下此前因 7797 离线回退到了 stage.html，每 3.5 秒自动探测一次是否已上线
                now = time.monotonic()
                if (self.current_mode == 'coopanion'
                        and not page.url.startswith('http://127.0.0.1:7797')
                        and now - last_coop_probe >= 3.5):
                    last_coop_probe = now
                    if _check_port(7797):
                        await self._apply_mode(page, cdp, 'coopanion', self.current_layout)

                # 4. CDP 截帧 (quality 75 + optimizeForSpeed 兼顾高清画质与低延迟，带超时看门狗防挂死)
                try:
                    res = await asyncio.wait_for(
                        cdp.send('Page.captureScreenshot', {
                            'format': 'jpeg',
                            'quality': 75,
                            'optimizeForSpeed': True,
                        }),
                        timeout=1.5,
                    )
                    jpeg_bytes = base64.b64decode(res['data'])
                    self.last_jpeg_bytes = jpeg_bytes
                    self.total_frames += 1
                    cdp_fail_streak = 0

                    # 5. 推送至物理硬件
                    if self.is_active:
                        self.pusher.push_frame(jpeg_bytes)

                    # 6. 预览信号发射 (降采样 10 FPS)
                    preview_counter += 1
                    if preview_counter >= _PREVIEW_EVERY_N:
                        preview_counter = 0
                        self.signals.preview_frame_ready.emit(jpeg_bytes)

                    frames += 1
                except Exception as e:
                    cdp_fail_streak += 1
                    log.warning('CDP 截帧失败 (%d/5): %s', cdp_fail_streak, e)
                    if cdp_fail_streak >= 5:
                        raise RuntimeError(f'CDP 连续截帧失败 {cdp_fail_streak} 次，触发渲染器自愈重启') from e
                    await asyncio.sleep(0.08)

                # 7. FPS 统计
                now = time.monotonic()
                if now - last_fps_t0 >= 1.0:
                    fps = frames / (now - last_fps_t0)
                    self.last_fps = fps
                    self.signals.fps_updated.emit(fps)
                    frames = 0
                    last_fps_t0 = now

                # 8. 精确控频 (30 FPS)
                elapsed = time.monotonic() - loop_t0
                to_sleep = FRAME_INTERVAL - elapsed
                if to_sleep > 0.001:
                    await asyncio.sleep(to_sleep)
                else:
                    await asyncio.sleep(0.001)

            try:
                await cdp.detach()
            except Exception:
                pass
            await page.close()
            await context.close()
            await browser.close()

    @staticmethod
    def _stage_bg_url(bg_mode: str, bg_value: str) -> tuple[str, str]:
        """将本地背景路径转化为舞台 HTTP 可访问的 URL。"""
        if bg_mode != 'image' or not bg_value:
            return bg_mode, bg_value
        if bg_value.startswith('/assets/') or bg_value.startswith('http'):
            return 'image', bg_value
        filename = os.path.basename(bg_value)
        preset_files = {
            'bg_1_dots.jpg', 'bg_2_gradient.jpg', 'bg_3_starry.jpg',
            'bg_4_underwater.jpg', 'bg_5_cyber.jpg', 'bg_6_midnight.jpg',
        }
        if filename in preset_files:
            return 'image', f'/assets/backgrounds/{filename}'
        return 'image', f'/assets/custom_bg?t={int(time.time())}'

    async def _apply_mode(self, page, cdp, mode: str, layout: str):
        """原子切换渲染目标页面与视口参数。"""
        if mode not in ('coopanion', 'dsh', 'dual'):
            mode = 'dual'
        self.current_mode = mode
        self.current_layout = layout
        try:
            try:
                from config import get_settings
            except ImportError:
                from ..config import get_settings
            s = get_settings()

            if mode == 'coopanion':
                if _check_port(7797):
                    coop_url = getattr(s, 'coopanion_url', 'http://127.0.0.1:7797/pet')
                    if not page.url.startswith('http://127.0.0.1:7797'):
                        log.info('DshRendererThread: 导航至 Coopanion 原生视口 %s', coop_url)
                        await page.goto(coop_url, wait_until='load')
                        await asyncio.sleep(0.45)

                    scale = getattr(s, 'coopanion_scale', 1.6)
                    vw, vh = round(W / scale), round(H / scale)
                    await cdp.send('Emulation.setDeviceMetricsOverride', {
                        'width': vw, 'height': vh, 'deviceScaleFactor': scale, 'mobile': False
                    })
                    await asyncio.sleep(0.1)
                    await self._apply_coopanion_style(page, getattr(s, 'bg_mode', 'dots'), getattr(s, 'bg_value', ''))
                    return
                else:
                    log.info('DshRendererThread: Coopanion (7797) 暂未启动，展示舞台离线引导页')

            await cdp.send('Emulation.setDeviceMetricsOverride', {
                'width': W, 'height': H, 'deviceScaleFactor': 1.0, 'mobile': False
            })

            stage_url = f'http://127.0.0.1:{SERVER_PORT}/stage.html'
            if not page.url.startswith(stage_url):
                log.info('DshRendererThread: 导航回本地多宠舞台 %s', stage_url)
                await page.goto(stage_url, wait_until='load')
                await asyncio.sleep(0.25)

            await page.evaluate(
                '(arg) => window.__stageHub.setPetMode(arg.mode, arg.layout)',
                {'mode': mode, 'layout': layout}
            )

            bg_m, bg_v = self._stage_bg_url(getattr(s, 'bg_mode', 'dots'), getattr(s, 'bg_value', '#0D1117'))
            await page.evaluate(
                '(arg) => window.__stageHub.setBackground(arg.type, arg.val)',
                {'type': bg_m, 'val': bg_v}
            )
            await page.evaluate(
                '(arg) => window.__stageHub.setTransform(arg.scale, arg.x, arg.y)',
                {'scale': s.scale, 'x': s.offset_x, 'y': s.offset_y}
            )
            await page.evaluate(
                '(scale) => window.__stageHub.setBubbleScale(scale)',
                getattr(s, 'bubble_scale', 1.0)
            )
            await page.evaluate(
                '(scale) => window.__stageHub.setCoopanionScale && window.__stageHub.setCoopanionScale(scale)',
                getattr(s, 'coopanion_scale', 1.6)
            )
        except Exception as e:
            log.warning('应用模式切换异常: %s', e)

    async def _apply_coopanion_style(self, page, bg_mode: str, bg_value: str):
        """为原生 Coopanion 注入定制背景并隐藏底部工具栏。"""
        bg = ''
        if bg_mode == 'color' and bg_value:
            bg = f'html, body {{ background: {bg_value} !important; }} .floor {{ display: none !important; }}'
        elif bg_mode == 'image' and bg_value:
            path = Path(bg_value)
            if not path.is_file() and bg_value.startswith('/assets/backgrounds/'):
                base_dir = Path(__file__).resolve().parent.parent
                path = base_dir / 'assets' / 'backgrounds' / os.path.basename(bg_value)
            if path.is_file():
                b64 = base64.b64encode(path.read_bytes()).decode()
                bg = (f'html, body {{ background:#000 !important; }} '
                      f'#stage {{ background: url(data:image/jpeg;base64,{b64}) center/cover no-repeat !important; }} '
                      f'.floor {{ display: none !important; }}')
        css = f"""
        {bg}
        .floor-icons, #tools, .tools, #menu, .menu, .sizer, .wheel {{ display: none !important; }}
        """
        js = f"""
        (() => {{
            let s = document.getElementById('__titan_style__');
            if (!s) {{
                s = document.createElement('style');
                s.id = '__titan_style__';
                document.head.appendChild(s);
            }}
            s.textContent = {repr(css)};
        }})();
        """
        try:
            await page.evaluate(js)
        except Exception as e:
            log.warning('注入 Coopanion 样式失败: %s', e)

    async def _handle_command(self, page, cdp, cmd: str, kw: dict[str, Any]):
        """在页面环境中执行 JS 动作与多宠调度。"""
        if cmd == 'mode_change':
            mode = kw.get('mode', 'dual')
            layout = kw.get('layout', 'side_by_side')
            await self._apply_mode(page, cdp, mode, layout)

        elif cmd in ('touch', 'click'):
            target = kw.get('target', 'all')
            if '7797' in page.url:
                try:
                    from config import get_settings
                except ImportError:
                    from ..config import get_settings
                s = get_settings()
                scale = getattr(s, 'coopanion_scale', 1.6)
                vw, vh = round(W / scale), round(H / scale)
                rx, ry = kw.get('ratio', (0.78, 0.74))
                try:
                    await page.evaluate("""() => {
                        if (window.__petApp && typeof window.__petApp.touch === 'function') {
                            window.__petApp.touch('pet');
                        }
                        if (window.__coopanionWs && window.__coopanionWs.readyState === 1) {
                            window.__coopanionWs.send(JSON.stringify({ t: 'touch', kind: 'pat' }));
                        }
                    }""")
                    await page.mouse.click(vw * rx, vh * ry)
                except Exception as e:
                    log.warning('Playwright Coopanion touch 失败: %s', e)
            else:
                if target in ('coopanion', 'all'):
                    try:
                        await page.evaluate('() => window.__stageHub.touchCoopanion()')
                        for f in page.frames:
                            if '7797' in f.url:
                                await f.evaluate("""() => {
                                    if (window.__petApp && typeof window.__petApp.touch === 'function') {
                                        window.__petApp.touch('pet');
                                    }
                                    if (window.__coopanionWs && window.__coopanionWs.readyState === 1) {
                                        window.__coopanionWs.send(JSON.stringify({ t: 'touch', kind: 'pat' }));
                                    }
                                }""")
                        await page.mouse.click(160, 340)
                    except Exception:
                        pass
                if target in ('dsh', 'all'):
                    await page.evaluate('() => window.__dshPet.touch()')

        elif cmd == 'chat_text':
            target = kw.get('target', 'coopanion')
            text = kw.get('text', '')
            if '7797' in page.url:
                js = """
                (text) => {
                    if (window.__petApp && typeof window.__petApp.chat === 'function') {
                        window.__petApp.chat(text);
                        return;
                    }
                    if (typeof send === 'function') {
                        send({ t: 'text', text: text });
                        try { if (typeof addLine === 'function') addLine('type', text, false); } catch (e) {}
                        return;
                    }
                    if (window.__coopanionWs && window.__coopanionWs.readyState === 1) {
                        window.__coopanionWs.send(JSON.stringify({ t: 'text', text: text }));
                    }
                    const ta = document.querySelector('textarea, input[type="text"]');
                    if (ta) {
                        ta.value = text;
                        ta.dispatchEvent(new Event('input', { bubbles: true }));
                        if (ta.form) ta.form.requestSubmit();
                    }
                }
                """
                try:
                    await page.evaluate(js, text)
                except Exception as e:
                    log.warning('原生 Coopanion 发送对话失败: %s', e)
            else:
                if target in ('coopanion', 'all'):
                    await page.evaluate('(txt) => window.__stageHub.chatCoopanion(txt)', text)
                    for f in page.frames:
                        if '7797' in f.url:
                            try:
                                await f.evaluate("""(txt) => {
                                    if (window.__petApp && typeof window.__petApp.chat === 'function') {
                                        window.__petApp.chat(txt);
                                        return;
                                    }
                                    if (typeof send === 'function') {
                                        send({ t: 'text', text: txt });
                                        try { if (typeof addLine === 'function') addLine('type', txt, false); } catch (e) {}
                                        return;
                                    }
                                    if (window.__coopanionWs && window.__coopanionWs.readyState === 1) {
                                        window.__coopanionWs.send(JSON.stringify({ t: 'text', text: txt }));
                                    }
                                }""", text)
                            except Exception:
                                pass
                if target in ('dsh', 'all'):
                    await page.evaluate('(txt) => window.__stageHub.showSay(txt, "", 4500)', text)

        elif cmd == 'coopanion_scale':
            scale = float(kw.get('scale', 1.6))
            if '7797' in page.url:
                vw, vh = round(W / scale), round(H / scale)
                await cdp.send('Emulation.setDeviceMetricsOverride', {
                    'width': vw, 'height': vh, 'deviceScaleFactor': scale, 'mobile': False
                })
            else:
                await page.evaluate(
                    '(sc) => window.__stageHub.setCoopanionScale && window.__stageHub.setCoopanionScale(sc)',
                    scale
                )

        elif cmd == 'say':
            text = kw.get('text', '')
            meme = kw.get('meme', '')
            if '7797' not in page.url:
                if text:
                    await page.evaluate(
                        '(arg) => window.__stageHub.showSay(arg.text, arg.meme)',
                        {'text': text, 'meme': meme}
                    )
                else:
                    await page.evaluate('() => window.__stageHub.hideSay()')

        elif cmd == 'anim':
            name = kw.get('name', '')
            if '7797' not in page.url and name:
                await page.evaluate('(name) => window.__stageHub.playAnim(name)', name)

        elif cmd == 'sleep':
            sleeping = bool(kw.get('sleep', False))
            if '7797' not in page.url:
                await page.evaluate(
                    '(slp) => window.__stageHub.setSleep && window.__stageHub.setSleep(slp)',
                    sleeping
                )

        elif cmd == 'balance':
            bal = kw.get('balance', '')
            if '7797' not in page.url and bal:
                await page.evaluate('(bal) => window.__stageHub.showBalance(bal)', bal)

        elif cmd == 'background':
            bg_type = kw.get('type', 'dots')
            bg_val = kw.get('val', '')
            if '7797' in page.url:
                await self._apply_coopanion_style(page, bg_type, bg_val)
            else:
                st_type, st_val = self._stage_bg_url(bg_type, bg_val)
                await page.evaluate(
                    '(arg) => window.__stageHub.setBackground(arg.type, arg.val)',
                    {'type': st_type, 'val': st_val}
                )

        elif cmd == 'transform':
            scale = kw.get('scale', 1.0)
            x = kw.get('x', 0)
            y = kw.get('y', 0)
            if '7797' not in page.url:
                await page.evaluate(
                    '(arg) => window.__stageHub.setTransform(arg.scale, arg.x, arg.y)',
                    {'scale': scale, 'x': x, 'y': y}
                )

        elif cmd == 'bubble_scale':
            scale = kw.get('scale', 1.0)
            if '7797' not in page.url:
                await page.evaluate('(scale) => window.__stageHub.setBubbleScale(scale)', scale)

        elif cmd == 'reload':
            await page.reload(wait_until='load')
            await asyncio.sleep(0.25)
            await self._apply_mode(page, cdp, self.current_mode, self.current_layout)
