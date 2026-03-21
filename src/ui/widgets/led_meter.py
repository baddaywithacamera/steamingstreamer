"""
STEAMING STREAM — LED VU Meter Widget
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

Segmented LED bar meter. Fully dynamic — fills whatever space it's given.

Segment layout (20 segments, bottom to top):
  Segments  0–13  green   (-40 to -9 dBFS)
  Segments 14–16  yellow  ( -9 to -3 dBFS)
  Segments 17–19  red     ( -3 to  0 dBFS)
"""

import math

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

class _Palette:
    GREEN       = QColor(0,   210,   0)
    YELLOW      = QColor(255, 200,   0)
    RED         = QColor(255,  45,   0)
    GREEN_OFF   = QColor(0,   42,    0)
    YELLOW_OFF  = QColor(52,  40,    0)
    RED_OFF     = QColor(52,   8,    0)
    PEAK        = QColor(255, 255,  160)
    CLIP_ON     = QColor(255,   0,    0)
    CLIP_OFF    = QColor(50,    0,    0)
    BG          = QColor(16,   16,   16)


# ---------------------------------------------------------------------------
# Single channel — fully resizable
# ---------------------------------------------------------------------------

class LEDChannel(QWidget):
    """One LED bar (L or R). Segments computed from actual widget size."""

    SEGMENTS     = 20
    PEAK_HOLD    = 90    # ticks before peak starts to decay (~3 s at 30 fps)
    MIN_SEG_H    = 3     # px — don't let segments get tinier than this
    CLIP_BAR_H   = 4     # px — thin bar at very top for clip indicator
    GAP_RATIO    = 0.25  # gap = seg_h * this (keeps proportions at any size)

    _YELLOW_FLOOR = 14
    _RED_FLOOR    = 17

    def __init__(self, parent=None):
        super().__init__(parent)
        self._level: float = 0.0
        self._peak_seg: int = -1
        self._peak_counter: int = 0
        self._clipping: bool = False

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(10, 60)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_level(self, level: float) -> None:
        self._level    = max(0.0, min(1.05, level))
        self._clipping = self._level >= 1.0
        active = self._amp_to_segs(self._level)

        if active > self._peak_seg:
            self._peak_seg     = active
            self._peak_counter = self.PEAK_HOLD
        elif self._peak_counter > 0:
            self._peak_counter -= 1
        else:
            if self._peak_seg > active:
                self._peak_seg -= 1

        self.update()

    def reset(self) -> None:
        self._level = 0.0
        self._peak_seg = -1
        self._peak_counter = 0
        self._clipping = False
        self.update()

    # ------------------------------------------------------------------
    # Geometry helpers — all computed from current widget size
    # ------------------------------------------------------------------

    def _geometry(self):
        """Return (seg_h, seg_gap, seg_w, x_offset) for current widget size."""
        usable_h = self.height() - self.CLIP_BAR_H - 2
        # Gap is proportional so it stays visually consistent at any height
        seg_h = max(
            self.MIN_SEG_H,
            int(usable_h / (self.SEGMENTS * (1 + self.GAP_RATIO)))
        )
        seg_gap = max(1, int(seg_h * self.GAP_RATIO))
        seg_w   = max(4, self.width() - 4)
        x_off   = (self.width() - seg_w) // 2
        return seg_h, seg_gap, seg_w, x_off

    def _amp_to_segs(self, amp: float) -> int:
        if amp <= 0:
            return 0
        db = 20.0 * math.log10(max(amp, 1e-9))
        db = max(-40.0, min(0.0, db))
        return int((db + 40.0) / 40.0 * self.SEGMENTS)

    def _seg_colors(self, i: int):
        if i >= self._RED_FLOOR:
            return _Palette.RED, _Palette.RED_OFF
        if i >= self._YELLOW_FLOOR:
            return _Palette.YELLOW, _Palette.YELLOW_OFF
        return _Palette.GREEN, _Palette.GREEN_OFF

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.fillRect(self.rect(), _Palette.BG)

        seg_h, seg_gap, seg_w, x_off = self._geometry()
        active = self._amp_to_segs(self._level)

        for i in range(self.SEGMENTS):
            y = (
                self.height()
                - (i + 1) * (seg_h + seg_gap)
                + seg_gap
            )
            if y < self.CLIP_BAR_H + 2:
                continue   # don't overdraw the clip bar area

            lit        = i < active
            is_peak    = (i == self._peak_seg and not lit)
            lit_c, unlit_c = self._seg_colors(i)

            if is_peak:
                color = _Palette.PEAK
            elif lit:
                color = lit_c
            else:
                color = unlit_c

            p.fillRect(x_off, y, seg_w, seg_h, color)

        # Clip bar
        p.fillRect(
            x_off, 0, seg_w, self.CLIP_BAR_H,
            _Palette.CLIP_ON if self._clipping else _Palette.CLIP_OFF
        )


# ---------------------------------------------------------------------------
# Stereo pair — resizable
# ---------------------------------------------------------------------------

class StereoMeter(QWidget):
    """L + R LED meter pair. Expands to fill available space."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(3)

        self.left  = LEDChannel(self)
        self.right = LEDChannel(self)

        layout.addWidget(self.left)
        layout.addWidget(self.right)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_levels(self, left: float, right: float) -> None:
        self.left.set_level(left)
        self.right.set_level(right)

    def set_level(self, level: float) -> None:
        self.left.set_level(level)
        self.right.set_level(level)

    def reset(self) -> None:
        self.left.reset()
        self.right.reset()
