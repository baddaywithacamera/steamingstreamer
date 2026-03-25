"""
STEAMING STREAM — LED VU Meter Widget
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

Segmented LED bar meter. Fills all available space with no dead gaps.

Segment layout (20 segments):
  0–13  green   (-40 to -9 dBFS)
  14–16 yellow  ( -9 to -3 dBFS)
  17–19 red     ( -3 to  0 dBFS)

StereoMeter auto-detects orientation from its own aspect ratio:
  width > height × 1.4  →  'horizontal' (bars run left→right, quiet left)
  otherwise             →  'vertical'   (bars run bottom→top, scale on right)

The dBFS scale ruler (_DBScale) is always shown in vertical mode.
In horizontal mode, static dB tick marks are drawn inside each bar.
"""

import math

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QLinearGradient, QFont, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

class _P:
    GREEN        = QColor(0,   220,  30)
    GREEN_HI     = QColor(80,  255, 100)
    YELLOW       = QColor(255, 210,   0)
    YELLOW_HI    = QColor(255, 245, 120)
    RED          = QColor(255,  50,  20)
    RED_HI       = QColor(255, 140,  80)
    GREEN_OFF    = QColor(0,   38,    8)
    YELLOW_OFF   = QColor(46,  36,    0)
    RED_OFF      = QColor(50,   8,    4)
    PEAK         = QColor(255, 255, 180)
    CLIP_ON      = QColor(255,  20,  20)
    CLIP_OFF     = QColor(45,    0,   0)
    BG           = QColor(14,   14,  14)
    DB_TEXT      = QColor(90,   90,  90)
    SCALE_TEXT_G = QColor( 80, 160,  80)
    SCALE_TEXT_Y = QColor(220, 190,   0)
    SCALE_TEXT_R = QColor(255,  80,  60)


# ---------------------------------------------------------------------------
# Single LED bar — orientation-aware
# ---------------------------------------------------------------------------

class LEDChannel(QWidget):
    """One LED bar. Orientation switches between 'vertical' and 'horizontal'."""

    SEGMENTS     = 20
    PEAK_HOLD    = 90     # ticks (~3 s at 30 fps)
    MIN_SEG_H    = 2      # minimum segment size in px (reduced to avoid gaps)
    CLIP_BAR_H   = 5      # clip indicator thickness
    CLIP_GAP     = 2
    GAP_RATIO    = 0.22
    RADIUS       = 1.5

    _YELLOW_FLOOR = 14
    _RED_FLOOR    = 17

    def __init__(self, parent=None):
        super().__init__(parent)
        self._level       = 0.0
        self._peak_seg    = -1
        self._peak_cnt    = 0
        self._clipping    = False
        self._db_val      = -40.0
        self._orientation = 'vertical'
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(6, 6)

    def set_orientation(self, o: str) -> None:
        if o != self._orientation:
            self._orientation = o
            self.update()

    def set_level(self, level: float) -> None:
        self._level    = max(0.0, min(1.05, level))
        self._clipping = self._level >= 1.0
        self._db_val   = (
            -40.0 if self._level <= 1e-9
            else max(-40.0, min(0.0, 20.0 * math.log10(self._level)))
        )
        active = self._amp_to_segs(self._level)
        if active > self._peak_seg:
            self._peak_seg = active; self._peak_cnt = self.PEAK_HOLD
        elif self._peak_cnt > 0:
            self._peak_cnt -= 1
        elif self._peak_seg > active:
            self._peak_seg -= 1
        self.update()

    def reset(self) -> None:
        self._level = 0.0; self._peak_seg = -1; self._peak_cnt = 0
        self._clipping = False; self._db_val = -40.0; self.update()

    def _amp_to_segs(self, amp):
        if amp <= 0: return 0
        db = 20.0 * math.log10(max(amp, 1e-9))
        return int((max(-40.0, min(0.0, db)) + 40.0) / 40.0 * self.SEGMENTS)

    def _seg_colors(self, i):
        if i >= self._RED_FLOOR:    return _P.RED,    _P.RED_HI,    _P.RED_OFF
        if i >= self._YELLOW_FLOOR: return _P.YELLOW, _P.YELLOW_HI, _P.YELLOW_OFF
        return _P.GREEN, _P.GREEN_HI, _P.GREEN_OFF

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), _P.BG)
        if self._orientation == 'horizontal':
            self._paint_h(p)
        else:
            self._paint_v(p)

    # ── Vertical ──────────────────────────────────────────────────────

    def _paint_v(self, p: QPainter) -> None:
        h  = self.height()
        w  = self.width()
        n  = self.SEGMENTS
        cb = self.CLIP_BAR_H
        cg = self.CLIP_GAP

        usable = h - cb - cg
        denom  = n + (n - 1) * self.GAP_RATIO
        seg_h  = max(float(self.MIN_SEG_H), usable / denom)
        seg_g  = seg_h * self.GAP_RATIO
        seg_w  = max(4.0, float(w - 4))
        x_off  = (w - seg_w) / 2.0
        top    = float(cb + cg)
        active = self._amp_to_segs(self._level)

        for i in range(n - 1, -1, -1):
            slot = n - 1 - i
            y    = top + slot * (seg_h + seg_g)
            rect = QRectF(x_off, y, seg_w, seg_h)
            self._draw_seg(p, rect, i, active, horizontal=False)

        # Clip bar
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_P.CLIP_ON if self._clipping else _P.CLIP_OFF)
        p.drawRoundedRect(QRectF(x_off, 0, seg_w, cb), 1.0, 1.0)

    # ── Horizontal ────────────────────────────────────────────────────

    def _paint_h(self, p: QPainter) -> None:
        w  = self.width()
        h  = self.height()
        n  = self.SEGMENTS
        cb = self.CLIP_BAR_H
        cg = self.CLIP_GAP

        usable = w - cb - cg
        denom  = n + (n - 1) * self.GAP_RATIO
        seg_w  = max(float(self.MIN_SEG_H), usable / denom)
        seg_g  = seg_w * self.GAP_RATIO
        seg_h  = max(4.0, float(h - 4))
        y_off  = (h - seg_h) / 2.0
        active = self._amp_to_segs(self._level)

        for i in range(n):
            x    = i * (seg_w + seg_g)
            rect = QRectF(x, y_off, seg_w, seg_h)
            self._draw_seg(p, rect, i, active, horizontal=True)

        # Clip bar on right
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_P.CLIP_ON if self._clipping else _P.CLIP_OFF)
        p.drawRoundedRect(QRectF(w - cb, 0, cb, h), 1.0, 1.0)

        # dB tick marks overlaid in horizontal mode (static scale)
        self._paint_h_scale(p, usable, n, seg_w, seg_g, y_off, seg_h)

    def _paint_h_scale(self, p, usable, n, seg_w, seg_g, y_off, seg_h) -> None:
        """Draw static dB scale ticks inside the horizontal bar."""
        _DB_TICKS = (0, -3, -6, -9, -12, -18, -24, -30, -40)
        font = QFont("Consolas"); font.setPointSize(6)
        p.setFont(font)
        for db in _DB_TICKS:
            frac   = (db + 40.0) / 40.0              # 0=left, 1=right
            seg_f  = frac * n                         # fractional segment index
            x_pos  = seg_f * (seg_w + seg_g)
            colour = (
                _P.SCALE_TEXT_R if db >= -3 else
                _P.SCALE_TEXT_Y if db >= -9 else
                _P.SCALE_TEXT_G
            )
            p.setPen(QPen(colour, 0.8))
            p.drawLine(
                int(x_pos), int(y_off),
                int(x_pos), int(y_off + seg_h * 0.40)
            )
            label = "0" if db == 0 else str(db)
            p.drawText(
                QRectF(x_pos - 16.0, y_off + seg_h * 0.42, 32.0, seg_h * 0.50),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                label,
            )

    # ── Segment drawing (shared) ─────────────────────────────────────

    def _draw_seg(self, p, rect, i, active, horizontal=False) -> None:
        lit    = i < active
        is_pk  = (i == self._peak_seg and not lit)
        bc, hc, uc = self._seg_colors(i)

        p.setPen(Qt.PenStyle.NoPen)
        if is_pk:
            p.setBrush(_P.PEAK)
            p.drawRoundedRect(rect, self.RADIUS, self.RADIUS)
        elif lit:
            p.setBrush(bc)
            p.drawRoundedRect(rect, self.RADIUS, self.RADIUS)
            # Subtle highlight
            if horizontal:
                hi_r = QRectF(rect.x() + 1, rect.y() + 1,
                               rect.width() * 0.40, rect.height() - 2)
                grad = QLinearGradient(hi_r.topLeft(), hi_r.topRight())
            else:
                hi_r = QRectF(rect.x() + 1, rect.y() + 1,
                               rect.width() - 2, rect.height() * 0.40)
                grad = QLinearGradient(hi_r.topLeft(), hi_r.bottomLeft())
            ha = QColor(hc); ha.setAlpha(110)
            ht = QColor(hc); ht.setAlpha(0)
            grad.setColorAt(0.0, ha); grad.setColorAt(1.0, ht)
            p.setBrush(grad)
            p.drawRoundedRect(hi_r, self.RADIUS * 0.5, self.RADIUS * 0.5)
        else:
            p.setBrush(uc)
            p.drawRoundedRect(rect, self.RADIUS, self.RADIUS)


# ---------------------------------------------------------------------------
# dBFS scale ruler (vertical mode only)
# ---------------------------------------------------------------------------

_DB_TICKS = (0, -3, -6, -9, -12, -18, -24, -30, -40)


class _DBScale(QWidget):
    """Fixed-position vertical dBFS ruler that aligns with LEDChannel segments."""

    SEGMENTS   = LEDChannel.SEGMENTS
    CLIP_BAR_H = LEDChannel.CLIP_BAR_H
    CLIP_GAP   = LEDChannel.CLIP_GAP
    GAP_RATIO  = LEDChannel.GAP_RATIO
    MIN_SEG_H  = LEDChannel.MIN_SEG_H
    WIDTH      = 32   # px

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(40)

    def _bar_geo(self):
        h      = self.height()
        usable = h - self.CLIP_BAR_H - self.CLIP_GAP
        n      = self.SEGMENTS
        denom  = n + (n - 1) * self.GAP_RATIO
        seg_h  = max(float(self.MIN_SEG_H), usable / denom)
        seg_g  = seg_h * self.GAP_RATIO
        top    = float(self.CLIP_BAR_H + self.CLIP_GAP)
        return seg_h, seg_g, top

    def _db_to_y(self, db, seg_h, seg_g, top):
        bar_h = self.SEGMENTS * seg_h + (self.SEGMENTS - 1) * seg_g
        norm  = max(0.0, min(1.0, (db + 40.0) / 40.0))
        return top + (1.0 - norm) * bar_h

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.fillRect(self.rect(), _P.BG)

        seg_h, seg_g, top = self._bar_geo()
        font = QFont("Consolas"); font.setPointSize(8)
        p.setFont(font)
        tw   = self.WIDTH - 5
        tk_w = 4

        for db in _DB_TICKS:
            y  = self._db_to_y(float(db), seg_h, seg_g, top)
            c  = (
                _P.SCALE_TEXT_R if db >= -3 else
                _P.SCALE_TEXT_Y if db >= -9 else
                _P.SCALE_TEXT_G
            )
            p.setPen(c)
            iy = int(y)
            p.drawLine(self.WIDTH - tk_w, iy, self.WIDTH - 1, iy)
            label = "0" if db == 0 else str(db)
            p.drawText(
                QRectF(0, y - 7.0, tw, 14.0),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )


# ---------------------------------------------------------------------------
# Stereo pair — aspect-ratio auto-orient, zero dead space
# ---------------------------------------------------------------------------

class StereoMeter(QWidget):
    """L + R LED bars with dBFS scale.
    Auto-detects orientation from aspect ratio — no external call needed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._orientation = 'vertical'
        # Children positioned via resizeEvent (no layout manager)
        self.left   = LEDChannel(self)
        self.right  = LEDChannel(self)
        self._scale = _DBScale(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        # Auto-detect: wide → horizontal, tall/square → vertical
        new_o = 'horizontal' if w > h * 1.4 else 'vertical'
        if new_o != self._orientation:
            self._orientation = new_o
            self.left.set_orientation(new_o)
            self.right.set_orientation(new_o)
        self._do_layout()

    def _do_layout(self):
        w, h = self.width(), self.height()
        sp   = 3   # gap between bars

        if self._orientation == 'vertical':
            sw  = _DBScale.WIDTH
            bw  = max(6, (w - sp - sw) // 2)
            bh  = h
            self.left.setGeometry(0, 0, bw, bh)
            self.right.setGeometry(bw + sp, 0, bw, bh)
            self._scale.setGeometry(2*bw + sp + sp, 0, sw, bh)
            self._scale.show()
        else:
            self._scale.hide()
            bw = w
            bh = max(4, (h - sp) // 2)
            self.left.setGeometry(0, 0, bw, bh)
            self.right.setGeometry(0, bh + sp, bw, max(4, h - bh - sp))

    def set_orientation(self, orientation: str) -> None:
        """External hint — will be confirmed/overridden on next resize."""
        if orientation != self._orientation:
            self._orientation = orientation
            self.left.set_orientation(orientation)
            self.right.set_orientation(orientation)
            self._do_layout()

    def set_levels(self, left: float, right: float) -> None:
        self.left.set_level(left)
        self.right.set_level(right)

    def set_level(self, level: float) -> None:
        self.left.set_level(level)
        self.right.set_level(level)

    def reset(self) -> None:
        self.left.reset()
        self.right.reset()
