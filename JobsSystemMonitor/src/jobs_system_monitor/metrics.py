"""Read-only system sampling. A Collector belongs to one sampling thread."""

from __future__ import annotations

import ctypes
import ipaddress
import math
import plistlib
import re
import socket
import subprocess
import sys
import time
from xml.parsers.expat import ExpatError
from dataclasses import dataclass
from typing import Any, Iterable

import psutil


@dataclass(frozen=True)
class Snapshot:
    cpu_percent: float | None = None
    memory_percent: float | None = None
    memory_used: int = 0
    memory_total: int = 0
    upload_bps: float | None = None
    download_bps: float | None = None
    gpu_percent: float | None = None
    gpu_name: str = "GPU"
    gpu_detail: str = "等待采样"
    network_name: str = "自动"
    sampled_at: float = 0.0
    error: str = ""


def format_rate(value: float | None) -> str:
    if value is None or not math.isfinite(value) or value < 0:
        return "--"
    for unit in ("B/s", "K/s", "M/s", "G/s", "T/s"):
        if value < 1024 or unit == "T/s":
            return f"{value:.0f} {unit}" if unit == "B/s" else f"{value:.1f} {unit}"
        value /= 1024
    return "--"


def format_percent(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "--"
    return f"{min(100.0, max(0.0, value)):.0f}%"


def _percentage(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and 0 <= result <= 100 else None


def _is_loopback(name: str, stats: Any, addresses: Iterable[Any]) -> bool:
    if name.casefold() in {"lo", "lo0"} or "loopback" in name.casefold():
        return True
    if "loopback" in str(getattr(stats, "flags", "")).split(","):
        return True
    ips = []
    for entry in addresses:
        if entry.family in {socket.AF_INET, socket.AF_INET6}:
            try:
                ips.append(ipaddress.ip_address(entry.address.split("%")[0]))
            except ValueError:
                continue
    return bool(ips) and all(address.is_loopback for address in ips)


def _is_virtual(name: str) -> bool:
    # Name-based filtering is deliberately transparent; explicit selection overrides it.
    lowered = name.casefold()
    prefixes = (
        "utun", "tun", "tap", "ppp", "ipsec", "gif", "stf", "awdl", "llw",
        "bridge", "bond", "docker", "veth", "virbr", "vmnet", "vboxnet", "zt",
        "wg", "tailscale", "hamachi", "anpi", "nan", "vethernet",
    )
    keywords = ("virtual", "vpn", "vmware", "virtualbox", "hyper-v", "bluetooth", "loopback")
    return lowered.startswith(prefixes) or bool(re.fullmatch(r"ap\d+", lowered)) or any(word in lowered for word in keywords)


def _has_ip(addresses: Iterable[Any]) -> bool:
    for entry in addresses:
        if entry.family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        try:
            address = ipaddress.ip_address(entry.address.split("%")[0])
        except ValueError:
            continue
        if not address.is_loopback and not address.is_unspecified:
            return True
    return False


def available_interfaces() -> list[str]:
    """Include disconnected/virtual adapters for manual selection, excluding loopback."""
    try:
        stats = psutil.net_if_stats()
        addresses = psutil.net_if_addrs()
        return sorted(
            (name for name, state in stats.items() if not _is_loopback(name, state, addresses.get(name, []))),
            key=str.casefold,
        )
    except (OSError, psutil.Error):
        return []


@dataclass(frozen=True)
class _GPUReading:
    percent: float | None = None
    name: str = "GPU"
    detail: str = "此系统暂不支持 GPU 利用率"


def _parse_macos_gpu(data: bytes) -> _GPUReading:
    """Use only a driver's explicit percentage, never infer usage from memory/power."""
    root = plistlib.loads(data)
    readings: list[tuple[float, str]] = []
    stack = list(root) if isinstance(root, list) else [root]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        statistics = node.get("PerformanceStatistics")
        if isinstance(statistics, dict):
            value = _percentage(statistics.get("Device Utilization %"))
            if value is not None:
                name = node.get("model") or node.get("IORegistryEntryName") or "GPU"
                if isinstance(name, bytes):
                    name = name.rstrip(b"\0").decode("utf-8", errors="replace")
                readings.append((value, str(name)))
        children = node.get("IORegistryEntryChildren", [])
        if isinstance(children, list):
            stack.extend(children)
    if not readings:
        return _GPUReading(detail="当前 macOS / GPU 驱动未公开利用率；不需要管理员权限")
    value, name = max(readings, key=lambda reading: reading[0])
    return _GPUReading(value, name, "IORegistry 驱动利用率；多 GPU 取最忙设备")


_ENGINE_INSTANCE = re.compile(
    r"(?:^|_)luid_(?P<luid>0x[0-9a-f]+_0x[0-9a-f]+)_phys_(?P<physical>\d+)_eng_(?P<engine>\d+)(?:_|$)",
    re.IGNORECASE,
)


def _aggregate_windows_gpu(items: Iterable[tuple[str, float]]) -> _GPUReading:
    """Sum processes on one engine, then take the busiest engine/device like Task Manager."""
    engines: dict[tuple[str, str, str], float] = {}
    seen: set[str] = set()
    for name, value in items:
        match = _ENGINE_INSTANCE.search(name)
        if not match or name in seen or not math.isfinite(value) or value < 0:
            continue
        seen.add(name)
        key = (match["luid"].lower(), match["physical"], match["engine"])
        engines[key] = engines.get(key, 0.0) + value
    if not engines:
        return _GPUReading(detail="Windows GPU Engine 尚无有效数据，等待驱动或下一次采样")
    busiest, value = max(engines.items(), key=lambda pair: pair[1])
    return _GPUReading(
        min(100.0, value),
        f"GPU {busiest[1]}",
        "Windows GPU Engine；逐引擎合计进程后取最忙引擎 / 设备（WDDM 2.x）",
    )


class _CounterValueUnion(ctypes.Union):
    _fields_ = [
        ("longValue", ctypes.c_int32),
        ("doubleValue", ctypes.c_double),
        ("largeValue", ctypes.c_int64),
        ("AnsiStringValue", ctypes.c_char_p),
        ("WideStringValue", ctypes.c_wchar_p),
    ]


class _CounterValue(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("CStatus", ctypes.c_uint32), ("value", _CounterValueUnion)]


class _CounterItem(ctypes.Structure):
    _fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", _CounterValue)]


class _WindowsGPU:
    """Keep one native PDH query open; no PowerShell or external process per sample."""

    _MORE_DATA = 0x800007D2
    _NO_DATA = 0x800007D5
    _NO_INSTANCE = 0x800007D1
    _FORMAT = 0x00000200 | 0x00008000  # DOUBLE | NOCAP100 (sum per-process engines first).

    def __init__(self) -> None:
        self._pdh = ctypes.WinDLL("pdh.dll")
        handle = ctypes.c_void_p
        dword = ctypes.c_uint32
        self._pdh.PdhOpenQueryW.argtypes = [ctypes.c_wchar_p, ctypes.c_size_t, ctypes.POINTER(handle)]
        self._pdh.PdhAddEnglishCounterW.argtypes = [handle, ctypes.c_wchar_p, ctypes.c_size_t, ctypes.POINTER(handle)]
        self._pdh.PdhCollectQueryData.argtypes = [handle]
        self._pdh.PdhGetFormattedCounterArrayW.argtypes = [
            handle, dword, ctypes.POINTER(dword), ctypes.POINTER(dword), ctypes.c_void_p,
        ]
        self._pdh.PdhCloseQuery.argtypes = [handle]
        for name in ("PdhOpenQueryW", "PdhAddEnglishCounterW", "PdhCollectQueryData", "PdhGetFormattedCounterArrayW", "PdhCloseQuery"):
            getattr(self._pdh, name).restype = dword
        self._query = handle()
        self._counter = handle()
        try:
            self._check(self._pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query)), "创建 GPU 查询")
            self._check(
                self._pdh.PdhAddEnglishCounterW(
                    self._query, r"\GPU Engine(*)\Utilization Percentage", 0, ctypes.byref(self._counter)
                ),
                "GPU Engine 不可用",
            )
            self._check(self._pdh.PdhCollectQueryData(self._query), "GPU 首次采样")
        except Exception:
            self.close()
            raise

    @staticmethod
    def _check(status: int, action: str) -> None:
        if status:
            raise OSError(f"{action}：PDH 0x{status:08X}")

    def sample(self) -> _GPUReading:
        status = self._pdh.PdhCollectQueryData(self._query)
        if status in {self._NO_DATA, self._NO_INSTANCE}:
            return _GPUReading(detail="Windows GPU Engine 暂无数据，等待驱动或下一次采样")
        self._check(status, "GPU 采样")
        size = ctypes.c_uint32(0)
        count = ctypes.c_uint32(0)
        status = self._pdh.PdhGetFormattedCounterArrayW(
            self._counter, self._FORMAT, ctypes.byref(size), ctypes.byref(count), None
        )
        if status in {self._NO_DATA, self._NO_INSTANCE} or (not status and not count.value):
            return _GPUReading(detail="Windows GPU Engine 等待有效计数器")
        if status != self._MORE_DATA:
            self._check(status, "读取 GPU 计数器大小")
        # The list of process instances can grow between the size and data requests.
        for _ in range(3):
            if not 0 < size.value <= 32 * 1024 * 1024:
                raise OSError("GPU 计数器返回无效缓冲区大小")
            allocated_size = size.value
            buffer = ctypes.create_string_buffer(allocated_size)
            status = self._pdh.PdhGetFormattedCounterArrayW(
                self._counter, self._FORMAT, ctypes.byref(size), ctypes.byref(count), buffer
            )
            if status == self._MORE_DATA:
                continue
            if status in {self._NO_DATA, self._NO_INSTANCE}:
                return _GPUReading(detail="Windows GPU Engine 暂无有效计数器")
            self._check(status, "读取 GPU 计数器")
            if count.value * ctypes.sizeof(_CounterItem) > allocated_size:
                raise OSError("GPU 计数器条目数量超出缓冲区")
            array = ctypes.cast(buffer, ctypes.POINTER(_CounterItem))
            values = [
                (array[index].szName or "", array[index].FmtValue.doubleValue)
                for index in range(count.value)
                if array[index].FmtValue.CStatus in {0, 1}
            ]
            return _aggregate_windows_gpu(values)
        raise OSError("GPU 计数器实例变化过快，稍后重试")

    def close(self) -> None:
        if self._query.value:
            self._pdh.PdhCloseQuery(self._query)
            self._query = ctypes.c_void_p()


class _GPUProbe:
    def __init__(self) -> None:
        self._native: _WindowsGPU | None = None
        self._next_probe = 0.0
        self._last = _GPUReading()

    def sample(self, now: float) -> _GPUReading:
        if now < self._next_probe:
            return self._last
        try:
            if sys.platform == "darwin":
                result = subprocess.run(
                    ["/usr/sbin/ioreg", "-a", "-r", "-c", "IOAccelerator", "-d", "1"],
                    capture_output=True, check=True, timeout=1.5,
                )
                self._last = _parse_macos_gpu(result.stdout)
                self._next_probe = now + (2.0 if self._last.percent is not None else 60.0)
            elif sys.platform == "win32":
                if self._native is None:
                    self._native = _WindowsGPU()
                    self._last = _GPUReading(detail="Windows GPU Engine 正在预热，等待下一次采样")
                else:
                    self._last = self._native.sample()
                self._next_probe = now + 1.0
            else:
                self._last = _GPUReading(detail="当前平台未实现 GPU 采集；支持 macOS 与 Windows")
                self._next_probe = now + 60.0
        except (OSError, ValueError, TypeError, ExpatError, plistlib.InvalidFileException, subprocess.SubprocessError) as exc:
            self.close()
            self._last = _GPUReading(detail=f"GPU 不可用，60 秒后重试：{exc}")
            self._next_probe = now + 60.0
        return self._last

    def close(self) -> None:
        if self._native is not None:
            self._native.close()
            self._native = None


class Collector:
    """Call sample/close on the same worker thread; missing data remains None."""

    def __init__(self, interface: str | None = None) -> None:
        self.interface = interface or None
        self._previous: dict[str, tuple[float, int, int]] = {}
        self._cpu_primed = False
        self._gpu = _GPUProbe()

    def _network(self, now: float) -> tuple[float | None, float | None, str]:
        counters = psutil.net_io_counters(pernic=True, nowrap=False)
        stats = psutil.net_if_stats()
        addresses = psutil.net_if_addrs()
        selected = {}
        for name, counter in counters.items():
            state = stats.get(name)
            if state is None or not state.isup or _is_loopback(name, state, addresses.get(name, [])):
                continue
            if self.interface:
                if name != self.interface:
                    continue
            elif _is_virtual(name) or not _has_ip(addresses.get(name, [])):
                continue
            selected[name] = counter
        previous = self._previous
        self._previous = {
            name: (now, counter.bytes_sent, counter.bytes_recv) for name, counter in selected.items()
        }
        label = self.interface or (" + ".join(sorted(selected)) if selected else "无活动网卡")
        if not selected:
            return None, None, label
        upload = download = 0.0
        # A newly attached/reset NIC must warm up; do not under-report the aggregate.
        valid = True
        for name, counter in selected.items():
            old = previous.get(name)
            if old is None or now <= old[0] or counter.bytes_sent < old[1] or counter.bytes_recv < old[2]:
                valid = False
                continue
            elapsed = now - old[0]
            upload += (counter.bytes_sent - old[1]) / elapsed
            download += (counter.bytes_recv - old[2]) / elapsed
        return (upload, download, label) if valid else (None, None, label)

    def sample(self) -> Snapshot:
        now = time.monotonic()
        errors = []
        cpu = memory = None
        used = total = 0
        try:
            value = psutil.cpu_percent(interval=None)
            if self._cpu_primed:
                cpu = _percentage(value)
            self._cpu_primed = True
        except (OSError, psutil.Error) as exc:
            self._cpu_primed = False
            errors.append(f"CPU：{exc}")
        try:
            info = psutil.virtual_memory()
            memory = _percentage(info.percent)
            total = int(info.total)
            # Available-based usage agrees with psutil.percent across cached-memory policies.
            used = max(0, total - int(info.available))
        except (OSError, psutil.Error) as exc:
            errors.append(f"内存：{exc}")
        try:
            upload, download, network = self._network(now)
        except (OSError, psutil.Error) as exc:
            self._previous.clear()
            upload = download = None
            network = self.interface or "自动"
            errors.append(f"网络：{exc}")
        gpu = self._gpu.sample(now)
        return Snapshot(
            cpu_percent=cpu, memory_percent=memory, memory_used=used, memory_total=total,
            upload_bps=upload, download_bps=download,
            gpu_percent=gpu.percent, gpu_name=gpu.name, gpu_detail=gpu.detail,
            network_name=network, sampled_at=time.time(), error="；".join(errors),
        )

    def close(self) -> None:
        self._gpu.close()
        self._previous.clear()
