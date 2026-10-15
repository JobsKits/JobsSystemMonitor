"""应用生命周期、后台采集与平台入口。Created by Jobs."""

from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import threading
import time
from dataclasses import asdict

from PySide6.QtCore import (
    QLockFile, QObject, QPoint, QSettings, QStandardPaths, QThread, QTimer, Signal,
)
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .appearance import apply_appearance
from . import __version__
from .metrics import Collector, Snapshot, format_percent, format_rate
from .ui import CompactBar, MonitorPanel, status_image
from .windows_bar import TaskbarPlacement


def resource_icon() -> QIcon:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return QIcon(str(base / "assets" / "icon.png"))


class Sampler(QThread):
    ready = Signal(object)

    def __init__(self, interface: str, interval: float) -> None:
        super().__init__()
        self._mutex = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._config = (interface, interval, 0)

    def configure(self, interface: str, interval: float, reset: bool = False) -> None:
        with self._mutex:
            self._config = (interface, interval, self._config[2] + int(reset))
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def run(self) -> None:
        collector = None
        previous = None
        try:
            while not self._stop.is_set():
                with self._mutex:
                    interface, interval, generation = self._config
                identity = (interface, generation)
                try:
                    if previous != identity:
                        if collector is not None:
                            collector.close()
                            collector = None
                        collector = Collector(interface=interface or None)
                        previous = identity
                    self.ready.emit(collector.sample())
                except Exception as exc:
                    logging.exception("采集失败")
                    self.ready.emit(Snapshot(error=f"采集失败：{exc}，可点击重新采集"))
                self._wake.wait(interval)
                self._wake.clear()
        finally:
            if collector is not None:
                collector.close()


class Controller(QObject):
    def __init__(self, app: QApplication, settings: QSettings | None = None,
                 native: bool = True) -> None:
        super().__init__()
        self.app = app
        self.settings = settings if settings is not None else QSettings()
        self.theme = str(self.settings.value("theme", "system"))
        if self.theme not in ("system", "light", "dark"):
            self.theme = "system"
        try:
            self.interval = float(self.settings.value("interval", 1.0))
        except (TypeError, ValueError):
            self.interval = 1.0
        if self.interval not in (0.5, 1.0, 2.0, 5.0):
            self.interval = 1.0
        self.interface = str(self.settings.value("interface", ""))
        self.bar_enabled = self.settings.value("bar_enabled", sys.platform == "win32", type=bool)
        self._native = native
        self._quitting = False
        self._cleaned = False
        self.snapshot = Snapshot()
        self.mac_status = None
        self.tray = None
        self.placement = TaskbarPlacement() if sys.platform == "win32" and native else None
        self.panel = MonitorPanel(self.theme, self.interval, self.interface,
                                  self.bar_enabled, sys.platform == "win32")
        self.panel.setWindowIcon(resource_icon())
        self.bar = CompactBar()
        self.menu = QMenu()
        show_action = QAction("查看监控详情", self.menu)
        show_action.triggered.connect(self.show_panel)
        self.menu.addAction(show_action)
        reset_action = QAction("重置监控条位置", self.menu)
        reset_action.triggered.connect(self.reset_position)
        self.menu.addAction(reset_action)
        retry_action = QAction("重新采集", self.menu)
        retry_action.triggered.connect(self.retry)
        self.menu.addAction(retry_action)
        self.menu.addSeparator()
        quit_action = QAction("退出 Jobs System Monitor", self.menu)
        quit_action.triggered.connect(self.quit)
        self.menu.addAction(quit_action)
        self.bar.activated.connect(self.show_panel)
        self.bar.menu_requested.connect(lambda point: self.menu.popup(point))
        self.bar.moved.connect(self.save_position)
        self.panel.theme_changed.connect(self.change_theme)
        self.panel.interval_changed.connect(self.change_interval)
        self.panel.interface_changed.connect(self.change_interface)
        self.panel.bar_changed.connect(self.change_bar)
        self.panel.reset_requested.connect(self.reset_position)
        self.panel.retry_requested.connect(self.retry)
        self.panel.quit_requested.connect(self.quit)
        self.app.styleHints().colorSchemeChanged.connect(self.refresh_theme)
        self.refresh_theme()
        if native:
            self.setup_status()
        self.worker = Sampler(self.interface, self.interval)
        self.worker.ready.connect(self.refresh)
        self.position_timer = QTimer(self)
        self.position_timer.setInterval(1000)
        self.position_timer.timeout.connect(self.position_bar)
        self.app.aboutToQuit.connect(self.cleanup)
        self.position_bar()
        self.position_timer.start()
        # 初始化成功后才启动线程，避免半初始化对象退出时仍有采集线程。
        self.worker.start()

    def setup_status(self) -> None:
        if sys.platform == "darwin":
            try:
                from .macos_status import MacStatusItem
                self.mac_status = MacStatusItem(self.show_panel)
                self.mac_status.update(status_image(self.snapshot), "Jobs System Monitor · 点击查看")
                return
            except Exception:
                logging.exception("原生菜单栏初始化失败，使用托盘入口")
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(resource_icon(), self)
            self.tray.setContextMenu(self.menu)
            self.tray.setToolTip("Jobs System Monitor")
            self.tray.activated.connect(self.tray_activated)
            self.tray.show()
        else:
            self.panel.show()
            self.panel.note.setText("系统托盘不可用，请保留监控条以便重新打开详情。")
            self.change_bar(True)

    def tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_panel()

    def show_panel(self) -> None:
        self.panel.refresh_interfaces()
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def refresh(self, snapshot: Snapshot) -> None:
        if self._quitting:
            return
        self.snapshot = snapshot
        self.panel.refresh(snapshot)
        self.bar.snapshot = snapshot
        self.bar.update()
        tooltip = (
            f"CPU {format_percent(snapshot.cpu_percent)} · GPU {format_percent(snapshot.gpu_percent)}"
            f" · MEM {format_percent(snapshot.memory_percent)}\n"
            f"↑ {format_rate(snapshot.upload_bps)}  ↓ {format_rate(snapshot.download_bps)}\n"
            f"{snapshot.gpu_detail}"
        )
        self.bar.setToolTip(tooltip + "\n单击查看详情；拖动调整位置；右键打开菜单")
        if self.mac_status:
            try:
                self.mac_status.update(status_image(snapshot), tooltip)
            except Exception:
                logging.exception("菜单栏刷新失败")
        if self.tray:
            self.tray.setToolTip(tooltip)

    def refresh_theme(self, *_args) -> None:
        apply_appearance(self.theme)
        self.bar.update()

    def change_theme(self, mode: str) -> None:
        self.theme = mode
        self.settings.setValue("theme", mode)
        self.refresh_theme()

    def change_interval(self, interval: float) -> None:
        self.interval = interval
        self.settings.setValue("interval", interval)
        self.worker.configure(self.interface, self.interval)

    def change_interface(self, interface: str) -> None:
        self.interface = interface
        self.settings.setValue("interface", interface)
        self.worker.configure(self.interface, self.interval, reset=True)

    def retry(self) -> None:
        self.worker.configure(self.interface, self.interval, reset=True)

    def change_bar(self, enabled: bool) -> None:
        self.bar_enabled = enabled
        self.settings.setValue("bar_enabled", enabled)
        self.position_bar()

    def save_position(self, position: QPoint) -> None:
        self.settings.setValue("bar_position", position)

    def reset_position(self) -> None:
        self.settings.remove("bar_position")
        self.position_bar()

    def position_bar(self) -> None:
        if not self.bar_enabled or self._quitting:
            self.bar.hide()
            return
        if self.bar._drag_start is not None:
            return
        screen = self.app.primaryScreen()
        if screen is None:
            return
        try:
            placement = (self.placement.geometry(self.bar.width(), self.bar.height())
                         if self.placement else None)
        except (OSError, RuntimeError):
            logging.exception("任务栏位置读取失败，回退桌面悬浮位置")
            placement = None
        if self.placement and self.placement.auto_hidden:
            self.bar.hide()
            return
        stored = self.settings.value("bar_position")
        if isinstance(stored, QPoint):
            matching = self.app.screenAt(stored)
            if matching:
                bounds = matching.geometry()
                x = min(max(stored.x(), bounds.left()), max(bounds.left(), bounds.right() - self.bar.width() + 1))
                y = min(max(stored.y(), bounds.top()), max(bounds.top(), bounds.bottom() - self.bar.height() + 1))
                self.bar.move(x, y)
            else:
                self.settings.remove("bar_position")
                stored = None
        if not isinstance(stored, QPoint):
            if placement:
                self.bar.setGeometry(placement)
            else:
                bounds = screen.availableGeometry()
                self.bar.move(bounds.right() - self.bar.width() - 12, bounds.bottom() - self.bar.height() - 12)
        # 后台定位不能每秒 show/raise，macOS 会因此反复抢走其它应用的焦点。
        if not self.bar.isVisible():
            self.bar.show()

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.position_timer.stop()
        self.bar.hide()
        self.panel.hide()
        self.worker.stop()
        self.worker.finished.connect(self.app.quit)
        if not self.worker.isRunning():
            self.app.quit()

    def cleanup(self) -> None:
        if self._cleaned:
            return
        self._cleaned = True
        self.position_timer.stop()
        self.worker.stop()
        self.worker.wait()  # 子进程采集有超时，退出前等待释放 PDH 查询句柄。
        if self.mac_status:
            self.mac_status.close()
            self.mac_status = None
        if self.tray:
            self.tray.hide()
        self.settings.sync()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Jobs 菜单栏 / 任务栏整机监控")
    parser.add_argument("--window", action="store_true", help="启动时显示详情面板")
    parser.add_argument("--diagnose", action="store_true", help="输出一次真实采样 JSON 后退出")
    args = parser.parse_args(argv)
    if args.diagnose:
        collector = Collector()
        try:
            collector.sample()
            time.sleep(1)
            print(json.dumps(asdict(collector.sample()), ensure_ascii=False, indent=2))
            return 0
        finally:
            collector.close()
    if sys.platform not in ("darwin", "win32"):
        parser.error("图形界面支持 macOS 和 Windows；其它平台可使用 --diagnose")
    app = QApplication([sys.argv[0]])
    app.setOrganizationName("Jobs")
    app.setApplicationName("JobsSystemMonitor")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setWindowIcon(resource_icon())
    app.setQuitOnLastWindowClosed(False)
    data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    data_dir.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(data_dir / "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.information(None, "Jobs System Monitor", "监控已在运行，请点击菜单栏或托盘入口。")
        return 0
    handler = RotatingFileHandler(data_dir / "monitor.log", maxBytes=512 * 1024,
                                 backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(message)s")
    controller = None
    try:
        controller = Controller(app)
        if args.window or not controller.settings.value("has_opened", False, type=bool):
            controller.show_panel()
            controller.settings.setValue("has_opened", True)
        return app.exec()
    except Exception as exc:
        logging.exception("启动失败")
        QMessageBox.critical(None, "启动失败", f"{exc}\n日志：{data_dir / 'monitor.log'}")
        return 1
    finally:
        if controller is not None:
            controller.cleanup()
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
