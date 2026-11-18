# -*- coding: utf-8 -*-
"""dsh_renderer.py — 大肥鱼桌宠钛坦屏 Playwright 无头 Edge 复合渲染管线与专属舞台控制器。

功能：
- 启动/托管本地 Web 多宠舞台服务 (DshStageServer)
- 原生/复合双模渲染：
  • 仅投放大肥鱼 (coopanion)：直接加载 http://127.0.0.1:7797/pet 并应用 1.6x 最佳视口与样式，100% 还原 Coopanion 原生质感与互动。
  • 仅投放蓝毛女仆 (dsh)：直接渲染 http://127.0.0.1:17799/stage.html 全屏 30fps WebM。
  • 双桌宠同台 (dual)：通过复合舞台并排/混排，自适应微缩补偿与居中。
- CDP 高速截帧（30 FPS / JPEG 质量 80）
- 通过 pusher.push_frame() 投递至水冷屏推流器
- 对接 UI 预览信号 (preview_frame_ready) 与 FPS 统计
- 路由摸头、对话、动作播放、背景等指令至目标桌宠
"""
from __future__ import annotations

import asyncio
import base64
import logging
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


def _check_port(port: int, host: str = '127.0.0.1') -> bool:
    """快速检测目标端口是否开启。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.25)
        res = s.connect_ex((host, port))
        s.close()
        return res == 0
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
        self._server = DshStageServer(port=SERVER_PORT)

        # 状态设置
        self.bg_image_url: str = ''
        self.is_active: bool = True
        self.current_mode: str = 'dual'
        self.current_layout: str = 'side_by_side'

    def stop(self):
        """通知线程停止。"""
        self._stop_event.set()

    def send_command(self, action: str, **kwargs):
        """向舞台发送交互或渲染指令。"""
        self.commands.put((action, kwargs))

    def run(self):
        """线程主执行体。"""
        # 1. 启动本地舞台服务
        self._server.start()
        time.sleep(0.2)

        # 2. 运行 asyncio 事件循环
        asyncio.run(self._async_main())

        # 3. 停止本地服务器
        self._server.stop()
        log.info('DshRendererThread: 已完全退出')

    async def _async_main(self):
        log.info('DshRendererThread: 正在拉起无头 Edge 渲染器...')

        # 浏览器启动参数：禁用同源隔离以支持内嵌 Coopanion iframe 样式无缝注入与通信
        browser_args = [
            '--autoplay-policy=no-user-gesture-required',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-infobars',
            '--no-default-browser-check',
            '--disable-web-security',
            '--disable-features=IsolateOrigins,site-per-process',
            '--allow-running-insecure-content',
            '--hide-scrollbars',
            '--mute-audio'
        ]

        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(
                    channel='msedge',
                    headless=True,
                    args=browser_args
                )
            except Exception as e:
                log.warning('启动 msedge 失败，尝试默认 chromium: %s', e)
                browser = await p.chromium.launch(
                    headless=True,
                    args=browser_args
                )

            context = await browser.new_context(
                viewport={'width': W, 'height': H},
                device_scale_factor=1.0,
                is_mobile=False
            )
            # 全局注入 WebSocket 钩子，捕获 Coopanion 活跃双向连接以支持摸头与对话
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

            # 建立 CDP 会话
            cdp = await context.new_cdp_session(page)

            # 读取初始配置
            try:
                try:
                    from config import get_settings
                except ImportError:
                    from ..config import get_settings
                s = get_settings()
                init_mode = getattr(s, 'cast_mode', 'dual')
                init_layout = getattr(s, 'dual_layout', 'side_by_side')
            except Exception:
                init_mode = 'dual'
                init_layout = 'side_by_side'

            # 根据初始模式导航与初始化视口
            await self._apply_mode(page, cdp, init_mode, init_layout)

            preview_counter = 0
            frames = 0
            last_fps_t0 = time.monotonic()

            while not self._stop_event.is_set():
                loop_t0 = time.monotonic()

                # 1. 消费命令队列
                while not self.commands.empty():
                    try:
                        cmd, kw = self.commands.get_nowait()
                        await self._handle_command(page, cdp, cmd, kw)
                    except queue.Empty:
                        break
                    except Exception as e:
                        log.warning('执行舞台指令异常: %s', e)

                # 2. 截帧
                try:
                    res = await cdp.send('Page.captureScreenshot', {
                        'format': 'jpeg',
                        'quality': 80
                    })
                    jpeg_bytes = base64.b64decode(res['data'])

                    # 3. 推送至物理硬件
                    if self.is_active:
                        self.pusher.push_frame(jpeg_bytes)

                    # 4. 预览信号发射 (降采样)
                    preview_counter += 1
                    if preview_counter >= _PREVIEW_EVERY_N:
                        preview_counter = 0
                        self.signals.preview_frame_ready.emit(jpeg_bytes)

                    frames += 1
                except Exception as e:
                    log.warning('CDP 截帧失败: %s', e)
                    await asyncio.sleep(0.08)

                # 5. FPS 统计
                now = time.monotonic()
                if now - last_fps_t0 >= 1.0:
                    fps = frames / (now - last_fps_t0)
                    self.signals.fps_updated.emit(fps)
                    frames = 0
                    last_fps_t0 = now

                # 6. 精确控频 (30 FPS)
                elapsed = time.monotonic() - loop_t0
                to_sleep = FRAME_INTERVAL - elapsed
                if to_sleep > 0.001:
                    await asyncio.sleep(to_sleep)
                else:
                    await asyncio.sleep(0.001)

            # 清理关闭
            try:
                await cdp.detach()
            except Exception:
                pass
            await page.close()
            await context.close()
            await browser.close()

    async def _apply_mode(self, page, cdp, mode: str, layout: str):
        """原子切换渲染目标页面与视口参数。"""
        self.current_mode = mode
        self.current_layout = layout
        try:
            try:
                from config import get_settings
            except ImportError:
                from ..config import get_settings
            s = get_settings()

            if mode == 'coopanion':
                # 单独投放大肥鱼模式：优先原生接入 7797 端口
                if _check_port(7797):
                    coop_url = getattr(s, 'coopanion_url', 'http://127.0.0.1:7797/pet')
                    if not page.url.startswith('http://127.0.0.1:7797'):
                        log.info('DshRendererThread: 导航至 Coopanion 原生视口 %s', coop_url)
                        await page.goto(coop_url, wait_until='load')
                        await asyncio.sleep(0.6)

                    # 注入 1.6x 最佳比例参数
                    scale = getattr(s, 'coopanion_scale', 1.6)
                    vw, vh = round(W / scale), round(H / scale)
                    await cdp.send('Emulation.setDeviceMetricsOverride', {
                        'width': vw, 'height': vh, 'deviceScaleFactor': scale, 'mobile': False
                    })
                    await asyncio.sleep(0.15)
                    await self._apply_coopanion_style(page, getattr(s, 'bg_mode', 'dots'), getattr(s, 'bg_value', ''))
                    return
                else:
                    log.warning('DshRendererThread: Coopanion (7797) 离线，切换至复合舞台提示')

            # 蓝毛女仆或双宠模式：恢复 640×480 原生视口
            await cdp.send('Emulation.setDeviceMetricsOverride', {
                'width': W, 'height': H, 'deviceScaleFactor': 1.0, 'mobile': False
            })

            stage_url = f'http://127.0.0.1:{SERVER_PORT}/stage.html'
            if not page.url.startswith(stage_url):
                log.info('DshRendererThread: 导航回本地多宠舞台 %s', stage_url)
                await page.goto(stage_url, wait_until='load')
                await asyncio.sleep(0.3)

            # 应用复合舞台设置
            await page.evaluate(
                '(arg) => window.__stageHub.setPetMode(arg.mode, arg.layout)',
                {'mode': mode, 'layout': layout}
            )

            # 同步背景与女仆位置
            bg_m = getattr(s, 'bg_mode', 'dots')
            bg_v = getattr(s, 'bg_value', '#0D1117')
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
        except Exception as e:
            log.warning('应用模式切换异常: %s', e)

    async def _apply_coopanion_style(self, page, bg_mode: str, bg_value: str):
        """为原生 Coopanion 注入定制背景（保持 gemini_work 100% 体验）。"""
        bg = ''
        if bg_mode == 'color':
            bg = f'html, body {{ background: {bg_value} !important; }} .floor {{ display: none !important; }}'
        elif bg_mode == 'image' and bg_value:
            path = Path(bg_value)
            if path.is_file():
                b64 = base64.b64encode(path.read_bytes()).decode()
                bg = (f'html, body {{ background:#000 !important; }} '
                      f'#stage {{ background: url(data:image/jpeg;base64,{b64}) center/cover no-repeat !important; }} '
                      f'.floor {{ display: none !important; }}')
        js = f"""
        (() => {{
            let s = document.getElementById('__titan_style__');
            if (!s) {{
                s = document.createElement('style');
                s.id = '__titan_style__';
                document.head.appendChild(s);
            }}
            s.textContent = `{bg}`;
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

        elif cmd == 'touch':
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
                    await page.mouse.click(vw * rx, vh * ry)
                except Exception as e:
                    log.warning('Playwright touch/click 失败: %s', e)
                try:
                    await page.evaluate("""() => {
                        if (window.__coopanionWs && window.__coopanionWs.readyState === 1) {
                            window.__coopanionWs.send(JSON.stringify({ t: 'touch', kind: 'pat' }));
                        }
                    }""")
                except Exception as e:
                    log.warning('WS Coopanion 摸头失败: %s', e)
            else:
                if target in ('coopanion', 'all'):
                    try:
                        await page.mouse.click(480, 360)
                    except Exception:
                        pass
                    try:
                        await page.evaluate('() => window.__stageHub.touchCoopanion()')
                        for f in page.frames:
                            if '7797' in f.url:
                                await f.evaluate("""() => {
                                    if (window.__coopanionWs && window.__coopanionWs.readyState === 1) {
                                        window.__coopanionWs.send(JSON.stringify({ t: 'touch', kind: 'pat' }));
                                    }
                                }""")
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

        elif cmd == 'say':
            text = kw.get('text', '')
            meme = kw.get('meme', '')
            if not ('7797' in page.url):
                await page.evaluate('(arg) => window.__stageHub.showSay(arg.text, arg.meme)', {'text': text, 'meme': meme})

        elif cmd == 'anim':
            name = kw.get('name', '')
            if not ('7797' in page.url):
                await page.evaluate('(name) => window.__stageHub.playAnim(name)', name)

        elif cmd == 'balance':
            bal = kw.get('balance', '')
            if not ('7797' in page.url):
                await page.evaluate('(bal) => window.__stageHub.showBalance(bal)', bal)

        elif cmd == 'background':
            bg_type = kw.get('type', 'dots')
            bg_val = kw.get('val', '')
            if '7797' in page.url:
                await self._apply_coopanion_style(page, bg_type, bg_val)
            else:
                await page.evaluate(
                    '(arg) => window.__stageHub.setBackground(arg.type, arg.val)',
                    {'type': bg_type, 'val': bg_val}
                )

        elif cmd == 'transform':
            scale = kw.get('scale', 1.0)
            x = kw.get('x', 0)
            y = kw.get('y', 0)
            if not ('7797' in page.url):
                await page.evaluate(
                    '(arg) => window.__stageHub.setTransform(arg.scale, arg.x, arg.y)',
                    {'scale': scale, 'x': x, 'y': y}
                )

        elif cmd == 'bubble_scale':
            scale = kw.get('scale', 1.0)
            if not ('7797' in page.url):
                await page.evaluate('(scale) => window.__stageHub.setBubbleScale(scale)', scale)

        elif cmd == 'reload':
            await page.reload(wait_until='load')
