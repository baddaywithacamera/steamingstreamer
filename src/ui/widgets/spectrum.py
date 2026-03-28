"""
spectrum.py — Real-time FFT spectrum analyzer widget
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

Displays L and R channels side-by-side as filled bars on a log-frequency
scale (20 Hz – 20 kHz).  Feed it raw int16 PCM via set_pcm().

Layout (combined=False):
  ┌──────────────┬──────────────┐
  │      L       │      R       │
  │  (bars)      │  (bars)      │
  └──────────────┴──────────────┘

Layout (combined=True):
  ┌──────────────────────────────┐
  │          L+R sum             │
  │          (bars)              │
  └──────────────────────────────┘
"""

from __future__ import annotations
import math
from typing import Optional

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QWidget

try:
    import numpy as np
    _NUMPY = True
except ImportError:
    _NUMPY = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FFT_SIZE   = 2048          # points — ~21 Hz/bin at 44.1 kHz
_NUM_BARS   = 64            # display bars per channel
_F_MIN      = 20.0          # Hz
_F_MAX      = 20_000.0      # Hz
_DECAY      = 0.15          # fraction to decay per frame (0 = instant, 1 = hold forever)
_PEAK_HOLD  = 45            # frames before peak starts falling
_PEAK_DECAY = 0.04

# Pre-compute log-spaced frequency bin edges once
_LOG_EDGES: list[float] = [
    _F_MIN * (_F_MAX / _F_MIN) ** (i / _NUM_BARS)
    for i in range(_NUM_BARS + 1)
]

# Bar gradient colours (bottom → top)
_BAR_BOTTOM = QColor("#00cc44")
_BAR_MID    = QColor("#aacc00")
_BAR_TOP    = QColor("#ff3300")

_DIVIDER    = QColor("#303030")
_LABEL_CLR  = QColor("#666666")
_BG         = QColor("#111111")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _freq_to_bin(freq: float, sample_rate: float, fft_size: int) -> int:
    return max(0, min(fft_size // 2 - 1, int(freq * fft_size / sample_rate)))


def _compute_bars(
    pcm: "np.ndarray",          # 1-D float32, one channel, normalised to ±1
    sample_rate: float,
    peak_vals: list[float],
    peak_hold: list[int],
    prev_bars: list[float],
) -> list[float]:
    """FFT → log-scaled bars with smoothing, updates peak_vals in-place."""
    n = len(pcm)
    if n < _FFT_SIZE:
        pcm = np.pad(pcm, (0, _FFT_SIZE - n))
    else:
        pcm = pcm[-_FFT_SIZE:]

    window = np.hanning(_FFT_SIZE).astype(np.float32)
    mag    = np.abs(np.fft.rfft(pcm * window))[: _FFT_SIZE // 2]
    # Convert to dBFS  (add small epsilon to avoid log(0))
    db  = 20.0 * np.log10(mag / (_FFT_SIZE / 2) + 1e-9)
    # Map to 0-1  (–90 dBFS → 0, 0 dBFS → 1)
    norm = np.clip((db + 90.0) / 90.0, 0.0, 1.0).astype(np.float64)

    bars: list[float] = []
    for i in range(_NUM_BARS):
        lo = _freq_to_bin(_LOG_EDGES[i],     sample_rate, _FFT_SIZE)
        hi = _freq_to_bin(_LOG_EDGES[i + 1], sample_rate, _FFT_SIZE)
        hi = max(hi, lo + 1)
        val = float(np.max(norm[lo:hi]))

        # Temporal smoothing
        val = max(val, prev_bars[i] * (1.0 - _DECAY))
        bars.append(val)

        # Peak hold
        if val >= peak_vals[i]:
            peak_vals[i] = val
            peak_hold[i] = _PEAK_HOLD
        else:
            if peak_hold[i] > 0:
                peak_hold[i] -= 1
            else:
                peak_vals[i] = max(0.0, peak_vals[i] - _PEAK_DECAY)

    return bars


# ---------------------------------------------------------------------------
# Single-channel bar strip
# ---------------------------------------------------------------------------

class _ChannelStrip(QWidget):
    """One spectrum strip (L or R). Draws _NUM_BARS filled bars."""

    def __init__(self, label: str = "", parent=None):
        super().__init__(parent)
        self._label     = label
        self._bars      = [0.0] * _NUM_BARS
        self._peak_vals = [0.0] * _NUM_BARS
        self._peak_hold = [0]   * _NUM_BARS
        self._sr        = 44100.0
        self.setMinimumSize(60, 40)

    def set_sample_rate(self, sr: float) -> None:
        self._sr = sr

    def update_bars(self, pcm: "np.ndarray") -> None:
        if not _NUMPY:
            return
        self._bars = _compute_bars(
            pcm, self._sr, self._peak_vals, self._peak_hold, self._bars
        )
        self.update()

    def reset(self) -> None:
        self._bars      = [0.0] * _NUM_BARS
        self._peak_vals = [0.0] * _NUM_BARS
        self._peak_hold = [0]   * _NUM_BARS
        self.update()

    def paintEvent(self, _event) -> None:
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # Background
        p.fillRect(0, 0, w, h, _BG)

        if not _NUMPY or not self._bars:
            # Draw label only
            if self._label:
                p.setPen(_LABEL_CLR)
                p.drawText(4, h - 4, self._label)
            p.end()
            return

        bar_total_w = w / _NUM_BARS
        bar_w       = max(1.0, bar_total_w - 1.0)   # 1 px gap between bars

        # Gradient: bottom green → mid yellow → top red
        grad = QLinearGradient(0, h, 0, 0)
        grad.setColorAt(0.0,  _BAR_BOTTOM)
        grad.setColorAt(0.65, _BAR_MID)
        grad.setColorAt(1.0,  _BAR_TOP)

        p.setPen(Qt.PenStyle.NoPen)

        for i, val in enumerate(self._bars):
            bh = max(1.0, val * h)
            x  = i * bar_total_w
            y  = h - bh
            # Bar
            p.setBrush(grad)
            p.drawRect(QRectF(x, y, bar_w, bh))
            # Peak tick
            pv = self._peak_vals[i]
            if pv > 0.01:
                py = h - pv * h
                p.setBrush(QColor("#ffffff"))
                p.drawRect(QRectF(x, py, bar_w, 1.5))

        # Channel label
        if self._label:
            p.setPen(_LABEL_CLR)
            p.drawText(4, h - 4, self._label)

        p.end()


# ---------------------------------------------------------------------------
# Public stereo spectrum widget
# ---------------------------------------------------------------------------

class SpectrumWidget(QWidget):
    """
    Stereo spectrum analyzer.

    Call set_pcm(raw_bytes, sample_rate, channels) from the audio thread
    (or any thread — Qt update() is thread-safe).

    Use set_combined(True/False) to toggle single/dual display.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._combined  = False
        self._sr        = 44100.0
        self._channels  = 2

        self._left  = _ChannelStrip("L", self)
        self._right = _ChannelStrip("R", self)
        self._mono  = _ChannelStrip("",  self)

        self._left.set_sample_rate(self._sr)
        self._right.set_sample_rate(self._sr)
        self._mono.set_sample_rate(self._sr)

        self.setMinimumSize(120, 60)
        self._do_layout()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_combined(self, combined: bool) -> None:
        self._combined = combined
        self._do_layout()
        self.update()

    def set_pcm(self, raw: bytes, sample_rate: float = 44100.0, channels: int = 2) -> None:
        """Feed raw int16 PCM bytes. Called from the audio callback thread."""
        if not _NUMPY:
            return
        self._sr       = sample_rate
        self._channels = channels
        try:
            arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if channels >= 2:
                l_ch = arr[0::2]
                r_ch = arr[1::2]
            else:
                l_ch = r_ch = arr

            if self._combined:
                self._mono.set_sample_rate(sample_rate)
                self._mono.update_bars((l_ch + r_ch) * 0.5)
            else:
                self._left.set_sample_rate(sample_rate)
                self._right.set_sample_rate(sample_rate)
                self._left.update_bars(l_ch)
                self._right.update_bars(r_ch)
        except Exception:
            pass

    def reset(self) -> None:
        self._left.reset()
        self._right.reset()
        self._mono.reset()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._do_layout()

    def _do_layout(self) -> None:
        w, h = self.width(), self.height()
        gap  = 2

        if self._combined:
            self._left.hide()
            self._right.hide()
            self._mono.setGeometry(0, 0, w, h)
            self._mono.show()
        else:
            self._mono.hide()
            half = max(10, (w - gap) // 2)
            self._left.setGeometry(0,           0, half,          h)
            self._right.setGeometry(half + gap, 0, w - half - gap, h)
            self._left.show()
            self._right.show()
