"""
snappable_window.py — Base class for Winamp-style floating windows
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

Subclass SnappableWindow for any satellite window (meters, spectrum, EQ).
The window automatically:
  • Registers with SnapManager on show, unregisters on close
  • Moves its snap-group together when dragged
  • Snaps magnetically to any other registered window within threshold
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import QWidget

from .snap_manager import SnapManager


class SnappableWindow(QWidget):
    """
    Top-level window that participates in Winamp-style magnetic snapping.

    Override _build_content() to populate the window, or just add widgets
    to self.layout() after calling super().__init__().
    """

    # Class-level re-entrancy guard — prevents recursive moveEvent calls
    _moving: bool = False

    def __init__(
        self,
        title: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Window |
            Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint,
        )
        if title:
            self.setWindowTitle(title)

    # ------------------------------------------------------------------
    # SnapManager lifecycle
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        SnapManager.instance().register(self)

    def closeEvent(self, event) -> None:
        SnapManager.instance().unregister(self)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Winamp-style move + group drag
    # ------------------------------------------------------------------

    def moveEvent(self, event) -> None:
        super().moveEvent(event)

        if SnappableWindow._moving:
            return

        delta = event.pos() - event.oldPos()
        if delta.isNull():
            return

        manager = SnapManager.instance()
        group   = manager.get_group(self)

        SnappableWindow._moving = True
        try:
            # 1. Move all group members by the same delta
            for w in group:
                if w is not self:
                    w.move(w.pos() + delta)

            # 2. Snap this window against non-group windows
            snap = manager.compute_snap(self, group)
            if snap:
                adj = QPoint(snap[0], snap[1])
                self.move(self.pos() + adj)
                # Keep group aligned with the snap adjustment
                for w in group:
                    if w is not self:
                        w.move(w.pos() + adj)
        finally:
            SnappableWindow._moving = False
