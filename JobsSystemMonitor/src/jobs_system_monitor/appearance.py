"""统一 Qt 控件的三态外观。Created by Jobs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_appearance(mode: str) -> bool:
    """应用白天、黑夜或系统外观，返回当前是否为黑夜。"""
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("主题必须在 QApplication 创建后应用")
    if mode not in {"system", "light", "dark"}:
        raise ValueError(f"未知主题：{mode}")
    dark = mode == "dark" or (
        mode == "system" and app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    )
    values = (
        {
            "window": "#1b2029", "base": "#141922", "alternate": "#222936",
            "button": "#293140", "text": "#edf1f7", "muted": "#9da7b7",
            "highlight": "#356fb9", "selected": "#ffffff", "border": "#465163",
            "light": "#4b586b", "midlight": "#364254", "shadow": "#0b0f16",
            "link": "#7bb8ff", "visited": "#d0a2fa", "disabled": "#8893a4",
            "disabled_base": "#202631", "disabled_selected": "#34475e",
            "tooltip": "#303b4b", "bright": "#ffb4ab",
        }
        if dark else
        {
            "window": "#f1f4f8", "base": "#ffffff", "alternate": "#e9eef5",
            "button": "#e5eaf2", "text": "#172334", "muted": "#5b6a7e",
            "highlight": "#2563ab", "selected": "#ffffff", "border": "#aab5c4",
            "light": "#ffffff", "midlight": "#edf1f6", "shadow": "#627084",
            "link": "#155da6", "visited": "#714ba3", "disabled": "#728096",
            "disabled_base": "#e5e9ef", "disabled_selected": "#cbd5e3",
            "tooltip": "#ffffff", "bright": "#b3261e",
        }
    )
    roles = {
        QPalette.ColorRole.Window: "window",
        QPalette.ColorRole.WindowText: "text",
        QPalette.ColorRole.Base: "base",
        QPalette.ColorRole.AlternateBase: "alternate",
        QPalette.ColorRole.Text: "text",
        QPalette.ColorRole.Button: "button",
        QPalette.ColorRole.ButtonText: "text",
        QPalette.ColorRole.BrightText: "bright",
        QPalette.ColorRole.Light: "light",
        QPalette.ColorRole.Midlight: "midlight",
        QPalette.ColorRole.Dark: "border",
        QPalette.ColorRole.Mid: "border",
        QPalette.ColorRole.Shadow: "shadow",
        QPalette.ColorRole.Highlight: "highlight",
        QPalette.ColorRole.HighlightedText: "selected",
        QPalette.ColorRole.Link: "link",
        QPalette.ColorRole.LinkVisited: "visited",
        QPalette.ColorRole.ToolTipBase: "tooltip",
        QPalette.ColorRole.ToolTipText: "text",
        QPalette.ColorRole.PlaceholderText: "muted",
        QPalette.ColorRole.Accent: "highlight",
    }
    palette = QPalette(app.style().standardPalette())
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        for role, key in roles.items():
            palette.setColor(group, role, QColor(values[key]))
    for role, key in roles.items():
        if role in {
            QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
            QPalette.ColorRole.ButtonText, QPalette.ColorRole.PlaceholderText,
            QPalette.ColorRole.Link, QPalette.ColorRole.LinkVisited,
        }:
            key = "disabled"
        elif role in {QPalette.ColorRole.Base, QPalette.ColorRole.Button}:
            key = "disabled_base"
        elif role in {QPalette.ColorRole.Highlight, QPalette.ColorRole.Accent}:
            key = "disabled_selected"
        elif role == QPalette.ColorRole.HighlightedText:
            key = "text"
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(values[key]))
    app.setPalette(palette)
    # Fusion 使用完整 palette；少量样式补齐菜单边界、表头角按钮及弹出视图。
    app.setStyleSheet("""
        QToolTip {
            color: __TEXT__; background: __TOOLTIP__;
            border: 1px solid palette(mid); padding: 5px;
        }
        QMenu, QComboBox QAbstractItemView {
            color: palette(text); background: palette(base);
            border: 1px solid palette(mid);
            selection-background-color: palette(highlight);
            selection-color: palette(highlighted-text);
        }
        QMenu::item { padding: 6px 24px; }
        QMenu::item:selected { background: palette(highlight); color: palette(highlighted-text); }
        QMenu::item:disabled { color: __DISABLED__; }
        QMenu::separator { background: palette(mid); height: 1px; margin: 4px 8px; }
        QHeaderView::section, QTableCornerButton::section {
            color: palette(button-text); background: palette(button);
            border: 1px solid palette(mid); padding: 5px;
        }
        QTableView { gridline-color: palette(mid); alternate-background-color: palette(alternate-base); }
        QProgressBar {
            color: palette(text); background: palette(base);
            border: 1px solid palette(mid); border-radius: 4px; text-align: center;
        }
        QProgressBar::chunk { background: palette(highlight); border-radius: 3px; }
        QScrollBar { background: palette(window); }
        QScrollBar::handle { background: palette(mid); border-radius: 4px; min-width: 16px; min-height: 16px; }
    """.replace("__TEXT__", values["text"])
        .replace("__TOOLTIP__", values["tooltip"])
        .replace("__DISABLED__", values["disabled"]))
    return dark
