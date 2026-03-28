"""
spectrum_window.py — Floating snappable spectrum analyzer window
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from src.ui.snappable_window import SnappableWindow
from src.ui.widgets.spectrum import SpectrumWidget


class SpectrumWindow(SnappableWindow):
    """
    Floating real-time spectrum analyzer.
    Shows L / R side-by-side (default) or combined mono view.
    """

    def __init__(self, parent=None):
        super().__init__("Spectrum", parent)
        self.setMinimumSize(200, 100)
        self.resize(400, 160)

        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(2)

        # ── Header bar ────────────────────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(4, 0, 4, 0)

        lbl = QLabel("SPECTRUM")
        lbl.setStyleSheet("font-size: 9px; font-weight: 700; color: #555; letter-spacing: 1px;")

        self._combined_btn = QPushButton("Combined")
        self._combined_btn.setCheckable(True)
        self._combined_btn.setChecked(False)
        self._combined_btn.setFixedWidth(72)
        self._combined_btn.setStyleSheet(
            "QPushButton { font-size: 9px; padding: 1px 4px; }"
            "QPushButton:checked { background: #0d6efd; color: #fff; }"
        )
        self._combined_btn.toggled.connect(self._on_combined)

        header.addWidget(lbl)
        header.addStretch()
        header.addWidget(self._combined_btn)
        root.addLayout(header)

        # ── Spectrum widget ────────────────────────────────────────────
        self.spectrum = SpectrumWidget(self)
        self.spectrum.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self.spectrum, stretch=1)

    # ------------------------------------------------------------------

    def set_pcm(self, raw: bytes, sample_rate: float = 44100.0, channels: int = 2) -> None:
        self.spectrum.set_pcm(raw, sample_rate, channels)

    def reset(self) -> None:
        self.spectrum.reset()

    def _on_combined(self, checked: bool) -> None:
        self.spectrum.set_combined(checked)
        self._combined_btn.setText("Stereo" if checked else "Combined")
