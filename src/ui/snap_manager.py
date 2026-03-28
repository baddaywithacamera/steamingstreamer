"""
snap_manager.py — Winamp-style magnetic window snapping
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

Every floating window (meters, spectrum, EQ) registers itself here.
When any window moves, snap_manager:
  1. Identifies the window's snap-group (all transitively-touching windows)
  2. Moves the whole group by the same delta
  3. Snaps the group to any non-member window within SNAP_THRESHOLD px
"""

from __future__ import annotations
from typing import Optional

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QWidget


class SnapManager:
    """Singleton — call SnapManager.instance().register(w) from each window."""

    SNAP_THRESHOLD: int = 12   # px — magnetic zone width
    TOUCH_THRESHOLD: int = 2   # px — "touching" for group detection

    _instance: Optional["SnapManager"] = None

    @classmethod
    def instance(cls) -> "SnapManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._windows: list[QWidget] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, w: QWidget) -> None:
        if w not in self._windows:
            self._windows.append(w)

    def unregister(self, w: QWidget) -> None:
        if w in self._windows:
            self._windows.remove(w)

    @property
    def windows(self) -> list[QWidget]:
        return list(self._windows)

    # ------------------------------------------------------------------
    # Group detection  (BFS through touching windows)
    # ------------------------------------------------------------------

    def get_group(self, anchor: QWidget) -> set[QWidget]:
        """Return all windows transitively touching anchor (including anchor)."""
        visited: set[QWidget] = {anchor}
        queue: list[QWidget] = [anchor]
        while queue:
            w = queue.pop()
            for nb in self._neighbors(w):
                if nb not in visited:
                    visited.add(nb)
                    queue.append(nb)
        return visited

    def _neighbors(self, w: QWidget) -> list[QWidget]:
        """Windows whose edges are currently flush against w."""
        wg = w.frameGeometry()
        T = self.TOUCH_THRESHOLD
        result: list[QWidget] = []
        for other in self._windows:
            if other is w:
                continue
            og = other.frameGeometry()
            # Horizontal adjacency — vertical bands overlap
            h_adj = (
                abs(wg.right() - og.left()) <= T or
                abs(wg.left() - og.right()) <= T
            ) and not (wg.bottom() < og.top() or wg.top() > og.bottom())
            # Vertical adjacency — horizontal bands overlap
            v_adj = (
                abs(wg.bottom() - og.top()) <= T or
                abs(wg.top() - og.bottom()) <= T
            ) and not (wg.right() < og.left() or wg.left() > og.right())
            if h_adj or v_adj:
                result.append(other)
        return result

    # ------------------------------------------------------------------
    # Snap computation
    # ------------------------------------------------------------------

    def compute_snap(
        self,
        moving: QWidget,
        group: set[QWidget],
    ) -> Optional[tuple[int, int]]:
        """
        Given moving window's current position, return (dx, dy) to snap it
        against any non-group registered window, or None.
        """
        mg = moving.frameGeometry()
        best_dx = best_dy = 0
        best_dist = self.SNAP_THRESHOLD + 1
        snapped = False

        for other in self._windows:
            if other in group:
                continue
            result = self._edge_snap(mg, other.frameGeometry())
            if result is not None:
                dx, dy = result
                dist = abs(dx) + abs(dy)
                if dist < best_dist:
                    best_dist = dist
                    best_dx, best_dy = dx, dy
                    snapped = True

        return (best_dx, best_dy) if snapped else None

    def _edge_snap(self, mg: QRect, og: QRect) -> Optional[tuple[int, int]]:
        """Compute (dx, dy) to align edges of mg against og, or None."""
        T = self.SNAP_THRESHOLD
        dx: Optional[int] = None
        dy: Optional[int] = None

        # Vertical band overlap check (with tolerance) for horizontal snaps
        h_ok = not (mg.bottom() < og.top() - T or mg.top() > og.bottom() + T)
        if h_ok:
            if abs(mg.right() + 1 - og.left()) <= T:
                dx = og.left() - 1 - mg.right()        # right → left
            elif abs(mg.left() - og.right() - 1) <= T:
                dx = og.right() + 1 - mg.left()        # left ← right
            elif abs(mg.left() - og.left()) <= T:
                dx = og.left() - mg.left()              # align left edges
            elif abs(mg.right() - og.right()) <= T:
                dx = og.right() - mg.right()            # align right edges

        # Horizontal band overlap check for vertical snaps
        v_ok = not (mg.right() < og.left() - T or mg.left() > og.right() + T)
        if v_ok:
            if abs(mg.bottom() + 1 - og.top()) <= T:
                dy = og.top() - 1 - mg.bottom()        # bottom → top
            elif abs(mg.top() - og.bottom() - 1) <= T:
                dy = og.bottom() + 1 - mg.top()        # top ← bottom
            elif abs(mg.top() - og.top()) <= T:
                dy = og.top() - mg.top()               # align top edges
            elif abs(mg.bottom() - og.bottom()) <= T:
                dy = og.bottom() - mg.bottom()         # align bottom edges

        if dx is None and dy is None:
            return None

        # Secondary-axis alignment: when snapping in one axis, nudge the other
        if dx is not None and dy is None:
            if abs(mg.top() - og.top()) <= T:
                dy = og.top() - mg.top()
            elif abs(mg.bottom() - og.bottom()) <= T:
                dy = og.bottom() - mg.bottom()

        if dy is not None and dx is None:
            if abs(mg.left() - og.left()) <= T:
                dx = og.left() - mg.left()
            elif abs(mg.right() - og.right()) <= T:
                dx = og.right() - mg.right()

        return (dx or 0, dy or 0)
