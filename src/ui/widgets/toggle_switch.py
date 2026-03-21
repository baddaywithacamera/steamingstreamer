"""
STEAMING STREAM — Toggle Switch Widget
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

Pill-shaped on/off toggle. Green when on, grey when off.
Emits toggled(bool) on change.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QFont
from PyQt6.QtWidgets import QWidget


class ToggleSwitch(QWidget):
    """Green pill toggle. Emits toggled(bool) when clicked."""

    toggled = pyqtSignal(bool)

    # Geometry
    W, H = 58, 28

    # Colours
    _TRACK_ON    = QColor(0,  160,  0)
    _TRACK_OFF   = QColor(55,  55, 55)
    _KNOB        = QColor(230, 230, 230)
    _KNOB_SHADOW = QColor(0, 0, 0, 60)
    _TEXT_ON     = QColor(30,  80, 30)
    _TEXT_OFF    = QColor(140, 140, 140)

    def __init__(self, parent=None, initial: bool = False):
        super().__init__(parent)
        self._on = initial
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_on(self) -> bool:
        return self._on

    def set_on(self, state: bool, emit: bool = False) -> None:
        if self._on != state:
            self._on = state
            if emit:
                self.toggled.emit(self._on)
            self.update()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._on = not self._on
            self.toggled.emit(self._on)
            self.update()

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        track_color = self._TRACK_ON if self._on else self._TRACK_OFF

        # Track (pill shape)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track_color)
        p.drawRoundedRect(0, 4, self.W, self.H - 8, (self.H - 8) // 2, (self.H - 8) // 2)

        # Knob position
        knob_x = self.W - 26 - 2 if self._on else 2
        knob_y = 0
        knob_d = self.H

        # Subtle shadow
        p.setBrush(self._KNOB_SHADOW)
        p.drawEllipse(knob_x + 1, knob_y + 2, knob_d, knob_d)

        # Knob
        p.setBrush(self._KNOB)
        p.drawEllipse(knob_x, knob_y, knob_d, knob_d)

        # Label on knob
        font = QFont("Segoe UI", 7, QFont.Weight.Bold)
        p.setFont(font)
        label = "ON" if self._on else "OFF"
        color = self._TEXT_ON if self._on else self._TEXT_OFF
        p.setPen(QPen(color))
        p.drawText(knob_x, knob_y, knob_d, knob_d, Qt.AlignmentFlag.AlignCenter, label)
