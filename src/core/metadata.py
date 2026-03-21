"""
STEAMING STREAM — Metadata Watcher
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

Watches a now-playing text file and fires a callback on change.
Also handles URL polling and static text sources.

RadioDJ writes: Artist - Title (one line, UTF-8)
TUNE/TWERKER will write the same format.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from src.core.config import MetadataConfig


class MetadataWatcher:
    """
    Polls a metadata source and fires on_update(title) when the
    now-playing title changes.

    Supported sources:
      "file"   — plain text file, polls every poll_interval seconds
      "url"    — HTTP GET, polls every poll_interval seconds
      "static" — static string, fires once on start
    """

    def __init__(
        self,
        config:    MetadataConfig,
        on_update: Optional[Callable[[str], None]] = None,
        on_log:    Optional[Callable[[str], None]] = None,
    ):
        self._cfg       = config
        self._on_update = on_update
        self._on_log    = on_log

        self._thread:        Optional[threading.Thread] = None
        self._running:       bool  = False
        self._current_title: str   = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def current_title(self) -> str:
        return self._current_title

    def start(self) -> None:
        self._running = True
        if self._cfg.source_type == "static":
            self._emit(self._cfg.static_text or self._cfg.fallback_text)
            return
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="metadata-watcher"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def push_title(self, title: str) -> None:
        """Manually push a title (e.g. from the HTTP API)."""
        self._emit(title)

    # ------------------------------------------------------------------
    # Watch loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        last_mtime: Optional[float] = None

        while self._running:
            try:
                if self._cfg.source_type == "file":
                    self._poll_file(last_mtime)
                elif self._cfg.source_type == "url":
                    self._poll_url()
            except Exception as exc:
                self._log(f"Metadata poll error: {exc}")

            time.sleep(self._cfg.poll_interval)

    def _poll_file(self, last_mtime: Optional[float]) -> None:
        path = Path(self._cfg.file_path)
        if not path.exists():
            if self._current_title != self._cfg.fallback_text:
                self._emit(self._cfg.fallback_text)
            return

        mtime = path.stat().st_mtime
        if mtime == last_mtime:
            return

        title = self._read_file(path)
        if title != self._current_title:
            self._emit(title)

    def _read_file(self, path: Path) -> str:
        try:
            content = path.read_text(
                encoding=self._cfg.encoding, errors="replace"
            ).strip()
            if self._cfg.use_first_line:
                return content.splitlines()[0].strip() if content else ""
            return content
        except Exception:
            return self._cfg.fallback_text

    def _poll_url(self) -> None:
        if not REQUESTS_AVAILABLE:
            return
        try:
            r = requests.get(self._cfg.url, timeout=3)
            title = r.text.strip()
            if self._cfg.use_first_line:
                title = title.splitlines()[0].strip()
            if title and title != self._current_title:
                self._emit(title)
        except Exception as exc:
            self._log(f"Metadata URL poll failed: {exc}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _emit(self, title: str) -> None:
        self._current_title = title
        if self._on_update:
            self._on_update(title)

    def _log(self, msg: str) -> None:
        if self._on_log:
            self._on_log(msg)
