"""
meter_window.py — Floating snappable meter window
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from src.ui.snappable_window import SnappableWindow
from src.ui.widgets.led_meter import StereoMeter
from src.ui.widgets.vu_needle import StereoVUMeter
from src.ui.widgets.dot_meter import StereoDotMeter


def _make_meter(style: str, parent=None):
    if style == "vu":
        return StereoVUMeter(parent)
    if style == "dot":
        return StereoDotMeter(parent)
    return StereoMeter(parent)


class MeterWindow(SnappableWindow):
    """
    Floating level-meter window (LED / VU / Dot).
    Registers with SnapManager so it can snap to main window + other panels.
    """

    def __init__(self, style: str = "led", parent=None):
        super().__init__("Meters", parent)
        self.setMinimumSize(80, 120)
        self.resize(160, 300)

        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(2)

        # ── Header bar ────────────────────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(4, 0, 4, 0)
        lbl = QLabel("METERS")
        lbl.setStyleSheet("font-size: 9px; font-weight: 700; color: #555; letter-spacing: 1px;")

        self._style_combo = QComboBox()
        self._style_combo.addItems(["LED", "VU", "Dot"])
        self._style_combo.setFixedWidth(56)
        self._style_combo.setCurrentText(style.upper())
        self._style_combo.currentTextChanged.connect(self._on_style_changed)

        header.addWidget(lbl)
        header.addStretch()
        header.addWidget(self._style_combo)
        root.addLayout(header)

        # ── Meter widget ───────────────────────────────────────────────
        self._style = style
        self.meter  = _make_meter(style, self)
        self.meter.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self.meter, stretch=1)

    # ------------------------------------------------------------------

    def set_levels(self, left: float, right: float) -> None:
        self.meter.set_levels(left, right)

    def set_style(self, style: str) -> None:
        """Hot-swap the meter widget."""
        if style == self._style:
            return
        self._style = style
        layout = self.layout()
        layout.removeWidget(self.meter)
        self.meter.deleteLater()
        self.meter = _make_meter(style, self)
        self.meter.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self.meter, stretch=1)

    def _on_style_changed(self, text: str) -> None:
        self.set_style(text.lower())
