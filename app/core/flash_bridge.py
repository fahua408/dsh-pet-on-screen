# -*- coding: utf-8 -*-
"""flash_bridge.py — Flash 固件管理（开机动画/待机壁纸读写）。

整合 lg700_core.py 的核心协议函数，以 Python 信号驱动的线程方式封装。
读写 Flash 时会自动暂停 DataPusher（释放 USB 总线），刷写后自动恢复推流。

功能：
- FlashSignals    PySide6 信号集合（进度、完成）
- FlashBridge     Flash 固件管理入口类
"""
from __future__ import annotations

import io
import logging
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from .pusher import DataPusher

log = logging.getLogger('tcomas.flash_bridge')

# ---- lg700_core 所在目录加入 sys.path（开发环境 + PyInstaller 打包兼容） ----
def _resolve_tool_src() -> Path:
    """定位 lg700_core.py 所在目录，兼容开发环境与 PyInstaller 打包后的路径。"""
    # 1. PyInstaller 打包后，--add-data 将 lg700_tool_src 释放到 sys._MEIPASS/lg700_tool_src
    if hasattr(sys, '_MEIPASS'):
        p = Path(sys._MEIPASS) / 'lg700_tool_src'
        if p.exists():
            return p
    # 2. 当前工程内置独立源码: app/lg700_tool_src
    local_src = Path(__file__).resolve().parent.parent / 'lg700_tool_src'
    if local_src.exists():
        return local_src
    # 3. 兜底回退：外部 tools 目录
    p = Path(__file__).resolve().parents[3] / (
        'tools/LG700Tool/TCOMAS-Boot-Animation-Tool-v1.2.11-windows-x64/source/src'
    )
    return p

_TOOL_SRC = _resolve_tool_src()
if _TOOL_SRC.exists() and str(_TOOL_SRC) not in sys.path:
    sys.path.insert(0, str(_TOOL_SRC))
elif not _TOOL_SRC.exists():
    log.warning('lg700_core 源码目录未找到，Flash 刷写功能将不可用：%s', _TOOL_SRC)

# 延迟 import lg700_core（运行环境可能没装 PIL/hidapi，只在实际调用时才报错）

# ---------------------------------------------------------------- 验证常量
_MAX_STANDBY_BYTES = 950 * 1024   # 待机壁纸最大 950 KB
_MAX_BOOT_BYTES = 9_500 * 1024    # 开机动画总包最大 9.5 MB
_SCREEN_W, _SCREEN_H = 640, 480   # LG700 分辨率


# ---------------------------------------------------------------- 信号

class FlashSignals(QObject):
    """FlashBridge 对外暴露的 PySide6 信号。"""

    # percent: 0–100，message: 进度文字
    progress_updated = Signal(int, str)

    # success: 操作是否成功，message: 完成文字（失败时含错误信息）
    completed = Signal(bool, str)


# ---------------------------------------------------------------- 设备打开辅助
def _open_device():
    """打开 LG700 设备句柄，无 hidapi.dll C库依赖，使用纯 Windows HID。"""
    from .device import find_command_iface
    from device_profiles import LG700_PROFILE
    import lg700_core as core
    import struct

    class SafeLG700(core.LG700):
        def __init__(self):
            self.hid = None
            self._mutex = None
            self._kernel = None

            iface = find_command_iface()
            if not iface:
                raise RuntimeError("未找到 LG700 MI_00 接口")
            self.info = iface
            self._profile = LG700_PROFILE

            if sys.platform.startswith('win'):
                import ctypes
                from ctypes import wintypes
                self._kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                self._kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
                self._kernel.CreateMutexW.restype = wintypes.HANDLE
                self._kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                self._kernel.WaitForSingleObject.restype = wintypes.DWORD
                self._kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
                self._kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                handle = self._kernel.CreateMutexW(None, False, 'Local\\TCOMAS_LG700_Asset_IO')
                if not handle:
                    raise OSError('无法创建通信锁')
                status = self._kernel.WaitForSingleObject(handle, 2000)
                if status not in (0, 0x80):
                    self._kernel.CloseHandle(handle)
                    raise RuntimeError('另一个写入工具正在使用屏幕，请稍候重试')
                self._mutex = handle

            self.hid = core.open_command_transport(self.info["path"])
            self.revision = struct.unpack_from("<H", self.query(0x87))[0]

    return SafeLG700()


# ---------------------------------------------------------------- Flash 管理

class FlashBridge:
    """LG700 Flash 固件管理（开机动画 + 待机壁纸读写）。

    所有耗时操作均在调用方提供的线程中执行（或可由外部包装为线程），
    通过 FlashSignals 信号回报进度与结果。

    注意：Flash 读写期间必须关闭 DataPusher（释放 USB 总线）。
    """

    def __init__(self, signals: FlashSignals | 'DataPusher', pusher: 'DataPusher | FlashSignals | None' = None):
        """
        Args:
            signals: 信号对象，用于回报进度与完成状态（兼容 (signals, pusher) 与 (pusher, signals) 两种传参顺序）
            pusher:  推流线程实例（可选）；若提供，刷写前后自动 pause/resume
        """
        if isinstance(signals, FlashSignals):
            self.signals = signals
            self.pusher = pusher
        elif isinstance(pusher, FlashSignals):
            self.signals = pusher
            self.pusher = signals
        else:
            self.signals = signals  # type: ignore[assignment]
            self.pusher = pusher
        self._lock = threading.Lock()   # 防止并发刷写

    # ---- 公开接口 ----------------------------------------------------

    def read_current_info(self) -> dict:
        """只读探测设备信息，不写入任何数据。

        Returns:
            {
                'boot_size':     int,   # 开机动画区已用字节数
                'boot_frames':   int,   # 开机动画帧数
                'standby_size':  int,   # 待机壁纸字节数
                'firmware_ver':  str,   # 固件版本（十六进制字符串，如 '0067'）
            }

        Raises:
            RuntimeError: 设备未连接或通信失败
        """
        import lg700_core as core  # noqa: PLC0415
        with self._lock:
            with _open_device() as dev:
                ver = f'{dev.revision:04X}'
                # 读取待机图元数据（selector=0）
                try:
                    standby_meta = dev.metadata(0)
                    standby_size = standby_meta.get('size', 0)
                except OSError:
                    standby_size = 0
                # 读取开机动画元数据（selector=1）
                try:
                    boot_meta = dev.metadata(1)
                    boot_size = boot_meta.get('size', 0)
                    # 解析帧数（需要实际读取包头，暂用 0 表示空槽）
                    if core.is_empty_boot(boot_meta, dev.profile):
                        boot_frames = 0
                        boot_size = 0
                    else:
                        # 仅读取少量数据以解析帧数（避免读取全部内容）
                        try:
                            raw_head, _ = dev.read_asset(1, progress=lambda _: None)
                            from lg700_core import unpack_boot  # noqa: PLC0415
                            frames = unpack_boot(raw_head, inspect_jpeg=False)
                            boot_frames = len(frames)
                        except Exception:
                            boot_frames = -1  # 无法解析时返回 -1
                except OSError:
                    boot_size = 0
                    boot_frames = 0
        return {
            'boot_size': boot_size,
            'boot_frames': boot_frames,
            'standby_size': standby_size,
            'firmware_ver': ver,
        }

    def write_standby(self, jpeg_bytes: bytes, backup_directory: Path) -> None:
        """刷写待机壁纸（selector=0）。

        执行步骤：
          1. 验证 JPEG（非渐进式，≤950KB，640×480）
          2. 暂停 DataPusher 推流（释放 USB 总线）
          3. 调用 LG700 协议擦写 Flash Region 0
          4. 恢复 DataPusher 推流
          5. 通过 signals 回报进度与结果

        Args:
            jpeg_bytes:       待机壁纸 JPEG 数据
            backup_directory: 刷写前备份目录（lg700_core.write_asset 要求）

        Raises:
            ValueError: JPEG 验证失败
            OSError:    HID 通信失败
        """
        self._run_in_background(self._do_write_standby, jpeg_bytes, backup_directory)

    def write_boot(self, jpeg_frames: list[bytes], backup_directory: Path) -> None:
        """刷写开机动画帧序列（selector=1）。

        执行步骤：
          1. 验证每帧 JPEG 并检查总大小 ≤9.5MB
          2. 调用 pack_boot() 打包
          3. 暂停 DataPusher 推流
          4. 擦写 Flash Region 1
          5. 恢复推流

        Args:
            jpeg_frames:      帧 JPEG 列表
            backup_directory: 备份目录
        """
        self._run_in_background(self._do_write_boot, jpeg_frames, backup_directory)

    def restore_factory(self, defaults_dir: Path) -> None:
        """从 defaults/ 目录恢复出厂 boot.bin 和 standby.bin。

        Args:
            defaults_dir: 包含 manifest.json + boot.bin + standby.bin 的目录
        """
        self._run_in_background(self._do_restore_factory, defaults_dir)

    # ---- 内部：后台线程包装 ------------------------------------------

    def _run_in_background(self, func, *args):
        """在后台线程中执行耗时操作（防止阻塞 UI 线程）。"""
        t = threading.Thread(target=self._safe_call, args=(func, *args), daemon=True)
        t.start()

    def _safe_call(self, func, *args):
        """捕获所有异常并通过 signals.completed emit 结果。"""
        with self._lock:
            try:
                func(*args)
            except Exception as e:  # noqa: BLE001
                log.exception('FlashBridge 操作失败：%s', e)
                self.signals.completed.emit(False, f'失败：{type(e).__name__}: {e}')

    # ---- 内部：推流暂停 / 恢复 ----------------------------------------

    def _pause_pusher(self):
        """暂停推流线程（若存在），释放 USB 总线供 Flash 操作使用。"""
        if self.pusher is not None:
            self.pusher.pause()
            log.info('FlashBridge: DataPusher 已暂停')

    def _resume_pusher(self):
        """恢复推流线程。"""
        if self.pusher is not None:
            self.pusher.resume()
            log.info('FlashBridge: DataPusher 已恢复')

    # ---- 内部：具体操作 -----------------------------------------------

    def _do_write_standby(self, jpeg_bytes: bytes, backup_directory: Path):
        """待机壁纸刷写的实际实现（在后台线程调用）。"""
        import lg700_core as core  # noqa: PLC0415
        from lg700_core import validate_jpeg  # noqa: PLC0415
        from device_profiles import LG700_PROFILE  # noqa: PLC0415

        # 1. 验证 JPEG
        self.signals.progress_updated.emit(0, '验证 JPEG…')
        if len(jpeg_bytes) > _MAX_STANDBY_BYTES:
            raise ValueError(f'待机壁纸超过 950 KB 限制：{len(jpeg_bytes):,} 字节')
        validate_jpeg(jpeg_bytes, LG700_PROFILE, '待机壁纸')
        self.signals.progress_updated.emit(5, 'JPEG 验证通过')

        # 2. 暂停推流
        self._pause_pusher()
        try:
            # 3. 刷写
            with _open_device() as dev:
                def _progress(p: float):
                    pct = 10 + int(p * 85)
                    self.signals.progress_updated.emit(pct, f'写入中… {pct}%')

                self.signals.progress_updated.emit(10, '开始擦写 Flash Region 0…')
                sha = dev.write_asset(0, jpeg_bytes, str(backup_directory),
                                      progress=_progress)
                self.signals.progress_updated.emit(100, f'刷写完成，SHA-256: {sha[:8]}…')
                self.signals.completed.emit(True, f'待机壁纸刷写成功（{len(jpeg_bytes):,} 字节）')
        finally:
            # 4. 恢复推流
            self._resume_pusher()

    def _do_write_boot(self, jpeg_frames: list[bytes], backup_directory: Path):
        """开机动画刷写的实际实现（在后台线程调用）。"""
        import lg700_core as core  # noqa: PLC0415
        from lg700_core import pack_boot, validate_jpeg  # noqa: PLC0415
        from device_profiles import LG700_PROFILE  # noqa: PLC0415

        # 1. 验证帧序列
        self.signals.progress_updated.emit(0, f'验证 {len(jpeg_frames)} 帧 JPEG…')
        for i, frame in enumerate(jpeg_frames):
            validate_jpeg(frame, LG700_PROFILE, f'开机动画第 {i + 1} 帧')

        # 2. 打包
        self.signals.progress_updated.emit(3, '打包开机动画…')
        boot_data = pack_boot(jpeg_frames)
        if len(boot_data) > _MAX_BOOT_BYTES:
            raise ValueError(f'开机动画包超过 9.5 MB 限制：{len(boot_data):,} 字节')
        self.signals.progress_updated.emit(8, f'打包完成，共 {len(boot_data):,} 字节')

        # 3. 暂停推流
        self._pause_pusher()
        try:
            # 4. 擦写
            with _open_device() as dev:
                def _progress(p: float):
                    pct = 10 + int(p * 85)
                    self.signals.progress_updated.emit(pct, f'写入中… {pct}%')

                self.signals.progress_updated.emit(10, '开始擦写 Flash Region 1…')
                sha = dev.write_asset(1, boot_data, str(backup_directory),
                                      progress=_progress)
                self.signals.progress_updated.emit(100, f'刷写完成，SHA-256: {sha[:8]}…')
                self.signals.completed.emit(
                    True,
                    f'开机动画刷写成功（{len(jpeg_frames)} 帧，{len(boot_data):,} 字节）',
                )
        finally:
            # 5. 恢复推流
            self._resume_pusher()

    def _do_restore_factory(self, defaults_dir: Path):
        """从出厂备份目录恢复 boot + standby 的实际实现（在后台线程调用）。"""
        import lg700_core as core  # noqa: PLC0415
        from lg700_core import restore_file  # noqa: PLC0415

        defaults_dir = Path(defaults_dir).resolve()
        self.signals.progress_updated.emit(0, f'读取出厂备份：{defaults_dir}')

        # 验证备份目录结构
        manifest_path = defaults_dir / 'manifest.json'
        if not manifest_path.is_file():
            raise FileNotFoundError(f'出厂备份目录缺少 manifest.json：{defaults_dir}')

        # 读取备份数据（restore_file 内部会校验 SHA-256 和协议合法性）
        self.signals.progress_updated.emit(5, '校验 standby.bin…')
        standby_data = restore_file(defaults_dir, 0, allow_empty=False)
        self.signals.progress_updated.emit(15, '校验 boot.bin…')
        boot_data = restore_file(defaults_dir, 1, allow_empty=True)
        self.signals.progress_updated.emit(20, '备份校验通过，开始恢复…')

        # 暂停推流
        self._pause_pusher()
        try:
            with _open_device() as dev:
                # 恢复待机壁纸
                if standby_data:
                    def _sp(p: float):
                        pct = 20 + int(p * 35)
                        self.signals.progress_updated.emit(pct, f'恢复待机壁纸… {pct}%')
                    self.signals.progress_updated.emit(20, '恢复待机壁纸…')
                    dev.write_asset(0, standby_data, str(defaults_dir),
                                    progress=_sp, recovery=True)
                    self.signals.progress_updated.emit(55, '待机壁纸恢复完成')

                # 恢复开机动画（可能为空槽）
                if boot_data:
                    def _bp(p: float):
                        pct = 55 + int(p * 40)
                        self.signals.progress_updated.emit(pct, f'恢复开机动画… {pct}%')
                    self.signals.progress_updated.emit(55, '恢复开机动画…')
                    dev.write_asset(1, boot_data, str(defaults_dir),
                                    progress=_bp, recovery=True)
                self.signals.progress_updated.emit(100, '出厂恢复完成')
                self.signals.completed.emit(True, '已成功恢复出厂固件资产')
        finally:
            self._resume_pusher()
