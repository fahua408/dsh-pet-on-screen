# -*- coding: utf-8 -*-
"""config.py — 大肥鱼桌宠钛坦屏投放工具持久化配置管理。

默认存储路径：%APPDATA%/BigFishTitanConsole/config.json
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger('bigfish.config')


def _default_config_path() -> Path:
    app_data = os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming')
    return Path(app_data) / 'BigFishTitanConsole' / 'config.json'


CONFIG_PATH: Path = _default_config_path()


@dataclass
class AppConfig:
    """持久化配置（JSON 文件存储）。"""
    # 投放中枢与多宠调度配置
    cast_mode: str = 'dual'             # 投放模式：'coopanion' | 'dsh' | 'dual'
    cast_coopanion: bool = True         # 选择性投放：是否投放大肥鱼
    cast_dsh: bool = True               # 选择性投放：是否投放蓝毛女仆
    dual_layout: str = 'side_by_side'   # 双宠同屏布局：side_by_side | coopanion_main | dsh_main | overlay
    control_target: str = 'coopanion'   # 双宠同屏时的悬浮球默认控制目标：'coopanion' | 'dsh'

    # 大肥鱼 (Coopanion) 专属参数
    coopanion_url: str = 'http://127.0.0.1:7797/pet'
    coopanion_scale: float = 1.6        # 缩放 (1.0, 1.25, 1.6, 2.0, 2.5, 3.2)

    # 蓝毛女仆 (dsh-pet) 专属参数
    scale: float = 1.0                  # 女仆缩放 (0.5 ~ 1.5)
    offset_x: int = 0                   # 水平偏移 (-150 ~ +150 px)
    offset_y: int = 0                   # 垂直偏移 (-150 ~ +150 px)
    bubble_scale: float = 1.0           # 对话气泡缩放 (0.8 ~ 2.0)
    dsh_port: int = 0                   # DSH 端口（0 为自动探测）

    # 屏幕与背景
    bg_mode: str = 'dots'               # 背景模式：dots | color | image
    bg_value: str = '#0D1117'           # 背景图路径或色值
    pushing: bool = True                # 水冷屏推流总开关
    hide_desktop_pet: bool = True       # 推流时隐藏桌面对应桌宠 (双保险)

    # 悬浮球与桌面体验
    ball_x: int = -1                    # 悬浮球 X 坐标
    ball_y: int = -1                    # 悬浮球 Y 坐标
    ball_snap: bool = True              # 边缘贴边磁吸
    ball_peek: bool = True              # 贴边半藏
    autostart: bool = False             # 开机自启
    close_to_tray: bool = True          # 关闭窗口最小化至托盘


def load_config(path: Path | None = None) -> AppConfig:
    p = Path(path) if path else CONFIG_PATH
    if not p.is_file():
        log.info('配置文件不存在，使用默认配置: %s', p)
        return AppConfig()
    try:
        raw = json.loads(p.read_text(encoding='utf-8'))
        known = {f.name for f in AppConfig.__dataclass_fields__.values()}
        filtered = {k: v for k, v in raw.items() if k in known}
        cfg = AppConfig(**filtered)
        # 修复非法状态：如果cast_mode不在预期集合内，自动归正
        if cfg.cast_mode not in ('coopanion', 'dsh', 'dual'):
            cfg.cast_mode = 'dual'
        if cfg.cast_mode == 'coopanion':
            cfg.cast_coopanion, cfg.cast_dsh = True, False
        elif cfg.cast_mode == 'dsh':
            cfg.cast_coopanion, cfg.cast_dsh = False, True
        else:
            cfg.cast_coopanion, cfg.cast_dsh = True, True
        return cfg
    except Exception as e:
        log.warning('读取配置失败，使用默认配置: %s — %s', p, e)
        return AppConfig()


def save_config(cfg: AppConfig, path: Path | None = None):
    p = Path(path) if path else CONFIG_PATH
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp_p = p.with_suffix('.json.tmp')
        tmp_p.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding='utf-8')
        tmp_p.replace(p)
    except Exception as e:
        log.error('保存配置失败: %s — %s', p, e)


class SettingsSnapshot(dict):
    """支持字典键查询与元组解包 (scale, bg_mode, bg_value, pushing, ver) 的双用快照对象。"""
    def __iter__(self):
        yield self.get('scale', 1.0)
        yield self.get('bg_mode', 'dots')
        yield self.get('bg_value', '#0D1117')
        yield self.get('pushing', True)
        yield self.get('version', 0)


@dataclass
class Settings:
    """线程间共享运行时设置（支持防抖异步落盘，避免滑块高频拖拽阻塞 UI）。"""
    cast_mode: str = 'dual'
    cast_coopanion: bool = True
    cast_dsh: bool = True
    dual_layout: str = 'side_by_side'
    control_target: str = 'coopanion'

    coopanion_url: str = 'http://127.0.0.1:7797/pet'
    coopanion_scale: float = 1.6

    scale: float = 1.0
    offset_x: int = 0
    offset_y: int = 0
    bubble_scale: float = 1.0
    bg_mode: str = 'dots'
    bg_value: str = '#0D1117'
    pushing: bool = True
    hide_desktop_pet: bool = True
    ball_snap: bool = True
    ball_peek: bool = True
    autostart: bool = False
    close_to_tray: bool = True

    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _version: int = field(default=0, init=False, repr=False)
    _save_timer: threading.Timer | None = field(default=None, init=False, repr=False)
    _cfg: AppConfig | None = field(default=None, init=False, repr=False)

    def snapshot(self) -> SettingsSnapshot:
        with self._lock:
            return SettingsSnapshot({
                'cast_mode': self.cast_mode,
                'cast_coopanion': self.cast_coopanion,
                'cast_dsh': self.cast_dsh,
                'dual_layout': self.dual_layout,
                'control_target': self.control_target,
                'coopanion_scale': self.coopanion_scale,
                'scale': self.scale,
                'offset_x': self.offset_x,
                'offset_y': self.offset_y,
                'bubble_scale': self.bubble_scale,
                'bg_mode': self.bg_mode,
                'bg_value': self.bg_value,
                'pushing': self.pushing,
                'hide_desktop_pet': self.hide_desktop_pet,
                'ball_snap': self.ball_snap,
                'ball_peek': self.ball_peek,
                'autostart': self.autostart,
                'close_to_tray': self.close_to_tray,
                'version': self._version
            })

    def update(self, **kwargs) -> int:
        with self._lock:
            if self._cfg is None:
                self._cfg = load_config()
            for k, v in kwargs.items():
                if hasattr(self, k) and not k.startswith('_'):
                    setattr(self, k, v)
                if hasattr(self._cfg, k):
                    setattr(self._cfg, k, v)
            self._version += 1
            ver = self._version

            if self._save_timer is not None:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(0.25, self.flush)
            self._save_timer.daemon = True
            self._save_timer.start()
        return ver

    def flush(self):
        """立即将内存中的最新配置写入磁盘。"""
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
            if self._cfg is None:
                return
            cfg_copy = AppConfig(**asdict(self._cfg))
        save_config(cfg_copy)


_GLOBAL_SETTINGS: Settings | None = None


def get_settings() -> Settings:
    global _GLOBAL_SETTINGS
    if _GLOBAL_SETTINGS is None:
        cfg = load_config()
        s = Settings(
            cast_mode=getattr(cfg, 'cast_mode', 'dual'),
            cast_coopanion=getattr(cfg, 'cast_coopanion', True),
            cast_dsh=getattr(cfg, 'cast_dsh', True),
            dual_layout=getattr(cfg, 'dual_layout', 'side_by_side'),
            control_target=getattr(cfg, 'control_target', 'coopanion'),
            coopanion_url=getattr(cfg, 'coopanion_url', 'http://127.0.0.1:7797/pet'),
            coopanion_scale=getattr(cfg, 'coopanion_scale', 1.6),
            scale=cfg.scale,
            offset_x=cfg.offset_x,
            offset_y=cfg.offset_y,
            bubble_scale=getattr(cfg, 'bubble_scale', 1.0),
            bg_mode=cfg.bg_mode,
            bg_value=cfg.bg_value,
            pushing=cfg.pushing,
            hide_desktop_pet=cfg.hide_desktop_pet,
            ball_snap=getattr(cfg, 'ball_snap', True),
            ball_peek=getattr(cfg, 'ball_peek', True),
            autostart=getattr(cfg, 'autostart', False),
            close_to_tray=getattr(cfg, 'close_to_tray', True),
        )
        s._cfg = cfg
        _GLOBAL_SETTINGS = s
    return _GLOBAL_SETTINGS
