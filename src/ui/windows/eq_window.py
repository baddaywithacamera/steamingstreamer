"""
eq_window.py — Floating snappable EQ / Compressor / Limiter window
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer
"""

from __future__ import annotations

from PyQt6.QtWidgets import QSizePolicy, QVBoxLayout

from src.ui.snappable_window import SnappableWindow
from src.ui.widgets.eq_widget import EQProcessor, EQWidget


class EQWindow(SnappableWindow):
    """
    Floating 10-band EQ + Compressor + Limiter.
    Owns an EQProcessor instance that the audio engine calls process() on.
    """

    def __init__(self, sample_rate: float = 44100.0, channels: int = 2, parent=None):
        super().__init__("EQ / Effects", parent)
        self.setMinimumSize(480, 300)
        self.resize(580, 380)

        self.processor = EQProcessor(sample_rate=sample_rate, channels=channels)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(0)

        self._eq_widget = EQWidget(self.processor, self)
        self._eq_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self._eq_widget)

    # ------------------------------------------------------------------

    def process(self, raw: bytes) -> bytes:
        """Convenience pass-through to processor — call from audio thread."""
        return self.processor.process(raw)

    def set_sample_rate(self, sr: float) -> None:
        self.processor.set_sample_rate(sr)

    def set_channels(self, ch: int) -> None:
        self.processor.set_channels(ch)
