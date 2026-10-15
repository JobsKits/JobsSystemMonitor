"""通过系统 Objective-C runtime 创建原生可变宽度菜单栏项。Created by Jobs.

所有调用都在 Qt 的主线程执行；函数指针声明完整签名，兼容 arm64 / x86_64。
"""

from __future__ import annotations

import ctypes as C
import logging
import os
import sys
from collections.abc import Callable

from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImage


class NSSize(C.Structure):
    _fields_ = [("width", C.c_double), ("height", C.c_double)]


class MacStatusItem:
    """系统持有 status item；Python 持有 action 回调，关闭时解除目标。"""

    def __init__(self, clicked: Callable[[], None]) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("原生菜单栏仅适用于 macOS")
        self._appkit = C.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
        self._objc = C.CDLL("/usr/lib/libobjc.A.dylib")
        self._objc.objc_getClass.argtypes = [C.c_char_p]
        self._objc.objc_getClass.restype = C.c_void_p
        self._objc.sel_registerName.argtypes = [C.c_char_p]
        self._objc.sel_registerName.restype = C.c_void_p
        self._objc.objc_allocateClassPair.argtypes = [C.c_void_p, C.c_char_p, C.c_size_t]
        self._objc.objc_allocateClassPair.restype = C.c_void_p
        self._objc.class_addMethod.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_char_p]
        self._objc.class_addMethod.restype = C.c_bool
        self._objc.objc_registerClassPair.argtypes = [C.c_void_p]
        self._objc.objc_registerClassPair.restype = None
        self._functions: dict[tuple, object] = {}
        self._clicked = clicked

        callback_type = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_void_p)
        self._callback = callback_type(self._on_click)
        target_class = self._objc.objc_allocateClassPair(
            self._class("NSObject"), f"JobsMonitorAction_{os.getpid()}_{id(self)}".encode(), 0
        )
        if not target_class:
            raise RuntimeError("无法创建菜单栏 action 类")
        action = self._selector("showMonitor:")
        if not self._objc.class_addMethod(target_class, action, self._callback, b"v@:@"):
            raise RuntimeError("无法注册菜单栏 action")
        self._objc.objc_registerClassPair(target_class)
        self._target = self._send(target_class, "new")
        self._bar = self._send(self._class("NSStatusBar"), "systemStatusBar")
        # statusItemWithLength: 返回 autorelease 对象，显式 retain 到退出。
        self._item = self._send(self._bar, "statusItemWithLength:", -1.0, types=(C.c_double,))
        if not self._item:
            raise RuntimeError("无法创建系统菜单栏项")
        self._send(self._item, "retain")
        self._button = self._send(self._item, "button")
        self._send(self._button, "setTarget:", self._target)
        self._send(self._button, "setAction:", action)

    def _class(self, name: str) -> int:
        return self._objc.objc_getClass(name.encode())

    def _selector(self, name: str) -> int:
        return self._objc.sel_registerName(name.encode())

    def _send(self, receiver, selector, *args, types=None, result=C.c_void_p):
        """为每种 ABI 签名单独创建 objc_msgSend 包装，不修改共享函数的签名。"""
        types = types or (C.c_void_p,) * len(args)
        key = (result, *types)
        if key not in self._functions:
            self._functions[key] = C.CFUNCTYPE(result, C.c_void_p, C.c_void_p, *types)(
                ("objc_msgSend", self._objc)
            )
        return self._functions[key](receiver, self._selector(selector), *args)

    def _on_click(self, _target, _selector, _sender) -> None:
        try:
            self._clicked()
        except Exception:
            logging.exception("菜单栏点击失败")

    def update(self, image: QImage, tooltip: str) -> None:
        """PNG 保留 Retina 分辨率，模板图由 macOS 按菜单栏背景自动着色。"""
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError("无法绘制菜单栏图像")
        raw = bytes(data)
        pool = self._send(self._class("NSAutoreleasePool"), "new")
        try:
            native_data = self._send(
                self._class("NSData"), "dataWithBytes:length:", raw, len(raw),
                types=(C.c_char_p, C.c_size_t),
            )
            native_image = self._send(self._class("NSImage"), "alloc")
            native_image = self._send(native_image, "initWithData:", native_data)
            if not native_image:
                raise RuntimeError("NSImage 无法解码菜单栏图像")
            ratio = image.devicePixelRatio()
            self._send(
                native_image, "setSize:", NSSize(image.width() / ratio, image.height() / ratio),
                types=(NSSize,), result=None,
            )
            self._send(native_image, "setTemplate:", True, types=(C.c_bool,), result=None)
            self._send(self._item, "setLength:", image.width() / ratio + 8,
                       types=(C.c_double,), result=None)
            self._send(self._button, "setImage:", native_image, result=None)
            self._send(native_image, "release", result=None)
            text = self._send(self._class("NSString"), "stringWithUTF8String:",
                              tooltip.encode(), types=(C.c_char_p,))
            self._send(self._button, "setToolTip:", text, result=None)
        finally:
            self._send(pool, "drain", result=None)

    def close(self) -> None:
        if self._item:
            self._send(self._button, "setTarget:", None, result=None)
            self._send(self._bar, "removeStatusItem:", self._item, result=None)
            self._send(self._item, "release", result=None)
            self._send(self._target, "release", result=None)
            self._item = None
