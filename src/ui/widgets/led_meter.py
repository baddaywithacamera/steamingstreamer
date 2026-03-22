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

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QLinearGradient
from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

class _Palette:
    # Lit colours — slightly warm/bright for realism
    GREEN        = QColor(0,   220,  30)
    GREEN_HI     = QColor(80,  255, 100)   # highlight centre
    YELLOW       = QColor(255, 210,   0)
    YELLOW_HI    = QColor(255, 245, 120)
    RED          = QColor(255,  50,  20)
    RED_HI       = QColor(255, 140,  80)

    # Unlit colours — dark but not invisible
    GREEN_OFF    = QColor(0,   38,    8)
    YELLOW_OFF   = QColor(46,  36,    0)
    RED_OFF      = QColor(50,   8,    4)

    PEAK         = QColor(255, 255, 180)
    CLIP_ON      = QColor(255,  20,  20)
    CLIP_OFF     = QColor(45,    0,   0)
    BG           = QColor(14,   14,  14)


# ---------------------------------------------------------------------------
# Single channel — fully resizable
# ---------------------------------------------------------------------------

class LEDChannel(QWidget):
    """One LED bar (L or R). Segments computed from actual widget size."""

    SEGMENTS     = 20
    PEAK_HOLD    = 90     # ticks before peak decays (~3 s at 30 fps)
    MIN_SEG_H    = 3      # px minimum segment height
    CLIP_BAR_H   = 5      # px — clip indicator strip at very top
    CLIP_GAP     = 2      # px — gap between clip bar and first segment
    GAP_RATIO    = 0.22   # gap = seg_h × this
    RADIUS       = 1.5    # px — rounded corner radius on each segment

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
    # Geometry helpers — float-based so segments fill exactly top→bottom
    # ------------------------------------------------------------------

    def _geometry(self):
        """
        Return (seg_h, seg_gap, seg_w, x_offset) as floats.
        Segments are anchored from the clip bar, filling the full height.
        """
        usable_h = self.height() - self.CLIP_BAR_H - self.CLIP_GAP
        # Solve: usable_h = N*seg_h + (N-1)*seg_gap,  seg_gap = seg_h * GAP_RATIO
        # usable_h = seg_h * (N + (N-1)*GAP_RATIO)
        n = self.SEGMENTS
        denom = n + (n - 1) * self.GAP_RATIO
        seg_h = max(float(self.MIN_SEG_H), usable_h / denom)
        seg_gap = seg_h * self.GAP_RATIO
        seg_w = max(4.0, float(self.width() - 4))
        x_off = (self.width() - seg_w) / 2.0
        return seg_h, seg_gap, seg_w, x_off

    def _amp_to_segs(self, amp: float) -> int:
        if amp <= 0:
            return 0
        db = 20.0 * math.log10(max(amp, 1e-9))
        db = max(-40.0, min(0.0, db))
        return int((db + 40.0) / 40.0 * self.SEGMENTS)

    def _seg_colors(self, i: int):
        """Return (base_color, highlight_color, unlit_color) for segment i."""
        if i >= self._RED_FLOOR:
            return _Palette.RED, _Palette.RED_HI, _Palette.RED_OFF
        if i >= self._YELLOW_FLOOR:
            return _Palette.YELLOW, _Palette.YELLOW_HI, _Palette.YELLOW_OFF
        return _Palette.GREEN, _Palette.GREEN_HI, _Palette.GREEN_OFF

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), _Palette.BG)

        seg_h, seg_gap, seg_w, x_off = self._geometry()
        active = self._amp_to_segs(self._level)
        top_anchor = float(self.CLIP_BAR_H + self.CLIP_GAP)

        for i in range(self.SEGMENTS - 1, -1, -1):
            # i = SEGMENTS-1 is topmost, i = 0 is bottommost
            slot = self.SEGMENTS - 1 - i          # 0 = top slot
            y = top_anchor + slot * (seg_h + seg_gap)
            rect = QRectF(x_off, y, seg_w, seg_h)

            lit = i < active
            is_peak = (i == self._peak_seg and not lit)
            base_c, hi_c, unlit_c = self._seg_colors(i)

            if is_peak:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(_Palette.PEAK)
                p.drawRoundedRect(rect, self.RADIUS, self.RADIUS)
            elif lit:
                # Base colour
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(base_c)
                p.drawRoundedRect(rect, self.RADIUS, self.RADIUS)
                # Subtle vertical highlight in top 40% of segment
                hi_h = seg_h * 0.40
                hi_rect = QRectF(x_off + 1, y + 1, seg_w - 2, hi_h)
                grad = QLinearGradient(hi_rect.topLeft(), hi_rect.bottomLeft())
                hi_alpha = QColor(hi_c)
                hi_alpha.setAlpha(110)
                transparent = QColor(hi_c)
                transparent.setAlpha(0)
                grad.setColorAt(0.0, hi_alpha)
                grad.setColorAt(1.0, transparent)
                p.setBrush(grad)
                p.drawRoundedRect(hi_rect, self.RADIUS * 0.5, self.RADIUS * 0.5)
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(unlit_c)
                p.drawRoundedRect(rect, self.RADIUS, self.RADIUS)

        # Clip indicator bar
        clip_rect = QRectF(x_off, 0, seg_w, self.CLIP_BAR_H)
        p.setBrush(_Palette.CLIP_ON if self._clipping else _Palette.CLIP_OFF)
        p.drawRoundedRect(clip_rect, 1.0, 1.0)


# ---------------------------------------------------------------------------
# Stereo pair — resizable
# ---------------------------------------------------------------------------

class StereoMeter(QWidget):
    """L + R LED meter pair. Expands to fill available space."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
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
