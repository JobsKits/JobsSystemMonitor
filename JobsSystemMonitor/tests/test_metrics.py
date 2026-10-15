"""Counter discontinuities and platform GPU aggregation, with no live hardware required."""

from __future__ import annotations

import ctypes
import plistlib
import socket
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jobs_system_monitor import metrics


def counter(sent: int, received: int) -> SimpleNamespace:
    return SimpleNamespace(bytes_sent=sent, bytes_recv=received)


def state(up: bool = True, flags: str = "up") -> SimpleNamespace:
    return SimpleNamespace(isup=up, flags=flags)


def instance(pid: int, engine: int = 0, physical: int = 0, luid: str = "0x00000000_0x0000c001") -> str:
    return f"pid_{pid}_luid_{luid}_phys_{physical}_eng_{engine}_engtype_3D"


class NetworkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stats = {"en0": state(), "en1": state(), "utun0": state(), "bridge0": state(), "lo0": state(flags="up,loopback")}
        self.counts = {"en0": counter(100, 200), "en1": counter(500, 800), "utun0": counter(900, 1200), "lo0": counter(2000, 2000)}
        self.addresses = {
            name: [SimpleNamespace(family=socket.AF_INET, address="192.168.1.2")]
            for name in self.stats
        }
        self.patches = [
            patch.object(metrics.psutil, "net_if_stats", side_effect=lambda: self.stats),
            patch.object(metrics.psutil, "net_io_counters", side_effect=lambda **_: self.counts),
            patch.object(metrics.psutil, "net_if_addrs", side_effect=lambda: self.addresses),
        ]
        for current in self.patches:
            current.start()
            self.addCleanup(current.stop)
        self.collector = metrics.Collector()
        self.addCleanup(self.collector.close)

    def test_warmup_and_per_interface_rates_exclude_duplicate_virtual_traffic(self) -> None:
        self.assertEqual(self.collector._network(10)[:2], (None, None))
        self.counts["en0"] = counter(300, 800)
        self.counts["en1"] = counter(900, 1600)
        self.counts["utun0"] = counter(999999, 999999)
        upload, download, name = self.collector._network(12)
        self.assertEqual((upload, download), (300.0, 700.0))
        self.assertEqual(name, "en0 + en1")

    def test_counter_reset_warms_up_instead_of_negative_or_spike(self) -> None:
        self.collector._network(10)
        self.counts["en0"] = counter(1, 2)
        self.assertEqual(self.collector._network(11)[:2], (None, None))
        self.counts["en0"] = counter(101, 202)
        self.assertEqual(self.collector._network(13)[:2], (50.0, 100.0))

    def test_disconnect_reconnect_requires_a_fresh_baseline(self) -> None:
        self.collector.interface = "en0"
        self.collector._network(10)
        self.stats["en0"] = state(False)
        self.assertEqual(self.collector._network(11)[:2], (None, None))
        self.stats["en0"] = state(True)
        self.counts["en0"] = counter(100000, 200000)
        self.assertEqual(self.collector._network(15)[:2], (None, None))
        self.counts["en0"] = counter(100050, 200100)
        self.assertEqual(self.collector._network(16)[:2], (50.0, 100.0))

    def test_clock_not_advancing_is_unknown(self) -> None:
        self.collector._network(10)
        self.assertEqual(self.collector._network(10)[:2], (None, None))
        self.assertEqual(self.collector._network(9)[:2], (None, None))

    def test_idle_counter_is_real_zero_after_warmup(self) -> None:
        self.collector._network(10)
        self.assertEqual(self.collector._network(11)[:2], (0.0, 0.0))

    def test_explicit_virtual_adapter_is_supported(self) -> None:
        self.collector.interface = "utun0"
        self.collector._network(10)
        self.counts["utun0"] = counter(1100, 1400)
        self.assertEqual(self.collector._network(12), (100.0, 100.0, "utun0"))

    def test_adding_adapter_does_not_publish_partial_total(self) -> None:
        self.collector._network(10)
        self.stats["en2"] = state()
        self.addresses["en2"] = [SimpleNamespace(family=socket.AF_INET6, address="fe80::123%en2")]
        self.counts["en2"] = counter(100000, 100000)
        self.assertEqual(self.collector._network(11)[:2], (None, None))

    def test_auto_skips_active_bridge_member_without_ip(self) -> None:
        self.addresses["en1"] = []
        self.collector._network(10)
        self.counts["en0"] = counter(300, 800)
        self.counts["en1"] = counter(999999, 999999)
        self.assertEqual(self.collector._network(12), (100.0, 300.0, "en0"))

    def test_available_interfaces_include_offline_and_virtual_but_not_loopback(self) -> None:
        self.stats["en9"] = state(False)
        self.assertEqual(metrics.available_interfaces(), ["bridge0", "en0", "en1", "en9", "utun0"])

    def test_address_identifies_loopback_with_custom_name(self) -> None:
        address = SimpleNamespace(family=socket.AF_INET, address="127.0.0.1")
        self.assertTrue(metrics._is_loopback("custom", state(), [address]))
        self.assertFalse(metrics._is_virtual("Apple USB Ethernet"))
        self.assertTrue(metrics._is_virtual("ap1"))


class GPUParserTests(unittest.TestCase):
    def test_macos_busiest_device_and_real_zero(self) -> None:
        data = [{"IORegistryEntryChildren": [
            {"IORegistryEntryName": "Intel", "PerformanceStatistics": {"Device Utilization %": 0}},
            {"model": b"AMD GPU\0", "PerformanceStatistics": {"Device Utilization %": 31}},
        ]}]
        result = metrics._parse_macos_gpu(plistlib.dumps(data))
        self.assertEqual(result.percent, 31)
        self.assertEqual(result.name, "AMD GPU")
        result = metrics._parse_macos_gpu(plistlib.dumps(data[0]["IORegistryEntryChildren"][:1]))
        self.assertEqual(result.percent, 0)

    def test_macos_missing_or_invalid_percentage_is_not_zero(self) -> None:
        for stats in ({}, {"Device Utilization %": -1}, {"Device Utilization %": 101}, {"Device Utilization %": True}):
            with self.subTest(stats=stats):
                data = plistlib.dumps([{"PerformanceStatistics": stats}])
                self.assertIsNone(metrics._parse_macos_gpu(data).percent)

    def test_windows_sums_processes_per_engine_then_uses_busiest(self) -> None:
        result = metrics._aggregate_windows_gpu([
            (instance(1, 0), 20), (instance(2, 0), 30),
            (instance(3, 1), 45), (instance(4, 0, 1), 40),
        ])
        self.assertEqual(result.percent, 50)
        self.assertEqual(result.name, "GPU 0")

    def test_windows_distinct_adapter_luids_are_not_added(self) -> None:
        result = metrics._aggregate_windows_gpu([
            (instance(1), 30),
            (instance(2, luid="0x00000000_0x0000c002"), 40),
        ])
        self.assertEqual(result.percent, 40)

    def test_windows_duplicates_invalids_and_cap(self) -> None:
        result = metrics._aggregate_windows_gpu([
            (instance(1), 70), (instance(1), 70), (instance(2), 60),
            (instance(3), float("nan")), ("unrecognized", 100),
        ])
        self.assertEqual(result.percent, 100)
        self.assertIsNone(metrics._aggregate_windows_gpu([]).percent)

    def test_unsupported_macos_does_not_spawn_every_tick(self) -> None:
        probe = metrics._GPUProbe()
        result = SimpleNamespace(stdout=plistlib.dumps([{}]))
        with patch.object(metrics.sys, "platform", "darwin"), patch.object(metrics.subprocess, "run", return_value=result) as run:
            for now in (0, 1, 2, 59):
                self.assertIsNone(probe.sample(now).percent)
            self.assertEqual(run.call_count, 1)
            probe.sample(60)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.kwargs["timeout"], 1.5)

    def test_invalid_plist_and_timeout_degrade_and_back_off(self) -> None:
        for outcome in (SimpleNamespace(stdout=b"<plist>invalid"), subprocess.TimeoutExpired("ioreg", 1.5)):
            with self.subTest(outcome=outcome):
                probe = metrics._GPUProbe()
                arguments = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
                with patch.object(metrics.sys, "platform", "darwin"), patch.object(metrics.subprocess, "run", **arguments) as run:
                    self.assertIsNone(probe.sample(0).percent)
                    self.assertIn("60", probe.sample(1).detail)
                    self.assertEqual(run.call_count, 1)


class _FakeFunction:
    def __init__(self, implementation):
        self.implementation = implementation

    def __call__(self, *args):
        return self.implementation(*args)


class _FakePDH:
    def __init__(self, *, add_status: int = 0, grow_once: bool = False) -> None:
        self.closed = 0
        self.requests = 0
        self.grow_once = grow_once
        self.add_status = add_status
        self.PdhOpenQueryW = _FakeFunction(self.open)
        self.PdhAddEnglishCounterW = _FakeFunction(self.add)
        self.PdhCollectQueryData = _FakeFunction(lambda _: 0)
        self.PdhGetFormattedCounterArrayW = _FakeFunction(self.array)
        self.PdhCloseQuery = _FakeFunction(self.close)
        self.names = [ctypes.create_unicode_buffer(instance(1)), ctypes.create_unicode_buffer(instance(2))]

    def open(self, source, user, result):
        ctypes.cast(result, ctypes.POINTER(ctypes.c_void_p))[0] = 10
        return 0

    def add(self, query, path, user, result):
        ctypes.cast(result, ctypes.POINTER(ctypes.c_void_p))[0] = 20
        return self.add_status

    def array(self, counter_handle, fmt, size_pointer, count_pointer, buffer):
        size = ctypes.cast(size_pointer, ctypes.POINTER(ctypes.c_uint32))
        count = ctypes.cast(count_pointer, ctypes.POINTER(ctypes.c_uint32))
        count[0] = 2
        array = (metrics._CounterItem * 2)()
        for index, value in enumerate((20, 30)):
            array[index].szName = ctypes.cast(self.names[index], ctypes.c_wchar_p)
            array[index].FmtValue.CStatus = index
            array[index].FmtValue.doubleValue = value
        if buffer is None:
            size[0] = ctypes.sizeof(array)
            return metrics._WindowsGPU._MORE_DATA
        self.requests += 1
        if self.grow_once and self.requests == 1:
            size[0] = ctypes.sizeof(array) + 200
            return metrics._WindowsGPU._MORE_DATA
        ctypes.memmove(buffer, array, ctypes.sizeof(array))
        return 0

    def close(self, query):
        self.closed += 1
        return 0


class WindowsNativeTests(unittest.TestCase):
    def test_native_array_lifecycle_and_dynamic_buffer_retry(self) -> None:
        pdh = _FakePDH(grow_once=True)
        with patch.object(metrics.ctypes, "WinDLL", return_value=pdh, create=True):
            native = metrics._WindowsGPU()
            self.assertEqual(native.sample().percent, 50)
            self.assertEqual(pdh.requests, 2)
            native.close()
            native.close()
        self.assertEqual(pdh.closed, 1)

    def test_initialization_failure_closes_open_query(self) -> None:
        pdh = _FakePDH(add_status=0xC0000BB8)
        with patch.object(metrics.ctypes, "WinDLL", return_value=pdh, create=True):
            with self.assertRaises(OSError):
                metrics._WindowsGPU()
        self.assertEqual(pdh.closed, 1)

    def test_native_read_error_is_not_false_zero(self) -> None:
        pdh = _FakePDH()
        with patch.object(metrics.ctypes, "WinDLL", return_value=pdh, create=True):
            native = metrics._WindowsGPU()
            pdh.PdhCollectQueryData.implementation = lambda _: metrics._WindowsGPU._NO_DATA
            self.assertIsNone(native.sample().percent)
            native.close()


class CollectorTests(unittest.TestCase):
    def test_snapshot_all_defaults_and_format_unknown(self) -> None:
        self.assertIsNone(metrics.Snapshot(error="broken").cpu_percent)
        self.assertEqual(metrics.format_rate(None), "--")
        self.assertEqual(metrics.format_rate(float("nan")), "--")
        self.assertEqual(metrics.format_percent(None), "--")
        self.assertEqual(metrics.format_rate(0), "0 B/s")
        self.assertEqual(metrics.format_rate(1536), "1.5 K/s")

    def test_cpu_first_sample_unknown_and_memory_available_based(self) -> None:
        collector = metrics.Collector()
        collector._gpu = Mock()
        collector._gpu.sample.return_value = metrics._GPUReading()
        memory = SimpleNamespace(percent=25, total=1000, available=750, used=100)
        with patch.object(metrics.psutil, "cpu_percent", return_value=12.5), patch.object(metrics.psutil, "virtual_memory", return_value=memory), patch.object(collector, "_network", return_value=(0, 0, "en0")):
            first = collector.sample()
            second = collector.sample()
        self.assertIsNone(first.cpu_percent)
        self.assertEqual(second.cpu_percent, 12.5)
        self.assertEqual(second.memory_used, 250)
        self.assertEqual(second.memory_total, 1000)

    def test_network_failure_clears_baseline(self) -> None:
        collector = metrics.Collector()
        collector._previous = {"en0": (10, 100, 100)}
        collector._gpu = Mock()
        collector._gpu.sample.return_value = metrics._GPUReading()
        memory = SimpleNamespace(percent=25, total=1000, available=750)
        with patch.object(metrics.psutil, "cpu_percent", return_value=12.5), patch.object(metrics.psutil, "virtual_memory", return_value=memory), patch.object(collector, "_network", side_effect=OSError("offline")):
            result = collector.sample()
        self.assertIsNone(result.download_bps)
        self.assertIn("offline", result.error)
        self.assertEqual(collector._previous, {})


if __name__ == "__main__":
    unittest.main()
