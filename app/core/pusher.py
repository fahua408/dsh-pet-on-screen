# -*- coding: utf-8 -*-
"""pusher.py — 实时推流线程（MI_01 数据口，1025字节分包）。

功能：
- PusherSignals   PySide6 信号集合（状态更新、设备丢失、设备重连）
- DataPusher      推流工作线程，支持热插拔重连、FPS 统计、单写者互斥
"""
from __future__ import annotations

import logging
import queue
import struct
import threading
import time

try:
    import hid
except Exception:
    hid = None
from PySide6.QtCore import QObject, Signal

from .device import find_data_iface, DeviceLock, create_data_transport

log = logging.getLogger('tcomas.pusher')

# ---------------------------------------------------------------- 分包常量
PAYLOAD: int = 1020      # 每包有效载荷字节数（原 build_packets 保留）
REPORT_SIZE: int = 1025  # 完整 HID 报告大小（含 Report-ID 字节 0x00）

# 重连间隔与超时
_RECONNECT_INTERVAL = 3.0   # 秒，丢失后每 3 秒尝试一次重连
_FRAME_QUEUE_MAX = 2         # 帧队列最大深度，防止堆积太多帧


# ---------------------------------------------------------------- 信号

class PusherSignals(QObject):
    """DataPusher 对外暴露的 PySide6 信号。

    所有信号均在 DataPusher 工作线程内 emit，UI 层应通过 Qt 队列连接
    （connect(slot, Qt.QueuedConnection)）来保证线程安全。
    """

    # fps:   当前帧率（帧/秒）
    # kb:    当前帧大小（KB）
    # pkt:   当前帧包数
    # ok:    推流是否正常
    # msg:   状态文字
    status_updated = Signal(float, float, int, bool, str)

    # 设备断开时触发（USB 被拔出或写入失败）
    device_lost = Signal()

    # 重连成功后触发
    device_connected = Signal()


# ---------------------------------------------------------------- 分包算法（原样保留，一行不丢）

def build_packets(jpeg: bytes):
    """将一帧 JPEG 分解为 HID 分包序列（原 main.py build_packets 完整保留）。

    包格式：
      - 1025 字节（含 Report-ID 0x00）
      - 载荷 1020 字节
      - 包头：b'\\x00\\x08' + struct.pack('<H', count_or_seq) + (b'\\x80' if seq==0 else b'\\x00')
    """
    count = (len(jpeg) + PAYLOAD - 1) // PAYLOAD
    for seq in range(count):
        head = struct.pack('<H', count if seq == 0 else seq) + (b'\x80' if seq == 0 else b'\x00')
        yield b'\x00\x08' + head + jpeg[seq * PAYLOAD:(seq + 1) * PAYLOAD].ljust(PAYLOAD, b'\x00')


# ---------------------------------------------------------------- 推流线程

class DataPusher(threading.Thread):
    """独立推流线程，接收帧数据并通过 MI_01 HID 接口写入屏幕。

    外部线程（渲染线程）通过 push_frame() 投递 JPEG 帧；
    本线程负责分包、写入 HID、统计 FPS、处理断连重试。
    """

    def __init__(self, signals: PusherSignals):
        super().__init__(daemon=True, name='pusher')
        self.signals = signals

        # 帧队列：渲染线程放入，推流线程取出
        self._frame_queue: queue.Queue[bytes] = queue.Queue(maxsize=_FRAME_QUEUE_MAX)

        # 控制标志
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()   # set() = 暂停，clear() = 运行
        self._pushing = True                    # 是否开启推流（Settings.pushing 对应）

        # 状态统计
        self._fps_frames = 0
        self._fps_t0 = time.monotonic()
        self._last_kb = 0.0
        self._last_pkt = 0

        # 写者互斥：同一时间只有一个线程可以写 HID
        # 注意：这里用 threading.Lock 而非 DeviceLock（后者是跨进程的命名 Mutex）
        self._write_lock = threading.Lock()

        # HID 设备句柄（None 表示未连接）
        self._dev: any = None
        self._dev_lock = threading.Lock()   # 保护 _dev 的并发访问

    # ---- 公开控制接口 ------------------------------------------------

    def start_pushing(self):
        """开启推流（线程安全）。"""
        self._pushing = True
        log.info('DataPusher: 推流已开启')

    def stop_pushing(self):
        """暂停推流（不停止线程，不关闭 HID）。"""
        self._pushing = False
        log.info('DataPusher: 推流已暂停')

    def pause(self):
        """暂停整个推流线程（Flash 刷写前调用），等待当前帧写完后挂起。"""
        self._pause_event.set()

    def resume(self):
        """从 pause() 挂起状态恢复。"""
        self._pause_event.clear()

    def push_frame(self, jpeg_bytes: bytes):
        """投递一帧 JPEG 给推流线程（渲染线程调用，非阻塞）。

        队列满时丢弃最旧的帧（防止积压造成延迟飙升）。
        """
        if not self._pushing:
            return
        try:
            self._frame_queue.put_nowait(jpeg_bytes)
        except queue.Full:
            # 队列满：丢弃最旧帧，放入新帧
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._frame_queue.put_nowait(jpeg_bytes)
            except queue.Full:
                pass

    def stop(self):
        """请求停止线程（会等待当前帧写完后退出）。"""
        self._stop_event.set()
        # 投入哨兵值唤醒阻塞在 get() 的线程
        try:
            self._frame_queue.put_nowait(b'')
        except queue.Full:
            pass

    # ---- 线程主循环 --------------------------------------------------

    def run(self):
        """线程入口：自动连接 → 循环推流 → 断连时重试。"""
        log.info('DataPusher: 线程启动')
        while not self._stop_event.is_set():
            # 1. 尝试连接设备
            if not self._connect():
                # 连接失败，等待 _RECONNECT_INTERVAL 秒后重试
                self._stop_event.wait(timeout=_RECONNECT_INTERVAL)
                continue

            # 2. 推流主循环
            self._push_loop()

            # 3. 推流中断（设备丢失），等待重连
            if not self._stop_event.is_set():
                log.info('DataPusher: 设备丢失，%.1f 秒后重试…', _RECONNECT_INTERVAL)
                self.signals.device_lost.emit()
                self._stop_event.wait(timeout=_RECONNECT_INTERVAL)

        # 线程退出，关闭设备
        self._close_dev()
        log.info('DataPusher: 线程退出')

    # ---- 内部：连接 / 断开 -------------------------------------------

    def _connect(self) -> bool:
        """尝试打开 MI_01 数据口。成功返回 True，失败返回 False。"""
        iface = find_data_iface()
        if not iface:
            self.signals.status_updated.emit(0.0, 0.0, 0, False, '未找到 LG700 数据口')
            return False
        try:
            with self._dev_lock:
                if self._dev is not None:
                    try:
                        self._dev.close()
                    except Exception:
                        pass
                dev = create_data_transport(iface['path'])
                self._dev = dev
            log.info('DataPusher: 已连接 MI_01 数据口')
            self.signals.device_connected.emit()
            self.signals.status_updated.emit(0.0, 0.0, 0, True, '已连接，等待帧…')
            # 重置 FPS 计数器
            self._fps_frames = 0
            self._fps_t0 = time.monotonic()
            return True
        except OSError as e:
            log.warning('DataPusher: 连接失败：%s', e)
            self.signals.status_updated.emit(0.0, 0.0, 0, False, f'连接失败：{e}')
            return False

    def _close_dev(self):
        """关闭 HID 设备句柄。"""
        with self._dev_lock:
            if self._dev is not None:
                try:
                    self._dev.close()
                except Exception:
                    pass
                self._dev = None

    # ---- 内部：推流主循环 --------------------------------------------

    def _push_loop(self):
        """已连接状态下的推流循环，直到设备丢失或 stop() 被调用。"""
        while not self._stop_event.is_set():
            # 检查是否被 pause() 挂起（Flash 刷写时）
            if self._pause_event.is_set():
                time.sleep(0.05)
                continue

            # 从队列取帧（最多等待 0.5 秒，以便检查 stop_event）
            try:
                jpeg = self._frame_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            # 哨兵：空 bytes 表示退出
            if not jpeg:
                continue

            # 推流开关检查
            if not self._pushing:
                continue

            # 写入 HID
            try:
                ok = self._write_frame(jpeg)
            except OSError as e:
                log.warning('DataPusher: 写入失败：%s', e)
                self.signals.status_updated.emit(0.0, 0.0, 0, False, f'写入失败：{e}')
                return  # 回到外层重连逻辑

            if ok:
                self._update_stats(jpeg)

    def _write_frame(self, jpeg: bytes) -> bool:
        """将一帧 JPEG 分包写入 HID 设备（单写者互斥）。

        Returns:
            True  — 写入成功
            False — 推流被关闭（_pushing=False）

        Raises:
            OSError: HID 写入失败
        """
        with self._write_lock:
            with self._dev_lock:
                dev = self._dev
            if dev is None:
                raise OSError('HID 设备未连接')
            for pkt in build_packets(jpeg):
                written = dev.write(pkt)
                if written < 0:
                    raise OSError(f'hid.write 返回 {written}，设备可能已断开')
        return True

    # ---- 内部：FPS 统计 ----------------------------------------------

    def _update_stats(self, jpeg: bytes):
        """更新帧率、包数统计，每秒 emit 一次 status_updated 信号。"""
        self._fps_frames += 1
        now = time.monotonic()
        elapsed = now - self._fps_t0
        pkt = (len(jpeg) + PAYLOAD - 1) // PAYLOAD
        kb = len(jpeg) / 1024
        if elapsed >= 1.0:
            fps = self._fps_frames / elapsed
            self.signals.status_updated.emit(
                round(fps, 1),
                round(kb, 1),
                pkt,
                True,
                '运行中',
            )
            self._fps_frames = 0
            self._fps_t0 = now
            self._last_kb = kb
            self._last_pkt = pkt
