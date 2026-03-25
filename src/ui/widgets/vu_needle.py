"""
STEAMING STREAM — Analog VU Needle Meter
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

Realistic TEAC-style face:
  • Labels above the arc, ticks hang inward from the arc
  • Filled red zone band (from "0" to "+") on the right
  • Thin dark arc line over the full sweep
  • PEAK LED inside the face, lower-right, with "PEAK" label
  • "VU" text centred, well clear of the needle hinge

Physics: underdamped spring-damper (omega=12 rad/s, zeta=0.45) gives
fast response with natural needle bounce.  3× more responsive than
IEC 60268-17 τ=300 ms spec.

Auto-layout in StereoVUMeter: aspect-ratio driven (portrait → stacked,
landscape → side-by-side).
"""

import math
import time

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QFont,
    QLinearGradient, QRadialGradient, QPainterPath,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget


# ---------------------------------------------------------------------------
# Physics
# ---------------------------------------------------------------------------

_VU_OMEGA = 12.0   # natural frequency rad/s — fast response
_VU_ZETA  = 0.45   # damping ratio  < 1 = under-damped / bouncy

# Scale range (dBFS)
_MIN_DB  = -40.0
_MAX_DB  =   0.0
_MIN_DEG = -65.0   # needle angle at _MIN_DB (degrees CW from vertical)
_MAX_DEG =  65.0   # needle angle at _MAX_DB

# Red zone starts at this fraction of the full sweep (~-5 dBFS = "0 VU")
_RED_FRAC = 0.875

# VU-scale tick table: (fraction 0..1, label, is_major, is_red)
# fraction → angle = MIN_DEG + frac*(MAX_DEG - MIN_DEG)
# dBFS    → frac  = (db - MIN_DB) / (MAX_DB - MIN_DB)
_TICKS_VU = [
    (0.000, "20",  True,  False),
    (0.050, "",    False, False),
    (0.150, "",    False, False),
    (0.250, "",    False, False),
    (0.375, "10",  True,  False),
    (0.500, "7",   True,  False),
    (0.600, "5",   True,  False),
    (0.700, "3",   True,  False),
    (0.770, "",    False, False),
    (0.830, "",    False, False),
    (0.875, "0",   True,  True),    # red zone starts
    (0.910, "",    False, True),
    (0.950, "",    False, True),
    (1.000, "+",   True,  True),
]

# Colours
_FACE_BG     = QColor(230, 222, 192)
_FACE_BG2    = QColor(210, 202, 172)
_FRAME_OUTER = QColor( 28,  24,  18)
_FRAME_MID   = QColor( 58,  50,  38)
_FRAME_INNER = QColor( 78,  68,  52)
_ARC_C       = QColor( 30,  26,  20)
_RED_ZONE_C  = QColor(175,  18,   4)
_TICK_DARK   = QColor( 28,  24,  18)
_LABEL_DARK  = QColor( 28,  24,  18)
_LABEL_RED   = QColor(160,  12,   2)
_NEEDLE_C    = QColor( 18,  16,  12)
_PIVOT_C     = QColor( 48,  40,  30)
_VU_TEXT_C   = QColor( 42,  36,  28)
_LED_OFF     = QColor( 48,  14,  14)
_LED_ON      = QColor(255,  28,  12)
_WIDGET_BG   = QColor( 14,  14,  14)
_PEAK_TEXT_C = QColor( 80,  70,  55)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _frac_to_angle(frac: float) -> float:
    """Fraction [0,1] → needle degrees (0=vertical, CW+)."""
    return _MIN_DEG + frac * (_MAX_DEG - _MIN_DEG)


def _db_to_angle(db: float) -> float:
    frac = (max(_MIN_DB, min(_MAX_DB, db)) - _MIN_DB) / (_MAX_DB - _MIN_DB)
    return _frac_to_angle(frac)


def _polar(angle_deg: float, px: float, py: float, r: float) -> QPointF:
    """Polar (CW from vertical) → Cartesian QPointF."""
    rad = math.radians(angle_deg)
    return QPointF(px + r * math.sin(rad), py - r * math.cos(rad))


def _arc_band_path(px: float, py: float, r_out: float, r_in: float,
                   a_start: float, a_end: float) -> QPainterPath:
    """Filled annular sector. Angles CW from vertical, degrees."""
    qt_start = 90.0 - a_start               # Qt: 0=3 o'clock, CCW+
    qt_span  = -(a_end - a_start)            # CW = negative

    outer = QRectF(px - r_out, py - r_out, 2*r_out, 2*r_out)
    inner = QRectF(px - r_in,  py - r_in,  2*r_in,  2*r_in)

    path = QPainterPath()
    path.moveTo(_polar(a_start, px, py, r_out))
    path.arcTo(outer, qt_start, qt_span)
    path.lineTo(_polar(a_end, px, py, r_in))
    path.arcTo(inner, qt_start + qt_span, -qt_span)
    path.closeSubpath()
    return path


# ---------------------------------------------------------------------------
# Single channel
# ---------------------------------------------------------------------------

class VUNeedleChannel(QWidget):
    """One TEAC-style analog VU needle face."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle     = _MIN_DEG    # current needle position (degrees)
        self._vel       = 0.0         # angular velocity (deg/s)
        self._last_t    = time.monotonic()
        self._clipping  = False
        self._peak_hold = 0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(60, 50)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_level(self, level: float) -> None:
        now = time.monotonic()
        dt  = min(now - self._last_t, 0.05)
        self._last_t = now

        level = max(0.0, min(1.05, level))

        # Peak LED hold
        if level >= 1.0:
            self._clipping  = True
            self._peak_hold = 45
        elif self._peak_hold > 0:
            self._peak_hold -= 1
        else:
            self._clipping = False

        # Target angle from input level
        target = (
            _MIN_DEG if level <= 1e-9
            else _db_to_angle(max(_MIN_DB, min(_MAX_DB, 20.0 * math.log10(level))))
        )

        # Underdamped spring-damper physics → overshoot + bounce
        accel = (-_VU_OMEGA**2 * (self._angle - target)
                 - 2.0 * _VU_ZETA * _VU_OMEGA * self._vel)
        self._vel   += accel * dt
        self._angle += self._vel * dt
        # Allow a little overshoot but prevent runaway
        self._angle = max(_MIN_DEG - 10.0, min(_MAX_DEG + 10.0, self._angle))
        self.update()

    def reset(self) -> None:
        self._angle     = _MIN_DEG
        self._vel       = 0.0
        self._last_t    = time.monotonic()
        self._clipping  = False
        self._peak_hold = 0
        self.update()

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _geo(self):
        """Return (face_rect, px, py, r, pl_x, pl_y, pl_r)."""
        w = float(self.width())
        h = float(self.height())

        fm = 3.0
        face_rect = QRectF(fm, fm, w - 2*fm, h - 2*fm)
        fw = face_rect.width()
        fh = face_rect.height()

        px = face_rect.left() + fw / 2.0
        py = face_rect.top()  + fh * 0.90   # pivot near bottom of face

        # Radius: enough room above for arc + labels
        sin65    = math.sin(math.radians(65.0))
        lbl_h    = max(10.0, fh * 0.14)     # vertical space reserved for labels above arc
        r_w      = (fw / 2.0 - 8.0) / sin65
        r_h      = py - face_rect.top() - lbl_h - 4.0
        r        = max(18.0, min(r_w, r_h))

        # PEAK LED: lower-right inside face, near the "+3VU" position
        pl_r = max(4.5, min(8.5, r * 0.068))
        pl_x = min(face_rect.right() - pl_r - 8.0, px + r * 0.80)
        pl_y = py - pl_r * 0.8

        return face_rect, px, py, r, pl_x, pl_y, pl_r

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), _WIDGET_BG)

        face_rect, px, py, r, pl_x, pl_y, pl_r = self._geo()

        # ── Housing (multi-layer dark bevel) ─────────────────────────────
        bp = QPainterPath(); bp.addRoundedRect(face_rect, 6.0, 6.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_FRAME_OUTER); p.drawPath(bp)

        b1 = face_rect.adjusted(1.5, 1.5, -1.5, -1.5)
        b2 = face_rect.adjusted(3.0, 3.0, -3.0, -3.0)
        b1p = QPainterPath(); b1p.addRoundedRect(b1, 5.0, 5.0)
        b2p = QPainterPath(); b2p.addRoundedRect(b2, 4.0, 4.0)
        p.setBrush(_FRAME_MID);   p.drawPath(b1p)
        p.setBrush(_FRAME_INNER); p.drawPath(b2p)

        # ── Cream face ────────────────────────────────────────────────────
        inner = face_rect.adjusted(4.0, 4.0, -4.0, -4.0)
        fg = QLinearGradient(inner.topLeft(), inner.bottomLeft())
        fg.setColorAt(0.0, _FACE_BG); fg.setColorAt(1.0, _FACE_BG2)
        ip = QPainterPath(); ip.addRoundedRect(inner, 3.5, 3.5)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(fg); p.drawPath(ip)

        # Subtle edge highlight
        p.setPen(QPen(QColor(255, 250, 235, 60), 0.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(inner.left() + 8.0, inner.top() + 1.5),
                   QPointF(inner.right() - 8.0, inner.top() + 1.5))

        # ── Arc band ─────────────────────────────────────────────────────
        arc_w   = max(4.0, r * 0.085)   # band thickness
        r_out   = r + arc_w * 0.5
        r_in    = r - arc_w * 0.5
        red_ang = _frac_to_angle(_RED_FRAC)   # angle where red starts

        # Filled red zone
        red_path = _arc_band_path(px, py, r_out, r_in, red_ang, _MAX_DEG)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_RED_ZONE_C)
        p.drawPath(red_path)

        # Thin dark arc line over the entire sweep
        arc_rect = QRectF(px - r, py - r, 2*r, 2*r)
        qt_s = int((90.0 - _MIN_DEG) * 16)
        qt_n = int(-(_MAX_DEG - _MIN_DEG) * 16)
        ap = QPen(_ARC_C); ap.setWidthF(max(0.7, r * 0.008))
        p.setPen(ap); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(arc_rect, qt_s, qt_n)

        # ── Ticks and labels ─────────────────────────────────────────────
        fsize = max(5.0, r * 0.083)

        for frac, lbl, is_major, is_red in _TICKS_VU:
            ang     = _frac_to_angle(frac)
            t_top   = _polar(ang, px, py, r_in)                        # at inner arc edge
            tlen    = r * (0.13 if is_major else 0.076)
            t_bot   = _polar(ang, px, py, r_in - tlen)                 # hangs inward

            # All ticks dark on cream background (classic VU look)
            tp = QPen(_TICK_DARK); tp.setWidthF(1.2 if is_major else 0.75)
            p.setPen(tp)
            p.drawLine(t_top, t_bot)

            if lbl:
                # Labels above (outside) the arc
                lp    = _polar(ang, px, py, r_out + max(3.0, r * 0.035))
                lf    = QFont("Consolas")
                lf.setPointSizeF(fsize * (1.12 if is_major else 1.0))
                lf.setBold(is_major and is_red)
                p.setFont(lf)
                p.setPen(_LABEL_RED if is_red else _LABEL_DARK)
                tr = QRectF(lp.x() - 18.0, lp.y() - 8.0, 36.0, 16.0)
                p.drawText(tr,
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, lbl)

        # ── "VU" legend — centred, well clear of needle hinge ────────────
        vu_fsize = max(7.0, r * 0.14)
        vuf = QFont("Georgia"); vuf.setPointSizeF(vu_fsize); vuf.setBold(True)
        p.setFont(vuf); p.setPen(_VU_TEXT_C)
        # Place at 42% of the way from pivot toward arc
        vu_cy  = py - r * 0.42
        vu_r   = QRectF(px - 32.0, vu_cy - vu_fsize * 0.8, 64.0, vu_fsize * 1.8)
        p.drawText(vu_r,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, "VU")

        # ── PEAK LED (inside face, lower right) ───────────────────────────
        if self._clipping:
            glow = QRadialGradient(pl_x, pl_y, pl_r * 2.4)
            glow.setColorAt(0.0, QColor(255, 80, 50, 105))
            glow.setColorAt(1.0, QColor(255,  0,  0,   0))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(glow)
            p.drawEllipse(QPointF(pl_x, pl_y), pl_r * 2.4, pl_r * 2.4)

        lg = QRadialGradient(pl_x - pl_r*0.35, pl_y - pl_r*0.38, pl_r * 0.7)
        if self._clipping:
            lg.setColorAt(0.0, QColor(255, 175, 140))
            lg.setColorAt(0.5, QColor(255,  65,  35))
            lg.setColorAt(1.0, _LED_ON)
        else:
            lg.setColorAt(0.0, QColor( 85,  24,  24))
            lg.setColorAt(1.0, _LED_OFF)

        p.setPen(QPen(QColor(12, 5, 5), 0.7))
        p.setBrush(lg)
        p.drawEllipse(QPointF(pl_x, pl_y), pl_r, pl_r)

        # "PEAK" caption below LED
        pkf = QFont("Consolas"); pkf.setPointSizeF(max(4.0, pl_r * 0.85))
        p.setFont(pkf); p.setPen(_PEAK_TEXT_C)
        p.drawText(
            QRectF(pl_x - 16.0, pl_y + pl_r + 1.0, 32.0, 10.0),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "PEAK",
        )

        # ── Needle ────────────────────────────────────────────────────────
        tip  = _polar(self._angle, px, py, r * 0.88)
        tail = _polar(self._angle + 180.0, px, py, r * 0.14)

        shad = QPen(QColor(0, 0, 0, 48))
        shad.setWidthF(max(1.5, r * 0.016)); shad.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(shad)
        off = QPointF(0.7, 0.7)
        p.drawLine(tail + off, tip + off)

        np_ = QPen(_NEEDLE_C)
        np_.setWidthF(max(1.0, r * 0.012)); np_.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(np_); p.drawLine(tail, tip)

        # Pivot cap
        pvr = max(2.5, r * 0.042)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawEllipse(QPointF(px + 0.6, py + 0.6), pvr, pvr)
        pvg = QRadialGradient(px - pvr*0.3, py - pvr*0.35, pvr * 0.6)
        pvg.setColorAt(0.0, QColor(138, 124, 100)); pvg.setColorAt(1.0, _PIVOT_C)
        p.setBrush(pvg)
        p.drawEllipse(QPointF(px, py), pvr, pvr)


# ---------------------------------------------------------------------------
# Stereo pair — aspect-ratio auto-layout
# ---------------------------------------------------------------------------

class StereoVUMeter(QWidget):
    """L + R VU meters. Portrait (h ≥ 1.1w) → stacked; landscape → side-by-side."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.left  = VUNeedleChannel(self)
        self.right = VUNeedleChannel(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._do_layout()

    def _do_layout(self):
        w, h, g = self.width(), self.height(), 3
        if h >= w * 1.1:
            ch = max(1, (h - g) // 2)
            self.left.setGeometry(0, 0, w, ch)
            self.right.setGeometry(0, ch + g, w, max(1, h - ch - g))
        else:
            cw = max(1, (w - g) // 2)
            self.left.setGeometry(0, 0, cw, h)
            self.right.setGeometry(cw + g, 0, max(1, w - cw - g), h)

    def set_orientation(self, _orientation: str) -> None:
        pass   # layout is aspect-ratio driven

    def set_levels(self, left: float, right: float) -> None:
        self.left.set_level(left)
        self.right.set_level(right)

    def set_level(self, level: float) -> None:
        self.left.set_level(level)
        self.right.set_level(level)

    def reset(self) -> None:
        self.left.reset()
        self.right.reset()
