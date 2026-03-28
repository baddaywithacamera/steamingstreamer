"""
eq_widget.py — 10-band graphic equalizer + compressor + limiter
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

DSP lives in EQProcessor (runs in the audio thread).
UI lives in EQWidget (runs on the Qt thread).
They communicate via EQProcessor.set_band_db() which is thread-safe
(just sets a float, no locks needed for single-writer/single-reader).
"""

from __future__ import annotations
import math
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

try:
    import numpy as np
    _NUMPY = True
except ImportError:
    _NUMPY = False

# ---------------------------------------------------------------------------
# Band definitions (10 bands, centre frequencies in Hz)
# ---------------------------------------------------------------------------

EQ_BANDS: list[tuple[float, str]] = [
    (32,    "32"),
    (64,    "64"),
    (125,   "125"),
    (250,   "250"),
    (500,   "500"),
    (1000,  "1k"),
    (2000,  "2k"),
    (4000,  "4k"),
    (8000,  "8k"),
    (16000, "16k"),
]

EQ_GAIN_RANGE = 12.0   # ± dB
EQ_Q_DEFAULT  = 1.41   # Butterworth shelf/peak Q

# Default presets {name: [gain_db × 10 bands]}
EQ_PRESETS: dict[str, list[float]] = {
    "Flat":       [0.0] * 10,
    "Bass Boost": [6.0, 5.0, 3.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "Treble Boost":[0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 2.0, 3.0, 5.0, 6.0],
    "Jazz":       [4.0, 3.0, 2.0, 2.5, -2.0, -2.0, 0.0, 2.0, 3.0, 3.5],
    "Rock":       [5.0, 4.0, 3.0, 1.0, -1.0, -1.0, 2.0, 3.0, 4.0, 4.0],
    "Vocal":      [-2.0, -1.0, 0.0, 2.0, 4.0, 4.0, 3.0, 1.0, 0.0, -1.0],
    "Dance":      [6.0, 5.0, 2.0, 0.0, -2.0, -1.0, 2.0, 4.0, 5.0, 5.0],
}


# ---------------------------------------------------------------------------
# Biquad peaking EQ filter (IIR, second-order)
# ---------------------------------------------------------------------------

class _Biquad:
    """
    Peaking EQ biquad filter.  Coefficients update instantly when gain changes.
    State (x1, x2, y1, y2) is per-channel, stereo interleaved.
    """

    def __init__(self, freq: float, q: float = EQ_Q_DEFAULT, sample_rate: float = 44100.0):
        self._freq = freq
        self._q    = q
        self._sr   = sample_rate
        self._db   = 0.0
        # Coefficients
        self._b0 = self._b1 = self._b2 = 1.0
        self._a1 = self._a2 = 0.0
        # State (2 channels × 2 delay elements)
        self._x1 = [0.0, 0.0]
        self._x2 = [0.0, 0.0]
        self._y1 = [0.0, 0.0]
        self._y2 = [0.0, 0.0]
        self._update_coeffs()

    def set_gain_db(self, db: float) -> None:
        self._db = db
        self._update_coeffs()

    def set_sample_rate(self, sr: float) -> None:
        self._sr = sr
        self._update_coeffs()

    def _update_coeffs(self) -> None:
        """Recompute biquad coefficients for a peaking EQ filter."""
        A  = 10.0 ** (self._db / 40.0)
        w0 = 2.0 * math.pi * self._freq / self._sr
        cw = math.cos(w0)
        sw = math.sin(w0)
        alpha = sw / (2.0 * self._q)

        b0 =  1.0 + alpha * A
        b1 = -2.0 * cw
        b2 =  1.0 - alpha * A
        a0 =  1.0 + alpha / A
        a1 = -2.0 * cw
        a2 =  1.0 - alpha / A

        self._b0 = b0 / a0
        self._b1 = b1 / a0
        self._b2 = b2 / a0
        self._a1 = a1 / a0
        self._a2 = a2 / a0

    def process(self, samples: "np.ndarray", channels: int = 2) -> "np.ndarray":
        """
        Process interleaved int16 samples in-place (as float32).
        samples shape: (frames * channels,) float32, ±1.0
        Returns processed float32 array of same shape.
        """
        if not _NUMPY or abs(self._db) < 0.01:
            return samples  # bypass when flat

        out = samples.copy()
        for ch in range(min(channels, 2)):
            ch_data = out[ch::channels]
            x1, x2 = self._x1[ch], self._x2[ch]
            y1, y2 = self._y1[ch], self._y2[ch]
            b0, b1, b2 = self._b0, self._b1, self._b2
            a1, a2     = self._a1, self._a2
            result = np.empty_like(ch_data)
            for i, xn in enumerate(ch_data):
                yn = b0*xn + b1*x1 + b2*x2 - a1*y1 - a2*y2
                x2, x1 = x1, xn
                y2, y1 = y1, yn
                result[i] = yn
            self._x1[ch], self._x2[ch] = x1, x2
            self._y1[ch], self._y2[ch] = y1, y2
            out[ch::channels] = result

        return out


# ---------------------------------------------------------------------------
# Compressor
# ---------------------------------------------------------------------------

class _Compressor:
    """Simple RMS feed-forward compressor."""

    def __init__(self):
        self.enabled   = True
        self.threshold = -18.0   # dBFS
        self.ratio     = 4.0
        self.attack    = 0.005   # seconds
        self.release   = 0.100
        self.makeup    = 0.0     # dB
        self._env      = 0.0     # envelope follower

    def process(self, samples: "np.ndarray", sr: float, channels: int) -> "np.ndarray":
        if not _NUMPY or not self.enabled:
            return samples

        attack_c  = math.exp(-1.0 / (sr * self.attack))
        release_c = math.exp(-1.0 / (sr * self.release))
        makeup    = 10.0 ** (self.makeup / 20.0)
        thresh_l  = 10.0 ** (self.threshold / 20.0)

        out = samples.copy()
        # Mix channels for level detection
        if channels >= 2:
            level_sig = (out[0::2].astype(np.float64) +
                         out[1::2].astype(np.float64)) * 0.5
        else:
            level_sig = out.astype(np.float64)

        env = self._env
        gains = np.empty(len(level_sig), dtype=np.float64)
        for i, x in enumerate(np.abs(level_sig)):
            if x > env:
                env = attack_c  * env + (1.0 - attack_c)  * x
            else:
                env = release_c * env + (1.0 - release_c) * x
            if env > thresh_l:
                gain = (thresh_l * (env / thresh_l) ** (1.0 / self.ratio)) / env
            else:
                gain = 1.0
            gains[i] = gain * makeup

        self._env = env
        # Apply per-sample gain to all channels
        for ch in range(min(channels, 2)):
            out[ch::channels] = (out[ch::channels].astype(np.float64) * gains).astype(np.float32)
        return out


# ---------------------------------------------------------------------------
# Limiter (brickwall)
# ---------------------------------------------------------------------------

class _Limiter:
    """Fast lookahead brickwall limiter."""

    def __init__(self):
        self.enabled   = True
        self.pre_gain  = 0.0      # dB
        self.ceiling   = -0.3     # dBFS true peak ceiling
        self.attack    = 0.001
        self.release   = 0.010
        self._env      = 0.0

    def process(self, samples: "np.ndarray", sr: float, channels: int) -> "np.ndarray":
        if not _NUMPY or not self.enabled:
            return samples

        pre    = 10.0 ** (self.pre_gain / 20.0)
        ceil   = 10.0 ** (self.ceiling / 20.0)
        att_c  = math.exp(-1.0 / (sr * self.attack))
        rel_c  = math.exp(-1.0 / (sr * self.release))

        out = (samples.astype(np.float64) * pre)
        if channels >= 2:
            peak_sig = np.maximum(np.abs(out[0::2]), np.abs(out[1::2]))
        else:
            peak_sig = np.abs(out)

        env = self._env
        gains = np.empty(len(peak_sig), dtype=np.float64)
        for i, pk in enumerate(peak_sig):
            if pk > env:
                env = att_c * env + (1.0 - att_c) * pk
            else:
                env = rel_c * env + (1.0 - rel_c) * pk
            gains[i] = min(1.0, ceil / max(env, 1e-9))

        self._env = env
        for ch in range(min(channels, 2)):
            out[ch::channels] *= gains
        return np.clip(out, -1.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# EQProcessor — runs on the audio thread
# ---------------------------------------------------------------------------

class EQProcessor:
    """
    Thread-safe audio processor: 10-band EQ → Compressor → Limiter.

    All set_* methods are safe to call from the Qt thread while process()
    runs on the audio thread (float assignments are atomic in CPython).
    """

    def __init__(self, sample_rate: float = 44100.0, channels: int = 2):
        self._sr       = sample_rate
        self._channels = channels
        self.enabled   = True

        self._filters: list[_Biquad] = [
            _Biquad(freq, sample_rate=sample_rate)
            for freq, _ in EQ_BANDS
        ]
        self.compressor = _Compressor()
        self.limiter    = _Limiter()

    def set_sample_rate(self, sr: float) -> None:
        self._sr = sr
        for f in self._filters:
            f.set_sample_rate(sr)

    def set_channels(self, ch: int) -> None:
        self._channels = ch

    def set_band_db(self, band: int, db: float) -> None:
        """Set gain for one EQ band (0-indexed). Thread-safe."""
        if 0 <= band < len(self._filters):
            self._filters[band].set_gain_db(db)

    def set_preset(self, gains: list[float]) -> None:
        for i, db in enumerate(gains):
            self.set_band_db(i, db)

    def process(self, raw: bytes) -> bytes:
        """
        Process raw int16 PCM bytes through the full chain.
        Returns processed int16 PCM bytes.
        """
        if not _NUMPY or not self.enabled:
            return raw
        try:
            arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

            # EQ bands
            for f in self._filters:
                arr = f.process(arr, self._channels)

            # Compressor
            arr = self.compressor.process(arr, self._sr, self._channels)

            # Limiter
            arr = self.limiter.process(arr, self._sr, self._channels)

            return (np.clip(arr, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
        except Exception:
            return raw


# ---------------------------------------------------------------------------
# EQ band slider column
# ---------------------------------------------------------------------------

class _BandColumn(QWidget):
    gain_changed = pyqtSignal(int, float)   # band_index, gain_db

    def __init__(self, band_index: int, freq_label: str, parent=None):
        super().__init__(parent)
        self._idx = band_index

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # Frequency label
        lbl = QLabel(freq_label)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-size: 9px; color: #888;")

        # Vertical slider: ±EQ_GAIN_RANGE dB, scaled ×10 for integer ticks
        self._slider = QSlider(Qt.Orientation.Vertical)
        self._slider.setRange(int(-EQ_GAIN_RANGE * 10), int(EQ_GAIN_RANGE * 10))
        self._slider.setValue(0)
        self._slider.setTickPosition(QSlider.TickPosition.NoTicks)
        self._slider.setFixedHeight(120)
        self._slider.valueChanged.connect(self._on_value)

        # dB readout
        self._readout = QLabel("0.0")
        self._readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._readout.setFixedWidth(36)
        self._readout.setStyleSheet(
            "font-size: 9px; color: #aaa; "
            "background: #222; border: 1px solid #333; border-radius: 2px;"
        )

        layout.addWidget(lbl)
        layout.addWidget(self._slider, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._readout, alignment=Qt.AlignmentFlag.AlignHCenter)

    def _on_value(self, val: int) -> None:
        db = val / 10.0
        self._readout.setText(f"{db:+.1f}" if db != 0 else "0.0")
        self.gain_changed.emit(self._idx, db)

    def set_value(self, db: float) -> None:
        self._slider.blockSignals(True)
        self._slider.setValue(int(round(db * 10)))
        self._readout.setText(f"{db:+.1f}" if db != 0 else "0.0")
        self._slider.blockSignals(False)

    def value_db(self) -> float:
        return self._slider.value() / 10.0


# ---------------------------------------------------------------------------
# Compressor widget
# ---------------------------------------------------------------------------

def _make_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("font-size: 9px; color: #888;")
    return lbl


class CompressorWidget(QWidget):
    """Simple compressor controls panel."""

    def __init__(self, processor: "_Compressor", parent=None):
        super().__init__(parent)
        self._proc = processor

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(4)

        # Bypass
        self._bypass = QCheckBox("Compressor")
        self._bypass.setChecked(True)
        self._bypass.toggled.connect(lambda v: setattr(processor, "enabled", v))
        outer.addWidget(self._bypass)

        row = QHBoxLayout()
        row.setSpacing(12)

        # Threshold
        thr_col = QVBoxLayout()
        thr_col.addWidget(_make_label("Threshold"))
        self._thr = QSlider(Qt.Orientation.Vertical)
        self._thr.setRange(-400, 0)    # tenths of dB
        self._thr.setValue(int(processor.threshold * 10))
        self._thr.setFixedHeight(80)
        self._thr_lbl = QLabel(f"{processor.threshold:.1f} dB")
        self._thr_lbl.setStyleSheet("font-size: 9px; color: #aaa;")
        self._thr.valueChanged.connect(self._on_thr)
        thr_col.addWidget(self._thr, alignment=Qt.AlignmentFlag.AlignHCenter)
        thr_col.addWidget(self._thr_lbl, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Ratio
        rat_col = QVBoxLayout()
        rat_col.addWidget(_make_label("Ratio"))
        self._rat = QSlider(Qt.Orientation.Vertical)
        self._rat.setRange(10, 200)    # tenths (1.0 – 20.0)
        self._rat.setValue(int(processor.ratio * 10))
        self._rat.setFixedHeight(80)
        self._rat_lbl = QLabel(f"{processor.ratio:.1f}:1")
        self._rat_lbl.setStyleSheet("font-size: 9px; color: #aaa;")
        self._rat.valueChanged.connect(self._on_rat)
        rat_col.addWidget(self._rat, alignment=Qt.AlignmentFlag.AlignHCenter)
        rat_col.addWidget(self._rat_lbl, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Makeup
        mku_col = QVBoxLayout()
        mku_col.addWidget(_make_label("Makeup"))
        self._mku = QSlider(Qt.Orientation.Vertical)
        self._mku.setRange(0, 200)     # tenths of dB
        self._mku.setValue(int(processor.makeup * 10))
        self._mku.setFixedHeight(80)
        self._mku_lbl = QLabel(f"{processor.makeup:.1f} dB")
        self._mku_lbl.setStyleSheet("font-size: 9px; color: #aaa;")
        self._mku.valueChanged.connect(self._on_mku)
        mku_col.addWidget(self._mku, alignment=Qt.AlignmentFlag.AlignHCenter)
        mku_col.addWidget(self._mku_lbl, alignment=Qt.AlignmentFlag.AlignHCenter)

        for col in (thr_col, rat_col, mku_col):
            row.addLayout(col)
        outer.addLayout(row)

    def _on_thr(self, v: int) -> None:
        db = v / 10.0
        self._proc.threshold = db
        self._thr_lbl.setText(f"{db:.1f} dB")

    def _on_rat(self, v: int) -> None:
        r = v / 10.0
        self._proc.ratio = r
        self._rat_lbl.setText(f"{r:.1f}:1")

    def _on_mku(self, v: int) -> None:
        db = v / 10.0
        self._proc.makeup = db
        self._mku_lbl.setText(f"{db:.1f} dB")


# ---------------------------------------------------------------------------
# Limiter widget
# ---------------------------------------------------------------------------

class LimiterWidget(QWidget):
    def __init__(self, processor: "_Limiter", parent=None):
        super().__init__(parent)
        self._proc = processor

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(4)

        self._bypass = QCheckBox("Limiter")
        self._bypass.setChecked(True)
        self._bypass.toggled.connect(lambda v: setattr(processor, "enabled", v))
        outer.addWidget(self._bypass)

        row = QHBoxLayout()
        row.setSpacing(12)

        # Pre-gain
        pg_col = QVBoxLayout()
        pg_col.addWidget(_make_label("Pre Gain"))
        self._pg = QSlider(Qt.Orientation.Vertical)
        self._pg.setRange(-120, 120)   # tenths
        self._pg.setValue(int(processor.pre_gain * 10))
        self._pg.setFixedHeight(80)
        self._pg_lbl = QLabel(f"{processor.pre_gain:.1f} dB")
        self._pg_lbl.setStyleSheet("font-size: 9px; color: #aaa;")
        self._pg.valueChanged.connect(self._on_pg)
        pg_col.addWidget(self._pg, alignment=Qt.AlignmentFlag.AlignHCenter)
        pg_col.addWidget(self._pg_lbl, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Ceiling
        cl_col = QVBoxLayout()
        cl_col.addWidget(_make_label("Ceiling"))
        self._cl = QSlider(Qt.Orientation.Vertical)
        self._cl.setRange(-120, 0)     # tenths
        self._cl.setValue(int(processor.ceiling * 10))
        self._cl.setFixedHeight(80)
        self._cl_lbl = QLabel(f"{processor.ceiling:.1f} dB")
        self._cl_lbl.setStyleSheet("font-size: 9px; color: #aaa;")
        self._cl.valueChanged.connect(self._on_cl)
        cl_col.addWidget(self._cl, alignment=Qt.AlignmentFlag.AlignHCenter)
        cl_col.addWidget(self._cl_lbl, alignment=Qt.AlignmentFlag.AlignHCenter)

        for col in (pg_col, cl_col):
            row.addLayout(col)
        outer.addLayout(row)

    def _on_pg(self, v: int) -> None:
        db = v / 10.0
        self._proc.pre_gain = db
        self._pg_lbl.setText(f"{db:.1f} dB")

    def _on_cl(self, v: int) -> None:
        db = v / 10.0
        self._proc.ceiling = db
        self._cl_lbl.setText(f"{db:.1f} dB")


# ---------------------------------------------------------------------------
# Top-level EQ widget (EQ + compressor + limiter in one panel)
# ---------------------------------------------------------------------------

class EQWidget(QWidget):
    """
    10-band graphic EQ + compressor + limiter panel.
    Attach an EQProcessor and this widget drives it.
    """

    def __init__(self, processor: EQProcessor, parent=None):
        super().__init__(parent)
        self._proc = processor
        self._columns: list[_BandColumn] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── EQ header ──────────────────────────────────────────────────
        eq_header = QHBoxLayout()
        eq_lbl = QLabel("EQUALIZER")
        eq_lbl.setStyleSheet("font-weight: 700; font-size: 10px; color: #bbb;")
        self._eq_bypass = QCheckBox("Active")
        self._eq_bypass.setChecked(True)
        self._eq_bypass.toggled.connect(self._on_eq_bypass)

        self._preset_combo = QComboBox()
        self._preset_combo.addItems(list(EQ_PRESETS.keys()))
        self._preset_combo.currentTextChanged.connect(self._on_preset)

        reset_btn = QPushButton("↺")
        reset_btn.setFixedWidth(26)
        reset_btn.setToolTip("Reset to flat")
        reset_btn.clicked.connect(lambda: self._apply_preset("Flat"))

        eq_header.addWidget(eq_lbl)
        eq_header.addStretch()
        eq_header.addWidget(QLabel("Preset:"))
        eq_header.addWidget(self._preset_combo)
        eq_header.addWidget(reset_btn)
        eq_header.addWidget(self._eq_bypass)
        root.addLayout(eq_header)

        # ── Band sliders ───────────────────────────────────────────────
        bands_row = QHBoxLayout()
        bands_row.setSpacing(0)
        for i, (freq, label) in enumerate(EQ_BANDS):
            col = _BandColumn(i, label, self)
            col.gain_changed.connect(self._on_band_gain)
            self._columns.append(col)
            bands_row.addWidget(col)
        root.addLayout(bands_row)

        # ── Separator ──────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #333;")
        root.addWidget(sep)

        # ── Compressor + Limiter side by side ─────────────────────────
        chain_row = QHBoxLayout()
        chain_row.setSpacing(0)

        self._comp_widget = CompressorWidget(processor.compressor, self)
        self._lim_widget  = LimiterWidget(processor.limiter, self)

        comp_frame = QFrame()
        comp_frame.setStyleSheet("QFrame { border: 1px solid #2a2a2a; border-radius: 3px; }")
        comp_frame.setLayout(QVBoxLayout())
        comp_frame.layout().setContentsMargins(0, 0, 0, 0)
        comp_frame.layout().addWidget(self._comp_widget)

        lim_frame = QFrame()
        lim_frame.setStyleSheet("QFrame { border: 1px solid #2a2a2a; border-radius: 3px; }")
        lim_frame.setLayout(QVBoxLayout())
        lim_frame.layout().setContentsMargins(0, 0, 0, 0)
        lim_frame.layout().addWidget(self._lim_widget)

        chain_row.addWidget(comp_frame, stretch=1)
        chain_row.addSpacing(4)
        chain_row.addWidget(lim_frame, stretch=1)
        root.addLayout(chain_row)

        # Chain order label
        chain_lbl = QLabel("Chain: EQ → Compressor → Limiter")
        chain_lbl.setStyleSheet("font-size: 9px; color: #555;")
        chain_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(chain_lbl)

    # ------------------------------------------------------------------

    def _on_band_gain(self, band: int, db: float) -> None:
        self._proc.set_band_db(band, db)

    def _on_eq_bypass(self, active: bool) -> None:
        self._proc.enabled = active

    def _on_preset(self, name: str) -> None:
        self._apply_preset(name)

    def _apply_preset(self, name: str) -> None:
        gains = EQ_PRESETS.get(name, [0.0] * 10)
        self._proc.set_preset(gains)
        for i, col in enumerate(self._columns):
            col.set_value(gains[i] if i < len(gains) else 0.0)
        # Sync combo without triggering signal
        idx = self._preset_combo.findText(name)
        if idx >= 0:
            self._preset_combo.blockSignals(True)
            self._preset_combo.setCurrentIndex(idx)
            self._preset_combo.blockSignals(False)

    def get_gains(self) -> list[float]:
        return [c.value_db() for c in self._columns]
