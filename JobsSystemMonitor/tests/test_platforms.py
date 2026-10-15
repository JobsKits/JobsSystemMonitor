"""任务栏布局验证不需要 Windows 桌面或原生句柄。Created by Jobs."""

import sys
import unittest

from jobs_system_monitor.windows_bar import TaskbarPlacement, fit_bar


class TaskbarGeometryTests(unittest.TestCase):
    def test_horizontal_uses_space_left_of_notification_area(self):
        self.assertEqual(
            fit_bar((0, 1040, 1920, 1080), (1660, 1040, 1920, 1080), 340, 32),
            (1312, 1044, 340, 32),
        )

    def test_retina_uses_logical_widget_size_and_coordinates(self):
        self.assertEqual(
            fit_bar((0, 2080, 3840, 2160), (3320, 2080, 3840, 2160), 340, 32, 2),
            (1312, 1044, 340, 32),
        )

    def test_missing_notify_reserves_system_icon_space(self):
        self.assertEqual(
            fit_bar((0, 1040, 1920, 1080), None, 340, 32),
            (1292, 1044, 340, 32),
        )

    def test_collapsed_or_offscreen_notification_area_uses_reserve(self):
        for notify in ((0, 0, 0, 0), (0, -48, 300, -1)):
            self.assertEqual(
                fit_bar((0, 1040, 1920, 1080), notify, 340, 32),
                (1292, 1044, 340, 32),
            )

    def test_top_taskbar(self):
        self.assertEqual(
            fit_bar((0, 0, 1920, 48), (1660, 0, 1920, 48), 340, 32),
            (1312, 8, 340, 32),
        )

    def test_vertical_taskbar_accepts_only_a_bar_that_fits(self):
        self.assertIsNone(fit_bar((0, 0, 48, 1080), None, 340, 32))
        self.assertEqual(
            fit_bar((0, 0, 48, 1080), (0, 900, 48, 1080), 40, 120),
            (4, 772, 40, 120),
        )

    def test_autohide_edge_and_small_taskbar_fail_safely(self):
        self.assertIsNone(fit_bar((0, 1078, 1920, 1080), None, 340, 32))
        self.assertIsNone(fit_bar((0, 0, 320, 40), None, 340, 32))

    def test_invalid_geometry_rejected(self):
        self.assertIsNone(fit_bar((10, 0, 0, 40), None, 340, 32))
        self.assertIsNone(fit_bar((0, 0, 1920, 40), None, 340, 32, 0))

    @unittest.skipIf(sys.platform == "win32", "非 Windows 导入保护")
    def test_native_helper_is_inert_on_other_platforms(self):
        placement = TaskbarPlacement()
        self.assertFalse(placement.is_available)
        self.assertIsNone(placement.geometry(340, 32))


if __name__ == "__main__":
    unittest.main()
