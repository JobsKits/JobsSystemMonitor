"""只读定位 Windows 主任务栏；不注入或更改 Explorer。Created by Jobs."""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import wintypes

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication

Rect = tuple[int, int, int, int]


def fit_bar(
    taskbar: Rect, notify: Rect | None, width: int, height: int, scale: float = 1.0
) -> Rect | None:
    """将逻辑尺寸放进物理任务栏，返回 Qt 逻辑坐标 (x, y, width, height)。"""
    if width <= 0 or height <= 0 or scale <= 0:
        return None
    left, top, right, bottom = taskbar
    available_width, available_height = right - left, bottom - top
    physical_width, physical_height = round(width * scale), round(height * scale)
    margin = max(2, round(8 * scale))
    if available_width <= 0 or available_height <= 0:
        return None
    notify_valid = bool(
        notify and notify[0] < notify[2] and notify[1] < notify[3]
        and notify[0] < right and notify[2] > left
        and notify[1] < bottom and notify[3] > top
    )
    # 竖向任务栏只有在调用者的控件确实放得下时才使用；否则留给浮窗回退。
    horizontal = available_width >= available_height
    if horizontal:
        if physical_height > available_height - 2:
            return None
        end = right - margin
        if notify_valid:
            end = min(end, notify[0] - margin)
        else:
            # 不依赖未公开的通知区子窗口结构；找不到时为时钟/系统图标预留空间。
            end -= round(280 * scale)
        x = end - physical_width
        y = top + (available_height - physical_height) // 2
        if x < left + margin:
            return None
    else:
        if physical_width > available_width - 2:
            return None
        end = bottom - margin
        if notify_valid:
            end = min(end, notify[1] - margin)
        else:
            end -= round(160 * scale)
        x = left + (available_width - physical_width) // 2
        y = end - physical_height
        if y < top + margin:
            return None
    return round(x / scale), round(y / scale), width, height


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
    ]


class TaskbarPlacement:
    """Explorer 重启、DPI 变化和自动隐藏在每次查询时重新检测。"""

    def __init__(self) -> None:
        self._user32 = None
        self._set_thread_dpi = None
        self.auto_hidden = False
        if sys.platform != "win32":
            return
        try:
            api = ctypes.WinDLL("user32", use_last_error=True)
            api.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            api.FindWindowW.restype = wintypes.HWND
            api.FindWindowExW.argtypes = [
                wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
            ]
            api.FindWindowExW.restype = wintypes.HWND
            api.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            api.GetWindowRect.restype = wintypes.BOOL
            api.IsWindowVisible.argtypes = [wintypes.HWND]
            api.IsWindowVisible.restype = wintypes.BOOL
            api.IsIconic.argtypes = [wintypes.HWND]
            api.IsIconic.restype = wintypes.BOOL
            api.GetForegroundWindow.argtypes = []
            api.GetForegroundWindow.restype = wintypes.HWND
            api.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            api.GetClassNameW.restype = ctypes.c_int
            api.GetWindowThreadProcessId.argtypes = [
                wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
            ]
            api.GetWindowThreadProcessId.restype = wintypes.DWORD
            api.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            api.MonitorFromWindow.restype = wintypes.HANDLE
            api.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
            api.GetMonitorInfoW.restype = wintypes.BOOL
            try:
                api.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
                api.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
                self._set_thread_dpi = api.SetThreadDpiAwarenessContext
            except AttributeError:
                pass
            self._user32 = api
        except (OSError, AttributeError):
            logging.exception("任务栏定位初始化失败，将使用浮动监控条")

    @property
    def is_available(self) -> bool:
        return bool(self._user32 and self._user32.FindWindowW("Shell_TrayWnd", None))

    def _rect(self, window: int) -> Rect | None:
        value = wintypes.RECT()
        if not self._user32.GetWindowRect(window, ctypes.byref(value)):
            return None
        return value.left, value.top, value.right, value.bottom

    def _fullscreen(self, taskbar: int, monitor: Rect) -> bool:
        window = self._user32.GetForegroundWindow()
        if not window or window == taskbar or self._user32.IsIconic(window):
            return False
        process = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(window, ctypes.byref(process))
        if process.value == os.getpid():
            return False
        class_name = ctypes.create_unicode_buffer(128)
        self._user32.GetClassNameW(window, class_name, len(class_name))
        if class_name.value in {"Progman", "WorkerW", "Shell_TrayWnd"}:
            return False
        bounds = self._rect(window)
        if bounds is None:
            return False
        return (
            bounds[0] <= monitor[0] and bounds[1] <= monitor[1]
            and bounds[2] >= monitor[2] and bounds[3] >= monitor[3]
        )

    def geometry(self, width: int, height: int) -> QRect | None:
        """返回主任务栏内的矩形；隐藏、全屏或空间不足时返回 None。"""
        self.auto_hidden = False
        if not self.is_available:
            return None
        previous_context = None
        if self._set_thread_dpi:
            # Qt 默认 per-monitor aware；临时统一原生查询，避免环境变量引入 DPI 虚拟化。
            previous_context = self._set_thread_dpi(ctypes.c_void_p(-4))
        try:
            return self._geometry(width, height)
        finally:
            if previous_context and self._set_thread_dpi:
                self._set_thread_dpi(previous_context)

    def _geometry(self, width: int, height: int) -> QRect | None:
        taskbar = self._user32.FindWindowW("Shell_TrayWnd", None)
        if not taskbar or not self._user32.IsWindowVisible(taskbar):
            self.auto_hidden = bool(taskbar)
            return None
        bounds = self._rect(taskbar)
        monitor_handle = self._user32.MonitorFromWindow(taskbar, 2)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if bounds is None or not self._user32.GetMonitorInfoW(monitor_handle, ctypes.byref(info)):
            return None
        screen_bounds = (
            info.rcMonitor.left, info.rcMonitor.top, info.rcMonitor.right, info.rcMonitor.bottom,
        )
        if self._fullscreen(taskbar, screen_bounds):
            self.auto_hidden = True
            return None
        visible = (
            max(bounds[0], screen_bounds[0]), max(bounds[1], screen_bounds[1]),
            min(bounds[2], screen_bounds[2]), min(bounds[3], screen_bounds[3]),
        )
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return None
        scale = screen.devicePixelRatio()
        # 自动隐藏后的任务栏只剩几像素边缘，不能把条压在该边缘上。
        horizontal = bounds[2] - bounds[0] >= bounds[3] - bounds[1]
        full_thickness = bounds[3] - bounds[1] if horizontal else bounds[2] - bounds[0]
        visible_thickness = visible[3] - visible[1] if horizontal else visible[2] - visible[0]
        if visible_thickness < round(12 * scale) or visible_thickness + 1 < full_thickness:
            self.auto_hidden = True
            return None
        notify = self._user32.FindWindowExW(taskbar, None, "TrayNotifyWnd", None)
        notify_rect = self._rect(notify) if notify else None
        result = fit_bar(visible, notify_rect, width, height, scale)
        return QRect(*result) if result else None
