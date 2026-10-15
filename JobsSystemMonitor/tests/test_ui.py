"""验证监控交互及缺测呈现。Created by Jobs."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import QApplication

from jobs_system_monitor.app import Controller
from jobs_system_monitor.metrics import Snapshot
from jobs_system_monitor.ui import MonitorPanel, status_image

APP = QApplication.instance() or QApplication([])
APP.setStyle("Fusion")
APP.setQuitOnLastWindowClosed(False)


class FakeSampler(QObject):
    ready = Signal(object)
    finished = Signal()

    def __init__(self, interface, interval):
        super().__init__()
        self.config = (interface, interval)

    def start(self):
        pass

    def configure(self, interface, interval, reset=False):
        self.config = (interface, interval, reset)

    def stop(self):
        pass

    def wait(self):
        return True


class MonitorTests(unittest.TestCase):
    def test_missing_gpu_is_not_zero_and_close_only_hides(self):
        panel = MonitorPanel("system", 1, "", False, False)
        panel.refresh(Snapshot(gpu_detail="驱动不提供利用率", memory_used=4 * 1024**3,
                               memory_total=16 * 1024**3))
        self.assertIn("驱动不提供利用率", panel.hardware.text())
        self.assertNotIn("0%", panel.gpu.value.text())
        panel.show()
        APP.processEvents()
        panel.close()
        self.assertFalse(panel.isVisible())
        panel.deleteLater()

    def test_disconnected_adapter_selection_survives_refresh(self):
        panel = MonitorPanel("dark", 2, "disconnected-adapter", False, True)
        with patch("jobs_system_monitor.ui.available_interfaces", return_value=[]):
            panel.refresh_interfaces()
        self.assertEqual(panel.interface.currentData(), "disconnected-adapter")
        panel.deleteLater()

    def test_preferences_survive_controller_restart(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "jobs_system_monitor.app.Sampler", FakeSampler
        ):
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            controller = Controller(APP, settings=settings, native=False)
            controller.change_theme("dark")
            controller.change_interval(2.0)
            controller.change_interface("en-test")
            self.assertEqual(controller.worker.config, ("en-test", 2.0, True))
            controller.cleanup()
            restarted = Controller(APP, settings=settings, native=False)
            self.assertEqual(restarted.theme, "dark")
            self.assertEqual(restarted.panel.theme.currentData(), "dark")
            self.assertEqual(restarted.interval, 2.0)
            self.assertEqual(restarted.interface, "en-test")
            restarted.cleanup()
            for item in (controller, restarted):
                APP.aboutToQuit.disconnect(item.cleanup)
                APP.styleHints().colorSchemeChanged.disconnect(item.refresh_theme)
                item.panel.deleteLater()
                item.bar.deleteLater()
                item.deleteLater()

    def test_status_image_has_retina_scale_and_transparency(self):
        image = status_image(Snapshot(cpu_percent=27, gpu_percent=15, memory_percent=59,
                                      upload_bps=23.2 * 1024, download_bps=502 * 1024))
        self.assertEqual(image.devicePixelRatio(), 2)
        self.assertEqual(image.width() / image.devicePixelRatio(), 280)
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertFalse(image.isNull())

    def test_changing_network_does_not_connect_different_adapter_histories(self):
        panel = MonitorPanel("system", 1, "", False, False)
        panel.refresh(Snapshot(network_name="en0", upload_bps=100, download_bps=200))
        panel.refresh(Snapshot(network_name="en0", upload_bps=300, download_bps=400))
        self.assertEqual(list(panel.up_chart.values), [100, 300])
        panel.refresh(Snapshot(network_name="en1", upload_bps=500, download_bps=600))
        self.assertEqual(list(panel.up_chart.values), [500])
        self.assertEqual(list(panel.down_chart.values), [600])
        panel.deleteLater()

    def test_background_position_updates_do_not_show_raise_or_activate_visible_bar(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "jobs_system_monitor.app.Sampler", FakeSampler
        ):
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("bar_enabled", True)
            controller = Controller(APP, settings=settings, native=False)
            self.assertTrue(controller.bar.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
            self.assertTrue(controller.bar.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
            with patch.object(controller.bar, "isVisible", return_value=True), \
                 patch.object(controller.bar, "show") as show, \
                 patch.object(controller.bar, "raise_") as raise_window, \
                 patch.object(controller.bar, "activateWindow") as activate:
                for _ in range(5):
                    controller.position_bar()
                    controller.refresh(Snapshot(cpu_percent=25))
                show.assert_not_called()
                raise_window.assert_not_called()
                activate.assert_not_called()
            controller.cleanup()
            controller.bar.hide()
            APP.aboutToQuit.disconnect(controller.cleanup)
            APP.styleHints().colorSchemeChanged.disconnect(controller.refresh_theme)
            controller.panel.deleteLater()
            controller.bar.deleteLater()
            controller.deleteLater()


if __name__ == "__main__":
    unittest.main()
