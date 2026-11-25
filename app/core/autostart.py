# -*- coding: utf-8 -*-
"""autostart.py — Windows 开机自启动注册表管理。"""
from __future__ import annotations

import sys
import winreg
from pathlib import Path

_RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
_APP_NAME = 'BigFishTitanConsole'
_LEGACY_NAMES = ('TcomasPetConsole', 'DshPetConsole')


def _get_target_cmd() -> str:
    """获取启动命令行。如果在打包环境中，返回 exe 绝对路径；否则返回 python 启动命令。"""
    if getattr(sys, 'frozen', False):
        exe = Path(sys.executable).resolve()
        return f'"{exe}" --autostart'
    exe = Path(sys.executable).resolve()
    main_py = Path(__file__).resolve().parent.parent / 'main.py'
    return f'"{exe}" "{main_py}" --autostart'


def is_autostart_enabled() -> bool:
    """检查是否已设置开机自启。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            for name in (_APP_NAME, *_LEGACY_NAMES):
                try:
                    winreg.QueryValueEx(key, name)
                    return True
                except OSError:
                    continue
            return False
    except OSError:
        return False


def set_autostart(enable: bool) -> bool:
    """设置或取消开机自启（同时自动清理旧版本的自启项）。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            for old_name in _LEGACY_NAMES:
                try:
                    winreg.DeleteValue(key, old_name)
                except OSError:
                    pass
            if enable:
                cmd = _get_target_cmd()
                winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, _APP_NAME)
                except OSError:
                    pass
            return True
    except OSError:
        return False
