# -*- coding: utf-8 -*-
"""device.py — USB 设备枚举、连接守护、单写者互斥锁。

功能：
- find_command_iface()     枚举 MI_00 命令口（interface_number=0, usage_page=0xFF06, usage=0x0001）
- find_data_iface()        枚举 MI_01 数据口（interface_number=1, usage_page=0xFF06, usage=0x0002）
- create_data_transport()  创建数据通道传输句柄（支持 hidapi 或 Windows 原生零拷贝 WriteFile）
- class DeviceLock         命名 Mutex（kernel32），防双开抢占 USB
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import winreg

try:
    import hid
    _HAS_HID = True
except Exception:
    _HAS_HID = False

log = logging.getLogger('tcomas.device')

# ---------------------------------------------------------------- 常量
VID: int = 0x1A2C   # TCOMAS 厂商 ID
PID: int = 0x151C   # LG700 产品 ID

# 命名互斥锁名称，防止多实例同时抢占 USB 总线
_MUTEX_NAME = 'Local\\TCOMAS_LG700_DataStream_IO'
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ('Internal', ctypes.c_size_t),
        ('InternalHigh', ctypes.c_size_t),
        ('Offset', ctypes.wintypes.DWORD),
        ('OffsetHigh', ctypes.wintypes.DWORD),
        ('hEvent', ctypes.wintypes.HANDLE),
    ]


_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_kernel32.CreateFileW.argtypes = [
    ctypes.wintypes.LPCWSTR,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.DWORD,
    ctypes.c_void_p,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.HANDLE,
]
_kernel32.CreateFileW.restype = ctypes.wintypes.HANDLE
_kernel32.CreateEventW.argtypes = [
    ctypes.c_void_p,
    ctypes.wintypes.BOOL,
    ctypes.wintypes.BOOL,
    ctypes.wintypes.LPCWSTR,
]
_kernel32.CreateEventW.restype = ctypes.wintypes.HANDLE
_kernel32.ResetEvent.argtypes = [ctypes.wintypes.HANDLE]
_kernel32.ResetEvent.restype = ctypes.wintypes.BOOL
_kernel32.WriteFile.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.wintypes.DWORD,
    ctypes.POINTER(ctypes.wintypes.DWORD),
    ctypes.POINTER(OVERLAPPED),
]
_kernel32.WriteFile.restype = ctypes.wintypes.BOOL
_kernel32.WaitForSingleObject.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.DWORD,
]
_kernel32.WaitForSingleObject.restype = ctypes.wintypes.DWORD
_kernel32.CancelIoEx.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.POINTER(OVERLAPPED),
]
_kernel32.CancelIoEx.restype = ctypes.wintypes.BOOL
_kernel32.GetOverlappedResult.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.POINTER(OVERLAPPED),
    ctypes.POINTER(ctypes.wintypes.DWORD),
    ctypes.wintypes.BOOL,
]
_kernel32.GetOverlappedResult.restype = ctypes.wintypes.BOOL
_kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
_kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
_kernel32.CreateMutexW.argtypes = [
    ctypes.c_void_p,
    ctypes.wintypes.BOOL,
    ctypes.wintypes.LPCWSTR,
]
_kernel32.CreateMutexW.restype = ctypes.wintypes.HANDLE
_kernel32.ReleaseMutex.argtypes = [ctypes.wintypes.HANDLE]
_kernel32.ReleaseMutex.restype = ctypes.wintypes.BOOL


# ---------------------------------------------------------------- 注册表发现 fallback

def _find_hid_registry() -> dict[str, str]:
    """通过 Windows 注册表扫描当前连接的 LG700 HID 设备路径。"""
    res: dict[str, str] = {}
    base_path = r'SYSTEM\CurrentControlSet\Enum\HID'
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base_path) as h_base:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(h_base, i)
                    i += 1
                    if 'VID_1A2C' in sub.upper() and 'PID_151C' in sub.upper():
                        with winreg.OpenKey(h_base, sub) as h_sub:
                            j = 0
                            while True:
                                try:
                                    inst = winreg.EnumKey(h_sub, j)
                                    j += 1
                                    path = f'\\\\?\\HID#{sub}#{inst}#{{4D1E55B2-F16F-11CF-88CB-001111000030}}'
                                    if 'MI_00' in sub.upper():
                                        res['MI_00'] = path
                                    elif 'MI_01' in sub.upper():
                                        res['MI_01'] = path
                                except OSError:
                                    break
                except OSError:
                    break
    except Exception as e:
        log.warning('Registry search error: %s', e)
    return res


# ---------------------------------------------------------------- 接口枚举

def find_command_iface() -> dict | None:
    """枚举 MI_00 命令口。"""
    if _HAS_HID:
        try:
            for d in hid.enumerate(VID, PID):
                if (d.get('interface_number') == 0
                        and d.get('usage_page') == 0xFF06
                        and d.get('usage', 1) == 0x0001):
                    return d
        except Exception:
            pass

    reg = _find_hid_registry()
    if 'MI_00' in reg:
        return {'path': reg['MI_00'], 'interface_number': 0, 'usage_page': 0xFF06, 'usage': 1}

    log.warning('find_command_iface: 未找到 MI_00 命令口 (VID=%04X PID=%04X)', VID, PID)
    return None


def find_data_iface() -> dict | None:
    """枚举 MI_01 数据口。"""
    if _HAS_HID:
        try:
            for d in hid.enumerate(VID, PID):
                if (d.get('interface_number') == 1
                        and d.get('usage_page') == 0xFF06):
                    usage = d.get('usage')
                    if usage is None or usage == 0x0002:
                        return d
        except Exception:
            pass

    reg = _find_hid_registry()
    if 'MI_01' in reg:
        return {'path': reg['MI_01'], 'interface_number': 1, 'usage_page': 0xFF06, 'usage': 2}

    log.warning('find_data_iface: 未找到 MI_01 数据口 (VID=%04X PID=%04X)', VID, PID)
    return None


# ---------------------------------------------------------------- 原生数据通道传输器

class WindowsDataHID:
    """Windows 原生 HID 数据通道传输器（基于预分配缓冲区的零分配 OVERLAPPED WriteFile）。"""

    def __init__(self):
        self.handle = None
        self.write_event = None
        self._ov = OVERLAPPED()
        self._buf = ctypes.create_string_buffer(1025)
        self._written = ctypes.wintypes.DWORD()

    def open_path(self, path: str | bytes):
        if isinstance(path, bytes):
            path = path.decode('utf8', errors='replace')
        # 0xC0000000 = GENERIC_READ | GENERIC_WRITE, 3 = FILE_SHARE_READ | FILE_SHARE_WRITE,
        # 3 = OPEN_EXISTING, 0x40000000 = FILE_FLAG_OVERLAPPED
        self.handle = _kernel32.CreateFileW(path, 0xC0000000, 3, None, 3, 0x40000000, None)
        if self.handle == _INVALID_HANDLE_VALUE or not self.handle:
            self.handle = None
            raise ctypes.WinError(ctypes.get_last_error())
        self.write_event = _kernel32.CreateEventW(None, True, False, None)
        if not self.write_event:
            err = ctypes.get_last_error()
            _kernel32.CloseHandle(self.handle)
            self.handle = None
            raise ctypes.WinError(err)

    def write(self, data: bytes) -> int:
        if not self.handle:
            raise OSError('Handle closed')
        n = len(data)
        _kernel32.ResetEvent(self.write_event)

        ov = self._ov
        ov.Internal = 0
        ov.InternalHigh = 0
        ov.Offset = 0
        ov.OffsetHigh = 0
        ov.hEvent = self.write_event

        if n <= 1025:
            ctypes.memmove(self._buf, data, n)
            buf_ptr = self._buf
        else:
            buf_ptr = ctypes.create_string_buffer(data, n)

        written = self._written
        written.value = 0
        success = _kernel32.WriteFile(self.handle, buf_ptr, n, ctypes.byref(written), ctypes.byref(ov))
        if not success:
            err = ctypes.get_last_error()
            if err == 997:  # ERROR_IO_PENDING
                wait = _kernel32.WaitForSingleObject(self.write_event, 2000)
                if wait != 0:
                    _kernel32.CancelIoEx(self.handle, ctypes.byref(ov))
                    _kernel32.GetOverlappedResult(self.handle, ctypes.byref(ov), ctypes.byref(written), True)
                    raise TimeoutError('HID write timeout')
                if not _kernel32.GetOverlappedResult(self.handle, ctypes.byref(ov), ctypes.byref(written), False):
                    raise ctypes.WinError(ctypes.get_last_error())
            else:
                raise ctypes.WinError(err)
        return written.value

    def close(self):
        if self.handle:
            try:
                _kernel32.CancelIoEx(self.handle, None)
                _kernel32.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None
        if self.write_event:
            try:
                _kernel32.CloseHandle(self.write_event)
            except Exception:
                pass
            self.write_event = None


def create_data_transport(path: str | bytes):
    """创建并打开数据口传输句柄。"""
    if _HAS_HID:
        try:
            d = hid.device()
            d.open_path(path if isinstance(path, bytes) else path.encode('utf8'))
            return d
        except Exception:
            pass
    trans = WindowsDataHID()
    trans.open_path(path)
    return trans


# ---------------------------------------------------------------- 命名互斥锁

class DeviceLock:
    """Win32 命名 Mutex，确保同一时间只有一个进程可以写 USB 数据口。"""

    def __init__(self, name: str = _MUTEX_NAME, timeout_ms: int = 0):
        self._name = name
        self._timeout_ms = timeout_ms
        self._handle: ctypes.wintypes.HANDLE | None = None
        self._owned: bool = False

    def acquire(self) -> bool:
        if self._handle and self._owned:
            return True
        handle = _kernel32.CreateMutexW(None, False, self._name)
        if not handle:
            return False
        ret = _kernel32.WaitForSingleObject(handle, self._timeout_ms)
        if ret not in (0, 0x00000080):  # WAIT_OBJECT_0 or WAIT_ABANDONED
            _kernel32.CloseHandle(handle)
            self._handle = None
            self._owned = False
            return False
        self._handle = handle
        self._owned = True
        return True

    def release(self):
        if self._handle:
            try:
                if self._owned:
                    _kernel32.ReleaseMutex(self._handle)
                _kernel32.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None
            self._owned = False

    def __enter__(self):
        if not self.acquire():
            raise BlockingIOError(f'无法获取设备互斥锁 {self._name}')
        return self

    def __exit__(self, *_):
        self.release()
