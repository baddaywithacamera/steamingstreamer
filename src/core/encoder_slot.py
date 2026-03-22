"""
STEAMING STREAM — FFmpeg Encoder Slot
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

One encoder slot = one FFmpeg subprocess pushing one stream to one server.

Accepts raw 16-bit signed int PCM via feed(), encodes with FFmpeg,
and pushes to Icecast, Shoutcast 1, or Shoutcast 2 (MRS / DNAS 2.x).

Metadata updates hit the server's HTTP admin API directly.
Auto-reconnect runs in a daemon thread.

FFmpeg must be on PATH or at the path returned by ffmpeg_path().
"""

from __future__ import annotations

import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote, urlencode

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from src.core.config import EncoderConfig


# ---------------------------------------------------------------------------
# FFmpeg path resolution
# ---------------------------------------------------------------------------

def ffmpeg_path() -> str:
    """
    Return path to ffmpeg binary.
    Checks (in order):
      1. Bundled binary next to this executable (PyInstaller release)
      2. System PATH
    """
    # PyInstaller sets sys.frozen and sys._MEIPASS
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
        for name in ("ffmpeg.exe", "ffmpeg"):
            candidate = base / name
            if candidate.exists():
                return str(candidate)

    # Fallback: PATH
    found = shutil.which("ffmpeg")
    if found:
        return found

    raise FileNotFoundError(
        "ffmpeg not found. Install FFmpeg and make sure it is on your PATH."
    )


# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

class SlotStatus:
    IDLE       = "idle"
    CONNECTING = "connecting"
    CONNECTED  = "connected"
    ERROR      = "error"


# ---------------------------------------------------------------------------
# Encoder slot
# ---------------------------------------------------------------------------

class EncoderSlot:
    """
    Manages one FFmpeg subprocess for one stream output.

    Thread safety: feed() may be called from the audio thread.
    Callbacks fire from background threads — wire to Qt queued signals.
    """

    _QUEUE_SIZE = 64   # chunks; ~1.5 s of audio at 44100/1024 blocksize

    def __init__(
        self,
        config:           EncoderConfig,
        on_status_change: Optional[Callable[[str, str], None]] = None,
        on_log:           Optional[Callable[[str], None]]       = None,
    ):
        self._cfg               = config
        self._on_status_change  = on_status_change
        self._on_log            = on_log

        self._proc:              Optional[subprocess.Popen] = None
        self._write_q:           queue.Queue                = queue.Queue(maxsize=self._QUEUE_SIZE)
        self._writer_thread:     Optional[threading.Thread] = None
        self._monitor_thread:    Optional[threading.Thread] = None
        self._running:           bool                       = False
        self._reconnect_count:   int                        = 0
        self._status:            str                        = SlotStatus.IDLE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def status(self) -> str:
        return self._status

    @property
    def encoder_id(self) -> str:
        return self._cfg.id

    def start(self) -> None:
        if not self._cfg.server:
            self._log(f"[{self._cfg.name}] Not configured — skipping.")
            self._set_status(SlotStatus.ERROR)
            return
        self._running = True
        self._reconnect_count = 0
        self._connect()

    def stop(self) -> None:
        self._running = False
        # Drain writer queue
        try:
            self._write_q.put_nowait(None)
        except queue.Full:
            pass
        self._kill_ffmpeg()
        self._set_status(SlotStatus.IDLE)

    def feed(self, pcm: bytes) -> None:
        """Deliver a PCM chunk. Drops silently if queue is full."""
        if self._status == SlotStatus.CONNECTED:
            try:
                self._write_q.put_nowait(pcm)
            except queue.Full:
                pass

    def update_metadata(self, title: str) -> None:
        """Push now-playing title to the server's HTTP admin endpoint."""
        if not REQUESTS_AVAILABLE:
            return
        cfg = self._cfg
        if not cfg.server:
            return
        threading.Thread(
            target=self._push_metadata,
            args=(title,),
            daemon=True,
        ).start()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        self._set_status(SlotStatus.CONNECTING)
        try:
            cmd = self._build_ffmpeg_cmd()
            self._log(f"[{self._cfg.name}] Starting: {' '.join(cmd[:6])}…")
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except FileNotFoundError as exc:
            self._log(f"[{self._cfg.name}] FFmpeg not found: {exc}")
            self._set_status(SlotStatus.ERROR)
            return
        except Exception as exc:
            self._log(f"[{self._cfg.name}] Failed to start: {exc}")
            self._set_status(SlotStatus.ERROR)
            self._maybe_reconnect()
            return

        self._set_status(SlotStatus.CONNECTED)
        self._reconnect_count = 0

        self._writer_thread = threading.Thread(
            target=self._writer_loop, daemon=True,
            name=f"writer-{self._cfg.id}"
        )
        self._writer_thread.start()

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True,
            name=f"monitor-{self._cfg.id}"
        )
        self._monitor_thread.start()

    def _writer_loop(self) -> None:
        """Pull PCM chunks from queue and write to FFmpeg stdin."""
        while self._running:
            try:
                chunk = self._write_q.get(timeout=0.2)
                if chunk is None:
                    break
                if self._proc and self._proc.stdin:
                    self._proc.stdin.write(chunk)
            except queue.Empty:
                continue
            except (BrokenPipeError, OSError):
                self._log(f"[{self._cfg.name}] Write error — pipe broken.")
                self._set_status(SlotStatus.ERROR)
                self._maybe_reconnect()
                break

    def _monitor_loop(self) -> None:
        """Read FFmpeg stderr; detect unexpected exit."""
        if not self._proc:
            return
        for raw_line in self._proc.stderr:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                self._log(f"[{self._cfg.name}] {line}")
        # Process exited
        if self._running and self._status == SlotStatus.CONNECTED:
            self._log(f"[{self._cfg.name}] Stream process exited unexpectedly.")
            self._set_status(SlotStatus.ERROR)
            self._maybe_reconnect()

    def _maybe_reconnect(self) -> None:
        if not self._running or not self._cfg.auto_reconnect:
            return
        max_a = self._cfg.reconnect_max
        if max_a > 0 and self._reconnect_count >= max_a:
            self._log(f"[{self._cfg.name}] Max reconnect attempts reached.")
            return
        self._reconnect_count += 1
        delay = self._cfg.reconnect_delay
        self._log(
            f"[{self._cfg.name}] Reconnecting in {delay}s "
            f"(attempt {self._reconnect_count}"
            + (f"/{max_a}" if max_a > 0 else "") + ")…"
        )
        def _delayed():
            time.sleep(delay)
            if self._running:
                self._kill_ffmpeg()
                self._connect()
        threading.Thread(target=_delayed, daemon=True).start()

    def _kill_ffmpeg(self) -> None:
        proc = self._proc
        self._proc = None          # clear first to prevent race
        if proc:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # FFmpeg command builder
    # ------------------------------------------------------------------

    def _build_ffmpeg_cmd(self) -> list[str]:
        c = self._cfg
        ch = 2 if c.channels == "stereo" else 1

        cmd = [
            ffmpeg_path(),
            "-hide_banner", "-loglevel", "warning",
            # Input: raw PCM from stdin
            "-f",  "s16le",
            "-ar", str(c.sample_rate),
            "-ac", str(ch),
            "-i",  "pipe:0",
        ]

        # Encoder
        if c.format == "AAC+":
            # HE-AAC (AAC+ / SBR) — dramatically better than plain AAC at low bitrates
            cmd += ["-c:a", "aac", "-profile:a", "aac_he", "-b:a", f"{c.bitrate}k"]
            fmt  = "adts"
            mime = "audio/aacp"   # SC2/MRS expects aacp not aac for HE-AAC streams
        elif c.format == "AAC":
            cmd += ["-c:a", "aac", "-b:a", f"{c.bitrate}k"]
            fmt  = "adts"
            mime = "audio/aac"
        else:  # MP3
            cmd += ["-c:a", "libmp3lame", "-b:a", f"{c.bitrate}k",
                    "-q:a", "0"]
            fmt  = "mp3"
            mime = "audio/mpeg"

        # Output URL
        url = self._build_output_url()

        # Server-type-specific flags
        # MRS / Shoutcast 2 still needs legacy SOURCE method — PUT is rejected immediately
        extra: list[str] = []
        if c.server_type in ("shoutcast1", "shoutcast2"):
            extra += ["-legacy_icecast", "1"]

        cmd += extra + [
            "-f",            fmt,
            "-content_type", mime,
            "-ice_name",     c.name,
            url,
        ]

        return cmd

    def _build_output_url(self) -> str:
        c = self._cfg
        mount = c.mount if c.mount.startswith("/") else f"/{c.mount}"

        if c.server_type == "icecast":
            # Icecast 2: standard mount
            return f"icecast://source:{c.password}@{c.server}:{c.port}{mount}"

        elif c.server_type == "shoutcast1":
            # Shoutcast 1: no mount, password only
            return f"icecast://source:{c.password}@{c.server}:{c.port}/"

        else:
            # Shoutcast 2 / MRS: numeric mount = SID (e.g. /3 = stream 3)
            return f"icecast://source:{c.password}@{c.server}:{c.port}{mount}"

    # ------------------------------------------------------------------
    # Metadata HTTP push
    # ------------------------------------------------------------------

    def _push_metadata(self, title: str) -> None:
        """Fire-and-forget HTTP metadata update. Runs in daemon thread."""
        c = self._cfg
        if not c.server:
            return
        try:
            if c.server_type == "icecast":
                # Icecast 2 admin endpoint
                url = (
                    f"http://{c.server}:{c.port}/admin/metadata"
                    f"?mount={quote(c.mount)}&mode=updinfo&song={quote(title)}"
                )
                requests.get(url, auth=("source", c.password), timeout=3)

            else:
                # Shoutcast 1 & 2 (MRS uses Shoutcast 2 admin.cgi)
                url = f"http://{c.server}:{c.port}/admin.cgi"
                params = {"mode": "updinfo", "song": title, "pass": c.password}
                requests.get(url, params=params, timeout=3)

        except Exception as exc:
            self._log(f"[{self._cfg.name}] Metadata push failed: {exc}")

    # ------------------------------------------------------------------
    # Listener count poll (Shoutcast admin XML)
    # ------------------------------------------------------------------

    def fetch_stats(self) -> dict:
        """
        Return {'listeners': int, 'peak': int, 'title': str} or empty dict on fail.
        Shoutcast 2: GET /admin.cgi?mode=viewxml&page=3
        """
        if not REQUESTS_AVAILABLE:
            return {}
        c = self._cfg
        if not c.server:
            return {}
        try:
            if c.server_type == "icecast":
                url = f"http://{c.server}:{c.port}/status-json.xsl"
                r = requests.get(url, timeout=3)
                # Basic parse — full implementation in stats phase
                return {}
            else:
                url = f"http://{c.server}:{c.port}/admin.cgi"
                params = {"mode": "viewxml", "page": "3", "pass": c.password}
                r = requests.get(url, params=params, timeout=3)
                return _parse_shoutcast_xml(r.text)
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, status: str) -> None:
        self._status = status
        if self._on_status_change:
            self._on_status_change(self._cfg.id, status)

    def _log(self, msg: str) -> None:
        if self._on_log:
            self._on_log(msg)


# ---------------------------------------------------------------------------
# Shoutcast XML stat parser (minimal)
# ---------------------------------------------------------------------------

def _parse_shoutcast_xml(xml: str) -> dict:
    """Extract listener counts from Shoutcast admin.cgi viewxml response."""
    import re
    result = {}
    for tag, key in (
        (r"<CURRENTLISTENERS>(\d+)</CURRENTLISTENERS>", "listeners"),
        (r"<PEAKLISTENERS>(\d+)</PEAKLISTENERS>",       "peak"),
        (r"<SONGTITLE>(.*?)</SONGTITLE>",               "title"),
    ):
        m = re.search(tag, xml, re.IGNORECASE)
        if m:
            result[key] = int(m.group(1)) if key != "title" else m.group(1)
    return result
