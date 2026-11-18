# -*- coding: utf-8 -*-
"""win32_dsh.py — Win32 窗口管理与快捷键模拟。

功能：
- 枚举并识别 'dsh-pet 桌宠（桌面模式）' 窗口句柄
- 双屏互斥显隐控制：水冷屏运作时静默隐藏桌面大肥鱼，停止或退出时恢复
- 全局快捷键注入（Ctrl+Shift+L 呼出对话，Ctrl+Shift+M 语音录制，Z 睡觉/唤醒）
"""
from __future__ import annotations

import ctypes
import os
import time
import logging

log = logging.getLogger('dsh.win32')

SW_HIDE = 0
SW_SHOW = 5
SW_SHOWNOACTIVATE = 4

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12       # Alt
VK_L = 0x4C          # L 键
VK_M = 0x4D          # M 键
VK_Z = 0x5A          # Z 键
KEYEVENTF_KEYUP = 0x0002

_last_visible_state: bool | None = None


def _find_dsh_windows() -> list[tuple[int, int]]:
    """枚举桌面上的 dsh-pet 透明窗口 (hwnd, pid)。"""
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    my_pid = os.getpid()
    buf = ctypes.create_unicode_buffer(512)
    cls_buf = ctypes.create_unicode_buffer(256)
    result = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(hwnd, _):
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == my_pid:
            return True

        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value
        user32.GetClassNameW(hwnd, cls_buf, 256)
        cls_name = cls_buf.value

        # 严格排除自身与其它应用窗口
        if any(ex in title for ex in ('DeepSeek Harness', 'TCOMAS', 'Edge', 'DshPetConsole', '控制台', '安装')):
            return True

        # 精准匹配 dsh-pet 桌面模式专属窗口
        if '桌宠（桌面模式）' in title or title == 'dsh-pet 桌宠':
            result.append((hwnd, pid.value))
        elif 'Chrome_WidgetWin' in cls_name and ('桌宠' in title or title.startswith('dsh-pet')):
            result.append((hwnd, pid.value))

        return True

    cb_proc = WNDENUMPROC(cb)
    user32.EnumWindows.argtypes = [WNDENUMPROC, ctypes.c_void_p]
    user32.EnumWindows.restype = ctypes.c_bool
    user32.EnumWindows(cb_proc, 0)
    return result


def is_desktop_dsh_pet_running() -> bool:
    """检测当前桌面端 dsh-pet 是否正在运行。"""
    return len(_find_dsh_windows()) > 0


def set_desktop_dsh_pet_visible(visible: bool, dsh_client=None, force: bool = False):
    """显示或隐藏桌面端的 dsh-pet 窗口（双保险：API + Win32）。"""
    global _last_visible_state
    if not force and _last_visible_state == visible:
        return
    _last_visible_state = visible

    # 1. 尝试通过 DSH 原生 /pet-display API 静默切换显示模式
    if dsh_client is not None:
        try:
            target_display = 'both' if visible else 'web'
            dsh_client.set_display(target_display)
            log.info('通过 DSH API 设置桌宠显示状态: %s', target_display)
        except Exception as e:
            log.warning('通过 DSH API 设置桌宠显示状态失败: %s', e)

    # 2. Win32 窗口级显隐操作
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    windows = _find_dsh_windows()
    for hwnd, _pid in windows:
        if visible:
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(-1), 0, 0, 0, 0,
                                0x0001 | 0x0002 | 0x0040)  # SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
        else:
            user32.ShowWindow(hwnd, SW_HIDE)
            user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(0), 0, 0, 0, 0,
                                0x0001 | 0x0002 | 0x0080)  # SWP_NOSIZE | SWP_NOMOVE | SWP_HIDEWINDOW
    if windows:
        log.info('已将桌面 dsh-pet 窗口设置为: %s', '显示' if visible else '隐藏')


def trigger_chat_hotkey():
    """模拟按下 Ctrl + Shift + L，唤起 dsh-pet 浮动对话弹窗。"""
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    try:
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_SHIFT, 0, 0, 0)
        user32.keybd_event(VK_L, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_L, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
    except Exception as e:
        log.warning('发送 Ctrl+Shift+L 失败: %s', e)


def trigger_voice_hotkey():
    """模拟按下 Ctrl + Shift + M，切换 dsh-pet 语音录音。"""
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    try:
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_SHIFT, 0, 0, 0)
        user32.keybd_event(VK_M, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_M, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
    except Exception as e:
        log.warning('发送 Ctrl+Shift+M 失败: %s', e)


def trigger_sleep_toggle():
    """向桌宠窗口发送 Z 键（睡觉 / 叫醒）。"""
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    try:
        user32.keybd_event(VK_Z, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_Z, 0, KEYEVENTF_KEYUP, 0)
    except Exception as e:
        log.warning('发送 Z 键失败: %s', e)
