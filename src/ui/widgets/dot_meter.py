"""
STEAMING STREAM — Round Dot-Matrix LED Meter
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

Round dot version of the LED bar meter. Same auto-orient logic as StereoMeter:
  width > height × 1.4  →  dots run left→right (horizontal)
  otherwise             →  dots run bottom→top (vertical)
"""

import math

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QColor, QPainter, QFont, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget


_SEGMENTS   = 20
_YELLOW_SEG = 14
_RED_SEG    = 17
_PEAK_HOLD  = 90
_CLIP_H     = 5.0
_CLIP_GAP   = 2.0
_GAP_RATIO  = 0.28

_COLOURS = {
    "green":  (QColor(  0, 220,  40), QColor(  0,  38,   8)),
    "yellow": (QColor(240, 200,   0), QColor( 46,  36,   0)),
    "red":    (QColor(255,  55,  25), QColor( 50,   8,   4)),
}
_PEAK_C  = QColor(255, 255, 185)
_CLIP_ON = QColor(255,  20,  20)
_CLIP_OFF= QColor( 45,   0,   0)
_BG      = QColor( 14,  14,  14)
_DB_TXT  = QColor( 80,  80,  80)
_SCALE_G = QColor( 80, 160,  80)
_SCALE_Y = QColor(220, 190,   0)
_SCALE_R = QColor(255,  80,  60)

_DB_TICKS = (0, -3, -6, -9, -12, -18, -24, -30, -40)


class DotChannel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._level      = 0.0
        self._peak_seg   = -1
        self._peak_cnt   = 0
        self._clipping   = False
        self._orientation= 'vertical'
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(6, 6)

    def set_orientation(self, o):
        if o != self._orientation:
            self._orientation = o; self.update()

    def set_level(self, level):
        self._level    = max(0.0, min(1.05, level))
        self._clipping = self._level >= 1.0
        active = self._amp_to_segs(self._level)
        if active > self._peak_seg:
            self._peak_seg = active; self._peak_cnt = _PEAK_HOLD
        elif self._peak_cnt > 0:
            self._peak_cnt -= 1
        elif self._peak_seg > active:
            self._peak_seg -= 1
        self.update()

    def reset(self):
        self._level = 0.0; self._peak_seg = -1; self._peak_cnt = 0
        self._clipping = False; self.update()

    @staticmethod
    def _amp_to_segs(amp):
        if amp <= 0: return 0
        db = 20.0 * math.log10(max(amp, 1e-9))
        return int((max(-40.0, min(0.0, db)) + 40.0) / 40.0 * _SEGMENTS)

    @staticmethod
    def _zone(i):
        if i >= _RED_SEG:    return _COLOURS["red"]
        if i >= _YELLOW_SEG: return _COLOURS["yellow"]
        return _COLOURS["green"]

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), _BG)
        if self._orientation == 'horizontal':
            self._paint_h(p)
        else:
            self._paint_v(p)

    def _paint_v(self, p):
        w, h = float(self.width()), float(self.height())
        cx   = w / 2.0
        usable = h - _CLIP_H - _CLIP_GAP
        denom  = _SEGMENTS + (_SEGMENTS - 1) * _GAP_RATIO
        dot_d  = max(3.0, usable / denom)
        gap    = dot_d * _GAP_RATIO
        dot_r  = min(dot_d / 2.0, (w - 4.0) / 2.0)
        active = self._amp_to_segs(self._level)

        for i in range(_SEGMENTS - 1, -1, -1):
            slot = _SEGMENTS - 1 - i
            yc   = _CLIP_H + _CLIP_GAP + slot * (dot_d + gap) + dot_d / 2.0
            lc, uc = self._zone(i)
            is_pk  = (i == self._peak_seg and i >= active)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_PEAK_C if is_pk else (lc if i < active else uc))
            p.drawEllipse(QPointF(cx, yc), dot_r, dot_r)

        cr = min(dot_r, w / 2.0 - 1.0)
        p.setBrush(_CLIP_ON if self._clipping else _CLIP_OFF)
        p.drawRoundedRect(QRectF(cx - cr, 0.0, cr*2.0, _CLIP_H), 1.5, 1.5)

    def _paint_h(self, p):
        w, h = float(self.width()), float(self.height())
        cy   = h / 2.0
        usable = w - _CLIP_H - _CLIP_GAP
        denom  = _SEGMENTS + (_SEGMENTS - 1) * _GAP_RATIO
        dot_d  = max(3.0, usable / denom)
        gap    = dot_d * _GAP_RATIO
        dot_r  = min(dot_d / 2.0, (h - 4.0) / 2.0)
        active = self._amp_to_segs(self._level)

        for i in range(_SEGMENTS):
            xc = i * (dot_d + gap) + dot_d / 2.0
            lc, uc = self._zone(i)
            is_pk  = (i == self._peak_seg and i >= active)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_PEAK_C if is_pk else (lc if i < active else uc))
            p.drawEllipse(QPointF(xc, cy), dot_r, dot_r)

        cr = min(dot_r, h / 2.0 - 1.0)
        p.setBrush(_CLIP_ON if self._clipping else _CLIP_OFF)
        p.drawRoundedRect(QRectF(w - _CLIP_H, cy - cr, _CLIP_H, cr*2.0), 1.5, 1.5)

        # Scale ticks in horizontal mode
        font = QFont("Consolas"); font.setPointSize(6)
        p.setFont(font)
        for db in _DB_TICKS:
            frac  = (db + 40.0) / 40.0
            xpos  = frac * _SEGMENTS * (dot_d + gap)
            c     = _SCALE_R if db >= -3 else (_SCALE_Y if db >= -9 else _SCALE_G)
            p.setPen(QPen(c, 0.8))
            p.drawLine(int(xpos), int(cy - dot_r), int(xpos), int(cy - dot_r * 0.5))
            p.drawText(
                QRectF(xpos - 14.0, cy + dot_r + 0.5, 28.0, 10.0),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                "0" if db == 0 else str(db),
            )


class StereoDotMeter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._orientation = 'vertical'
        self.left  = DotChannel(self)
        self.right = DotChannel(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        new_o = 'horizontal' if w > h * 1.4 else 'vertical'
        if new_o != self._orientation:
            self._orientation = new_o
            self.left.set_orientation(new_o)
            self.right.set_orientation(new_o)
        self._do_layout()

    def _do_layout(self):
        w, h, sp = self.width(), self.height(), 3
        if self._orientation == 'vertical':
            cw = max(6, (w - sp) // 2)
            self.left.setGeometry(0, 0, cw, h)
            self.right.setGeometry(cw + sp, 0, max(6, w - cw - sp), h)
        else:
            ch = max(4, (h - sp) // 2)
            self.left.setGeometry(0, 0, w, ch)
            self.right.setGeometry(0, ch + sp, w, max(4, h - ch - sp))

    def set_orientation(self, o):
        if o != self._orientation:
            self._orientation = o
            self.left.set_orientation(o); self.right.set_orientation(o)
            self._do_layout()

    def set_levels(self, l, r): self.left.set_level(l); self.right.set_level(r)
    def set_level(self, v): self.left.set_level(v); self.right.set_level(v)
    def reset(self): self.left.reset(); self.right.reset()
