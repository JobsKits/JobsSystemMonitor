"""紧凑监控条与详情面板。Created by Jobs."""

from __future__ import annotations

from collections import deque
import sys

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from .metrics import Snapshot, available_interfaces, format_percent, format_rate


def draw_readout(painter: QPainter, snapshot: Snapshot, width: int, height: int,
                 foreground: QColor) -> None:
    """菜单栏和任务栏共用排版，宽度固定，数值变化时不推动其它图标。"""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(foreground)
    column = (width - 124) / 3
    values = (snapshot.cpu_percent, snapshot.gpu_percent, snapshot.memory_percent)
    large = QFont("Arial")
    large.setPixelSize(12 if height > 24 else 11)
    large.setBold(True)
    small = QFont("Arial")
    small.setPixelSize(9 if height > 24 else 8)
    top = max(0, (height - 24) / 2)
    for index, (value, label) in enumerate(zip(values, ("CPU", "GPU", "MEM"))):
        x = index * column
        painter.setFont(large)
        painter.drawText(QRectF(x, top, column - 1, 14), Qt.AlignmentFlag.AlignCenter,
                         format_percent(value))
        painter.setFont(small)
        painter.drawText(QRectF(x, top + 13, column - 1, 10),
                         Qt.AlignmentFlag.AlignCenter, label)
        separator = QColor(foreground)
        separator.setAlpha(85)
        painter.setPen(separator)
        painter.drawLine(QPoint(round(x + column), 4),
                         QPoint(round(x + column), height - 4))
        painter.setPen(foreground)
    painter.setFont(large)
    network_x = 3 * column + 9
    painter.drawText(QRectF(network_x, top, 114, 13), Qt.AlignmentFlag.AlignVCenter,
                     f"↑ {format_rate(snapshot.upload_bps)}")
    painter.drawText(QRectF(network_x, top + 12, 114, 13), Qt.AlignmentFlag.AlignVCenter,
                     f"↓ {format_rate(snapshot.download_bps)}")


def status_image(snapshot: Snapshot) -> QImage:
    image = QImage(280 * 2, 24 * 2, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(2)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    draw_readout(painter, snapshot, 280, 24, QColor("black"))
    painter.end()
    return image


class CompactBar(QWidget):
    activated = Signal()
    menu_requested = Signal(QPoint)
    moved = Signal(QPoint)

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        if sys.platform == "darwin":
            # NSPanel 在应用失活时保持可见，避免后台刷新重新显示它而激活应用。
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(322, 36)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("单击查看详情；拖动调整位置；右键打开菜单")
        self.snapshot = Snapshot()
        self._drag_start: QPoint | None = None
        self._origin = QPoint()
        self._dragged = False

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        draw_readout(painter, self.snapshot, self.width(), self.height(),
                     self.palette().windowText().color())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(event.globalPosition().toPoint())
        elif event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
            self._origin = self.pos()
            self._dragged = False

    def mouseMoveEvent(self, event) -> None:
        if self._drag_start is not None:
            offset = event.globalPosition().toPoint() - self._drag_start
            if offset.manhattanLength() > 4:
                self._dragged = True
            if self._dragged:
                self.move(self._origin + offset)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
            if self._dragged:
                self.moved.emit(self.pos())
            else:
                self.activated.emit()
            self._drag_start = None


class Sparkline(QWidget):
    def __init__(self, color: str, ceiling: float | None = 100) -> None:
        super().__init__()
        self.values: deque[float | None] = deque(maxlen=60)
        self.color = QColor(color)
        self.ceiling = ceiling
        self.setMinimumHeight(36)

    def append(self, value: float | None) -> None:
        self.values.append(value)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self.palette().mid().color()
        color.setAlpha(70)
        painter.setPen(color)
        painter.drawLine(0, self.height() - 2, self.width(), self.height() - 2)
        valid = [value for value in self.values if value is not None]
        if len(valid) < 2:
            return
        ceiling = self.ceiling or max(1024, max(valid) * 1.15)
        path = QPainterPath()
        connected = False
        # 缺测会断开曲线，不把不支持的 GPU 画成 0%。
        for index, value in enumerate(self.values):
            if value is None:
                connected = False
                continue
            x = index * (self.width() - 2) / 59
            y = self.height() - 3 - min(value / ceiling, 1) * (self.height() - 6)
            if connected:
                path.lineTo(x, y)
            else:
                path.moveTo(x, y)
                connected = True
        painter.setPen(QPen(self.color, 1.8))
        painter.drawPath(path)


class MetricCard(QFrame):
    def __init__(self, title: str, color: str) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 8)
        self.title = QLabel(title)
        self.title.setStyleSheet("font-size: 11px; font-weight: 600;")
        self.value = QLabel("—")
        self.value.setStyleSheet("font-size: 28px; font-weight: 600;")
        self.chart = Sparkline(color)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.chart)

    def refresh(self, value: float | None) -> None:
        self.value.setText(format_percent(value))
        self.chart.append(value)


def memory_text(used: int, total: int) -> str:
    if not total:
        return "内存采集中…"
    return f"{used / 1024 ** 3:.1f} / {total / 1024 ** 3:.1f} GiB"


class MonitorPanel(QDialog):
    theme_changed = Signal(str)
    interval_changed = Signal(float)
    interface_changed = Signal(str)
    bar_changed = Signal(bool)
    reset_requested = Signal()
    retry_requested = Signal()
    quit_requested = Signal()

    def __init__(self, theme: str, interval: float, interface: str,
                 bar_enabled: bool, windows: bool) -> None:
        super().__init__()
        self.setWindowTitle("Jobs System Monitor")
        self.resize(490, 620)
        self.setMinimumWidth(450)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 16)
        root.setSpacing(14)
        title_row = QHBoxLayout()
        title = QLabel("整机监控")
        title.setStyleSheet("font-size: 24px; font-weight: 700;")
        title_row.addWidget(title)
        title_row.addStretch()
        self.state_label = QLabel("● 连接采集器")
        title_row.addWidget(self.state_label)
        root.addLayout(title_row)
        self.summary = QLabel("Jobs System Monitor  ·  60 个采样点趋势")
        root.addWidget(self.summary)

        cards = QHBoxLayout()
        self.cpu = MetricCard("CPU", "#5396e8")
        self.gpu = MetricCard("GPU", "#bd82eb")
        self.memory = MetricCard("MEM", "#39b5a0")
        for card in (self.cpu, self.gpu, self.memory):
            cards.addWidget(card)
        root.addLayout(cards)
        self.hardware = QLabel("正在读取硬件状态…")
        self.hardware.setWordWrap(True)
        root.addWidget(self.hardware)

        network = QFrame()
        network.setFrameShape(QFrame.Shape.StyledPanel)
        network_layout = QGridLayout(network)
        network_layout.setContentsMargins(14, 10, 14, 8)
        network_layout.addWidget(QLabel("↑ 上传"), 0, 0)
        network_layout.addWidget(QLabel("↓ 下载"), 0, 1)
        self.upload = QLabel("—")
        self.download = QLabel("—")
        for label in (self.upload, self.download):
            label.setStyleSheet("font-size: 24px; font-weight: 600;")
        network_layout.addWidget(self.upload, 1, 0)
        network_layout.addWidget(self.download, 1, 1)
        self.up_chart = Sparkline("#d39a3f", None)
        self.down_chart = Sparkline("#5396e8", None)
        network_layout.addWidget(self.up_chart, 2, 0)
        network_layout.addWidget(self.down_chart, 2, 1)
        root.addWidget(network)
        self.network_hint = QLabel("正在建立网卡计数基线…")
        self.network_hint.setWordWrap(True)
        root.addWidget(self.network_hint)

        settings = QGridLayout()
        settings.setHorizontalSpacing(12)
        self.theme = QComboBox()
        for text, value in (("跟随系统", "system"), ("白天", "light"), ("黑夜", "dark")):
            self.theme.addItem(text, value)
        self.theme.setCurrentIndex(max(0, self.theme.findData(theme)))
        self.interval = QComboBox()
        for value in (0.5, 1.0, 2.0, 5.0):
            self.interval.addItem(f"{value:g} 秒", value)
        self.interval.setCurrentIndex(max(0, self.interval.findData(interval)))
        self.interface = QComboBox()
        self._selected_interface = interface
        self._network_name: str | None = None
        self.refresh_interfaces()
        self.reload_interfaces = QPushButton("刷新网卡")
        settings.addWidget(QLabel("主题"), 0, 0)
        settings.addWidget(self.theme, 0, 1)
        settings.addWidget(QLabel("刷新间隔"), 0, 2)
        settings.addWidget(self.interval, 0, 3)
        settings.addWidget(QLabel("监控网卡"), 1, 0)
        settings.addWidget(self.interface, 1, 1, 1, 2)
        settings.addWidget(self.reload_interfaces, 1, 3)
        root.addLayout(settings)
        self.bar_toggle = QCheckBox("显示任务栏监控条" if windows else "显示桌面悬浮条")
        self.bar_toggle.setChecked(bar_enabled)
        bar_row = QHBoxLayout()
        bar_row.addWidget(self.bar_toggle)
        bar_row.addStretch()
        self.reset = QPushButton("重置位置")
        bar_row.addWidget(self.reset)
        root.addLayout(bar_row)
        self.note = QLabel(
            "监控条可拖动；若挡住任务栏图标，请调整位置。" if windows else
            "菜单栏文字自动适应系统外观；点击菜单栏可再次打开此面板。"
        )
        self.note.setWordWrap(True)
        root.addWidget(self.note)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)
        footer = QHBoxLayout()
        self.retry = QPushButton("重新采集")
        self.hide_button = QPushButton("收起面板")
        self.quit_button = QPushButton("退出")
        footer.addWidget(self.retry)
        footer.addStretch()
        footer.addWidget(self.hide_button)
        footer.addWidget(self.quit_button)
        root.addLayout(footer)

        self.theme.currentIndexChanged.connect(
            lambda: self.theme_changed.emit(self.theme.currentData()))
        self.interval.currentIndexChanged.connect(
            lambda: self.interval_changed.emit(self.interval.currentData()))
        self.interface.currentIndexChanged.connect(self._select_interface)
        self.reload_interfaces.clicked.connect(self.refresh_interfaces)
        self.bar_toggle.toggled.connect(self.bar_changed)
        self.reset.clicked.connect(self.reset_requested)
        self.retry.clicked.connect(self.retry_requested)
        self.hide_button.clicked.connect(self.hide)
        self.quit_button.clicked.connect(self.quit_requested)

    def _select_interface(self) -> None:
        self._selected_interface = self.interface.currentData() or ""
        self.interface_changed.emit(self._selected_interface)

    def refresh_interfaces(self) -> None:
        self.interface.blockSignals(True)
        self.interface.clear()
        self.interface.addItem("自动 · 活跃物理网卡", "")
        try:
            names = available_interfaces()
        except Exception:
            names = []
        if self._selected_interface and self._selected_interface not in names:
            names.append(self._selected_interface)
        for name in names:
            self.interface.addItem(name, name)
        self.interface.setCurrentIndex(max(0, self.interface.findData(self._selected_interface)))
        self.interface.blockSignals(False)

    def refresh(self, snapshot: Snapshot) -> None:
        self.cpu.refresh(snapshot.cpu_percent)
        self.gpu.refresh(snapshot.gpu_percent)
        self.memory.refresh(snapshot.memory_percent)
        self.upload.setText(format_rate(snapshot.upload_bps))
        self.download.setText(format_rate(snapshot.download_bps))
        if snapshot.network_name != self._network_name:
            self.up_chart.values.clear()
            self.down_chart.values.clear()
            self._network_name = snapshot.network_name
        self.up_chart.append(snapshot.upload_bps)
        self.down_chart.append(snapshot.download_bps)
        self.hardware.setText(
            f"内存 {memory_text(snapshot.memory_used, snapshot.memory_total)}\n"
            f"{snapshot.gpu_name or 'GPU'} · {snapshot.gpu_detail}"
        )
        self.network_hint.setText(f"网卡：{snapshot.network_name or '暂无可用网卡'}  ·  单位为字节/秒")
        self.state_label.setText("● 采集异常" if snapshot.error else "● 实时")
        self.error.setText(snapshot.error)
        self.error.setVisible(bool(snapshot.error))

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
