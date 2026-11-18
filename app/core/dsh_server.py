# -*- coding: utf-8 -*-
"""dsh_server.py — 水冷屏专属本地 Web 服务与资产映射网关。

端口：默认 17799（回环地址 127.0.0.1）
映射路由：
- /                      -> app/web/ (stage.html, stage.js, stage.css)
- /assets/webm/          -> ~/.dsh/profiles/desktop/node_modules/dsh-pet/assets/webm/
- /assets/memes/         -> ~/.dsh/profiles/desktop/node_modules/dsh-pet/assets/memes/
- /assets/fonts/         -> app/assets/fonts/
- /assets/backgrounds/   -> app/assets/backgrounds/
支持 HTTP 206 Partial Content 范围分片响应，完美支持 Chromium HTML5 视频流解码。
"""
from __future__ import annotations

import http.server
import logging
import mimetypes
import os
import re
import socketserver
import sys
import threading
import urllib.parse
from typing import ClassVar

log = logging.getLogger('dsh.server')

SERVER_PORT = 17799


class DshStageHandler(http.server.BaseHTTPRequestHandler):
    """自定义路由映射与切片支持 HTTP 请求处理器。"""

    server_version = 'DshPetConsoleServer/1.0'

    DSH_HOME = os.path.expanduser(r'~/.dsh')
    WEBM_DIR = os.path.join(DSH_HOME, 'profiles', 'desktop', 'node_modules', 'dsh-pet', 'assets', 'webm')
    MEMES_DIR = os.path.join(DSH_HOME, 'profiles', 'desktop', 'node_modules', 'dsh-pet', 'assets', 'memes')

    MEME_ALIASES: ClassVar[dict[str, str]] = {
        '吃token': 'token给妈妈保管.png',
        'token': 'token给妈妈保管.png',
        '惬意': '吃饱饱摸肚子.png',
        '探头': '可爱.png',
        '摸头': '吃饱饱摸肚子.png',
        '摸肚子': '吃饱饱摸肚子.png',
        '吃白饭': '吃白饭的大肥鱼.png',
        '看远方': '可爱.png',
        '夜观天象': '可爱.png',
    }

    @classmethod
    def get_base_dir(cls) -> str:
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            if os.path.isdir(os.path.join(exe_dir, 'web')):
                return exe_dir
            if hasattr(sys, '_MEIPASS') and os.path.isdir(os.path.join(sys._MEIPASS, 'web')):
                return sys._MEIPASS
            return exe_dir
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @classmethod
    def _resolve_meme_path(cls, sub: str) -> str | None:
        sub = os.path.basename(sub.strip().replace('\\', '/'))
        base_name, ext = os.path.splitext(sub)
        if not ext:
            target_name = f'{base_name}.png'
        else:
            target_name = sub

        # 检查别名
        lower_key = base_name.lower()
        if lower_key in cls.MEME_ALIASES:
            target_name = cls.MEME_ALIASES[lower_key]

        search_dirs = [
            os.path.join(cls.get_base_dir(), 'assets', 'memes'),
            cls.MEMES_DIR,
        ]

        # 1. 尝试直接与大小写不敏感匹配
        for s_dir in search_dirs:
            if not os.path.isdir(s_dir):
                continue
            direct = os.path.join(s_dir, target_name)
            if os.path.isfile(direct):
                return direct
            try:
                for f in os.listdir(s_dir):
                    if f.lower() == target_name.lower():
                        return os.path.join(s_dir, f)
            except Exception:
                pass

        # 2. 兜底默认表情包，避免返回 404 造成前端图裂
        for fallback in ('吃白饭的大肥鱼.png', '可爱.png', '先养着吧.png'):
            for s_dir in search_dirs:
                fb_path = os.path.join(s_dir, fallback)
                if os.path.isfile(fb_path):
                    return fb_path

        return None

    @classmethod
    def _resolve_webm_path(cls, sub: str) -> str | None:
        sub = os.path.basename(sub.strip().replace('\\', '/'))
        if not sub.endswith('.webm'):
            sub += '.webm'
        search_dirs = [
            cls.WEBM_DIR,
            os.path.join(cls.get_base_dir(), 'assets', 'webm'),
        ]
        for s_dir in search_dirs:
            if not os.path.isdir(s_dir):
                continue
            direct = os.path.join(s_dir, sub)
            if os.path.isfile(direct):
                return direct
            try:
                for f in os.listdir(s_dir):
                    if f.lower() == sub.lower():
                        return os.path.join(s_dir, f)
            except Exception:
                pass
        return None

    def log_message(self, format, *args):
        # 降噪，仅在 debug 时记录
        pass

    def do_GET(self):
        url_path = urllib.parse.unquote(self.path.split('?')[0])

        base_dir = self.get_base_dir()
        web_dir = os.path.join(base_dir, 'web')
        fonts_dir = os.path.join(base_dir, 'assets', 'fonts')
        bg_dir = os.path.join(base_dir, 'assets', 'backgrounds')

        # 映射本地物理文件
        file_path = None
        if url_path in ('/', '/index.html', '/stage.html'):
            file_path = os.path.join(web_dir, 'stage.html')
        elif url_path == '/stage.js':
            file_path = os.path.join(web_dir, 'stage.js')
        elif url_path == '/stage.css':
            file_path = os.path.join(web_dir, 'stage.css')
        elif url_path.startswith('/assets/webm/'):
            sub = url_path[len('/assets/webm/'):].lstrip('/')
            file_path = self._resolve_webm_path(sub)
        elif url_path.startswith('/assets/memes/'):
            sub = url_path[len('/assets/memes/'):].lstrip('/')
            file_path = self._resolve_meme_path(sub)
        elif url_path.startswith('/assets/fonts/'):
            sub = url_path[len('/assets/fonts/'):].lstrip('/')
            file_path = os.path.join(fonts_dir, sub)
        elif url_path.startswith('/assets/backgrounds/'):
            sub = url_path[len('/assets/backgrounds/'):].lstrip('/')
            file_path = os.path.join(bg_dir, sub)

        if not file_path or not os.path.isfile(file_path):
            self.send_error(404, f'File Not Found: {url_path}')
            return

        # 判定 MIME
        ext = os.path.splitext(file_path)[1].lower()
        mime_map = {
            '.html': 'text/html; charset=utf-8',
            '.js': 'application/javascript; charset=utf-8',
            '.css': 'text/css; charset=utf-8',
            '.webm': 'video/webm',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.ttf': 'font/ttf',
            '.json': 'application/json; charset=utf-8'
        }
        content_type = mime_map.get(ext, 'application/octet-stream')

        try:
            file_size = os.path.getsize(file_path)
            range_header = self.headers.get('Range')

            if range_header and ext == '.webm':
                # 处理 HTTP 206 范围请求
                m = re.match(r'bytes=(\d+)-(\d*)', range_header)
                if m:
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else file_size - 1
                    end = min(end, file_size - 1)
                    length = end - start + 1

                    self.send_response(206)
                    self.send_header('Content-Type', content_type)
                    self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
                    self.send_header('Content-Length', str(length))
                    self.send_header('Accept-Ranges', 'bytes')
                    self.end_headers()

                    with open(file_path, 'rb') as f:
                        f.seek(start)
                        self.wfile.write(f.read(length))
                    return

            # 普通 200 请求
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(file_size))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            with open(file_path, 'rb') as f:
                # 块分批写入
                while chunk := f.read(64 * 1024):
                    self.wfile.write(chunk)

        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass
        except OSError as e:
            if getattr(e, 'winerror', None) in (10053, 10054):
                pass
            else:
                log.warning('服务静态文件 %s 网络异常: %s', file_path, e)
        except Exception as e:
            log.warning('服务静态文件 %s 出错: %s', file_path, e)


class DshStageServer:
    """管理后台 ThreadingHTTPServer 生命周期。"""

    def __init__(self, port: int = SERVER_PORT):
        self.port = port
        self._server: socketserver.TCPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self):
        if self._server:
            return
        # 允许端口快速重用
        socketserver.TCPServer.allow_reuse_address = True
        self._server = socketserver.ThreadingTCPServer(('127.0.0.1', self.port), DshStageHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name='dsh_stage_http')
        self._thread.start()
        log.info('DshStageServer: 本地舞台服务已启动 http://127.0.0.1:%d', self.port)

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            log.info('DshStageServer: 本地舞台服务已关闭')
