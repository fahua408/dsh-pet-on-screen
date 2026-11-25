# -*- coding: utf-8 -*-
"""win32_guard.py — 双桌宠（Coopanion 大肥鱼 & DeepSeek dsh-pet 蓝毛小女仆）统一 Win32 守护与快捷键模拟。

功能：
- 识别并枚举 Coopanion (Cortico) 窗口句柄
- 识别并枚举 dsh-pet (DeepSeek Harness) 窗口句柄
- 双保险显隐控制（Win32 SW_HIDE/SW_SHOW + DSH 原生 API /pet-display 异步非阻塞调用）
- 依据当前投放模式自动按需隐藏桌面桌宠（水冷屏投放时隐藏桌面对应桌宠，停止或退出时无损恢复）
- 快捷键注入（Alt×2 激活大肥鱼语音、Ctrl+Shift+L 呼出小女仆对话、Ctrl+Shift+M 录音、Z 睡眠唤醒）
"""
from __future__ import annotations

import ctypes
import logging
import os
import threading
import time

log = logging.getLogger('bigfish.win32')

SW_HIDE = 0
SW_SHOW = 5
SW_SHOWNOACTIVATE = 4

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12       # Alt 键
VK_L = 0x4C          # L 键
VK_M = 0x4D          # M 键
VK_Z = 0x5A          # Z 键
KEYEVENTF_KEYUP = 0x0002

_user32 = ctypes.WinDLL('user32', use_last_error=True)
_WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
_user32.EnumWindows.argtypes = [_WNDENUMPROC, ctypes.c_void_p]
_user32.EnumWindows.restype = ctypes.c_bool

_last_coop_visible: bool | None = None
_last_dsh_visible: bool | None = None
_last_dsh_api_display: str | None = None


def _find_windows_by_filter(filter_fn) -> list[tuple[int, int]]:
    """通用的 Windows 桌面窗口枚举器（零句柄泄漏）。"""
    my_pid = os.getpid()
    buf = ctypes.create_unicode_buffer(512)
    cls_buf = ctypes.create_unicode_buffer(256)
    result: list[tuple[int, int]] = []

    def cb(hwnd, _):
        pid = ctypes.c_ulong()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == my_pid:
            return True

        _user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value
        _user32.GetClassNameW(hwnd, cls_buf, 256)
        cls_name = cls_buf.value

        # 排除自身与无关进程窗口
        if any(ex in title for ex in ('BigFishTitan', 'DshPetConsole', 'TcomasPetConsole', 'TCOMAS', 'Edge', '控制台', '安装')):
            return True

        if filter_fn(title, cls_name):
            result.append((hwnd, pid.value))
        return True

    cb_proc = _WNDENUMPROC(cb)
    _user32.EnumWindows(cb_proc, 0)
    return result


# ---------------------------------------------------------------- Coopanion 大肥鱼窗口
def find_coopanion_windows() -> list[tuple[int, int]]:
    """枚举桌面上的 Coopanion (Cortico) 窗口。"""
    def check_coop(title: str, cls_name: str) -> bool:
        if 'Cortico' in title and 'Tool' not in title:
            return True
        if 'Coopanion' in title and 'Setup' not in title and 'Update' not in title:
            return True
        return False

    return _find_windows_by_filter(check_coop)


def is_coopanion_running() -> bool:
    """检测 Coopanion 是否在运行。"""
    return len(find_coopanion_windows()) > 0


def set_desktop_coopanion_visible(visible: bool, force: bool = False):
    """设置桌面 Coopanion 窗口的显隐状态。"""
    global _last_coop_visible
    windows = find_coopanion_windows()
    changed = (_last_coop_visible != visible) or force
    _last_coop_visible = visible

    for hwnd, _pid in windows:
        is_vis = bool(_user32.IsWindowVisible(hwnd))
        if visible and (not is_vis or force):
            _user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            _user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(-1), 0, 0, 0, 0,
                                0x0001 | 0x0002 | 0x0040)
        elif not visible and (is_vis or force):
            _user32.ShowWindow(hwnd, SW_HIDE)
            _user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(0), 0, 0, 0, 0,
                                0x0001 | 0x0002 | 0x0080)
    if windows and changed:
        log.info('已将桌面 Coopanion (大肥鱼) 窗口设置为: %s', '显示' if visible else '隐藏')


# ---------------------------------------------------------------- DeepSeek dsh-pet 窗口
def find_dsh_windows() -> list[tuple[int, int]]:
    """枚举桌面上的 dsh-pet 窗口。"""
    def check_dsh(title: str, cls_name: str) -> bool:
        if 'Cortico' in title or 'Coopanion' in title:
            return False
        if '桌宠（桌面模式）' in title or title == 'dsh-pet 桌宠':
            return True
        if 'Chrome_WidgetWin' in cls_name and ('桌宠' in title or title.startswith('dsh-pet')):
            return True
        return False

    return _find_windows_by_filter(check_dsh)


def is_dsh_running() -> bool:
    """检测 dsh-pet 桌面窗口是否在运行。"""
    return len(find_dsh_windows()) > 0


def set_desktop_dsh_visible(visible: bool, dsh_client=None, force: bool = False, sync_api: bool = False):
    """设置桌面 dsh-pet 窗口的显隐状态（双保险：异步 API + Win32）。"""
    global _last_dsh_visible, _last_dsh_api_display
    changed = (_last_dsh_visible != visible) or force
    _last_dsh_visible = visible

    # 1. DSH 原生 API（仅在连接就绪且目标状态跳变时后台异步调用，绝不阻塞 UI 主线程）
    if dsh_client is not None and getattr(dsh_client, 'is_connected', False):
        target_display = 'both' if visible else 'web'
        if force or _last_dsh_api_display != target_display:
            _last_dsh_api_display = target_display
            if sync_api:
                try:
                    dsh_client.set_display(target_display)
                except Exception:
                    pass
            else:
                threading.Thread(
                    target=dsh_client.set_display,
                    args=(target_display,),
                    daemon=True,
                ).start()

    # 2. Win32 API
    windows = find_dsh_windows()
    for hwnd, _pid in windows:
        is_vis = bool(_user32.IsWindowVisible(hwnd))
        if visible and (not is_vis or force):
            _user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            _user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(-1), 0, 0, 0, 0,
                                0x0001 | 0x0002 | 0x0040)
        elif not visible and (is_vis or force):
            _user32.ShowWindow(hwnd, SW_HIDE)
            _user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(0), 0, 0, 0, 0,
                                0x0001 | 0x0002 | 0x0080)
    if windows and changed:
        log.info('已将桌面 dsh-pet (蓝毛女仆) 窗口设置为: %s', '显示' if visible else '隐藏')


# ---------------------------------------------------------------- 双宠综合状态同步
def sync_desktop_pets(
    cast_coopanion: bool,
    cast_dsh: bool,
    hide_desktop_pet: bool,
    dsh_client=None,
    force: bool = False
):
    """根据投放模式与互斥开关，原子同步桌面两只宠物的显隐状态。"""
    if not hide_desktop_pet:
        set_desktop_coopanion_visible(True, force=force)
        set_desktop_dsh_visible(True, dsh_client=dsh_client, force=force)
        return

    coop_target = not cast_coopanion
    dsh_target = not cast_dsh

    set_desktop_coopanion_visible(coop_target, force=force)
    set_desktop_dsh_visible(dsh_target, dsh_client=dsh_client, force=force)


def restore_all_desktop_pets(dsh_client=None):
    """安全退出或暂停推流时，无损恢复桌面全部桌宠显示。"""
    log.info('正在恢复所有桌面桌宠显示...')
    set_desktop_coopanion_visible(True, force=True)
    set_desktop_dsh_visible(True, dsh_client=dsh_client, force=True, sync_api=True)


# ---------------------------------------------------------------- 快捷键模拟
def trigger_coopanion_voice():
    """模拟连续双击 Alt (Alt×2)，激活 Coopanion 专属全局语音输入。"""
    def _send():
        try:
            _user32.keybd_event(VK_MENU, 0, 0, 0)
            _user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.06)
            _user32.keybd_event(VK_MENU, 0, 0, 0)
            _user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            log.info('已发送 Alt×2 唤醒 Coopanion 语音')
        except Exception as e:
            log.warning('模拟 Alt×2 失败: %s', e)
    threading.Thread(target=_send, daemon=True).start()


def trigger_dsh_chat():
    """模拟 Ctrl + Shift + L，唤起 dsh-pet 浮动对话框。"""
    def _send():
        try:
            _user32.keybd_event(VK_CONTROL, 0, 0, 0)
            _user32.keybd_event(VK_SHIFT, 0, 0, 0)
            _user32.keybd_event(VK_L, 0, 0, 0)
            time.sleep(0.05)
            _user32.keybd_event(VK_L, 0, KEYEVENTF_KEYUP, 0)
            _user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
            _user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
        except Exception as e:
            log.warning('模拟 Ctrl+Shift+L 失败: %s', e)
    threading.Thread(target=_send, daemon=True).start()


def trigger_dsh_voice():
    """模拟 Ctrl + Shift + M，触发 dsh-pet 语音录制。"""
    def _send():
        try:
            _user32.keybd_event(VK_CONTROL, 0, 0, 0)
            _user32.keybd_event(VK_SHIFT, 0, 0, 0)
            _user32.keybd_event(VK_M, 0, 0, 0)
            time.sleep(0.05)
            _user32.keybd_event(VK_M, 0, KEYEVENTF_KEYUP, 0)
            _user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
            _user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
        except Exception as e:
            log.warning('模拟 Ctrl+Shift+M 失败: %s', e)
    threading.Thread(target=_send, daemon=True).start()


def trigger_dsh_sleep():
    """模拟轻按 Z 键，切换 dsh-pet 睡觉/唤醒状态。"""
    def _send():
        try:
            _user32.keybd_event(VK_Z, 0, 0, 0)
            time.sleep(0.04)
            _user32.keybd_event(VK_Z, 0, KEYEVENTF_KEYUP, 0)
        except Exception as e:
            log.warning('模拟按 Z 键失败: %s', e)
    threading.Thread(target=_send, daemon=True).start()


def touch_desktop_pet():
    """轻抚主桌面大肥鱼（模拟点击桌面桌宠窗口中心）。"""
    try:
        class RECT(ctypes.Structure):
            _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long),
                        ('right', ctypes.c_long), ('bottom', ctypes.c_long)]
        rect = RECT()
        windows = find_coopanion_windows()
        for hwnd, _pid in windows:
            if _user32.IsWindowVisible(hwnd):
                if _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    w = rect.right - rect.left
                    h = rect.bottom - rect.top
                    cx = int(w * 0.5)
                    cy = int(h * 0.72)
                    lparam = (cy << 16) | (cx & 0xFFFF)
                    WM_LBUTTONDOWN = 0x0201
                    WM_LBUTTONUP = 0x0202
                    _user32.PostMessageW(hwnd, WM_LBUTTONDOWN, 1, lparam)
                    _user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
                    log.info('已向桌面 Coopanion 窗口发送摸头消息 (hwnd: %s)', hwnd)
    except Exception as e:
        log.warning('touch_desktop_pet 异常: %s', e)
