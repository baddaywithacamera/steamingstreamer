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

import os
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
from src.core.sc2_client import SC2Client, SC2Error, SC2StreamInUse


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


def _probe_fdk() -> bool:
    """Check once at import time whether libfdk_aac is compiled into FFmpeg."""
    try:
        result = subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=5,
        )
        return "libfdk_aac" in result.stdout
    except Exception:
        return False


# Cached once at startup — calling ffmpeg on every connect would be wasteful
try:
    _FDK_AVAILABLE: bool = _probe_fdk()
except Exception:
    _FDK_AVAILABLE = False


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
        self._sc2:               Optional[SC2Client]        = None   # live SC2 connection
        self._write_q:           queue.Queue                = queue.Queue(maxsize=self._QUEUE_SIZE)
        self._writer_thread:     Optional[threading.Thread] = None
        self._monitor_thread:    Optional[threading.Thread] = None
        self._relay_thread:      Optional[threading.Thread] = None   # SC2 stdout → socket
        self._running:           bool                       = False
        self._reconnect_count:   int                        = 0
        self._reconnecting:      bool                       = False  # guard against concurrent reconnects
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
        # Run _connect() on a background thread so the UI never blocks on the
        # socket handshake (10-second TCP timeout would freeze the main window).
        threading.Thread(
            target=self._connect, daemon=True, name=f"connect-{self._cfg.id}"
        ).start()

    def stop(self) -> None:
        self._running = False
        # Drain writer queue
        try:
            self._write_q.put_nowait(None)
        except queue.Full:
            pass
        self._set_status(SlotStatus.IDLE)
        # Kill on a background thread — proc.wait() must not block the UI thread.
        threading.Thread(
            target=self._kill_ffmpeg, daemon=True, name=f"stop-{self._cfg.id}"
        ).start()

    def feed(self, pcm: bytes) -> None:
        """Deliver a PCM chunk. Drops silently if queue is full.

        Accepted during CONNECTING as well as CONNECTED so that FFmpeg is
        already encoding while the SC2 handshake is in progress.
        """
        if self._status in (SlotStatus.CONNECTED, SlotStatus.CONNECTING):
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
        c = self._cfg

        if c.server_type == "shoutcast2":
            self._connect_sc2()
        else:
            self._connect_ffmpeg_icecast()

    def _connect_sc2(self) -> None:
        """SC2 / MRS path: uvox handshake in Python, FFmpeg outputs ADTS to stdout.

        Order matters: FFmpeg must be running and fed PCM *before* the SC2
        handshake completes so encoded audio is ready the instant we enter
        DATA_MODE.  MRS drops the connection if no audio arrives within ~2-3 s
        of the DATA_MODE ACK — and FFmpeg itself takes 1-2 s to initialize.
        """
        c = self._cfg
        sid = getattr(c, "stream_id", 1)

        # MRS SIDs are configured as AAC+ streams — always declare audio/aacp.
        # ADTS-framed AAC-LC is valid aacp content (base layer without SBR).
        # Sending audio/aac to an aacp SID causes the server to drop the feed.
        if c.format == "MP3":
            mime = "audio/mpeg"
        else:
            mime = "audio/aacp"   # AAC-LC or HE-AAC both declare aacp for MRS

        # ── 1. Launch FFmpeg FIRST so it is warm and has encoded frames
        #       buffered in its stdout pipe by the time we enter DATA_MODE.
        cmd = self._build_ffmpeg_cmd_sc2()
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,   # capture encoded audio
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except Exception as exc:
            self._log(f"[{c.name}] FFmpeg start failed: {exc}")
            self._set_status(SlotStatus.ERROR)
            self._maybe_reconnect()
            return

        # Start writer immediately — PCM flows into FFmpeg during the handshake.
        # feed() accepts chunks in both CONNECTING and CONNECTED states.
        self._writer_thread = threading.Thread(
            target=self._writer_loop, daemon=True, name=f"writer-{c.id}")
        self._writer_thread.start()

        # ── 2. SC2 handshake (FFmpeg is encoding in the background) ───
        sc2 = SC2Client(
            host          = c.server,
            port          = c.port,
            password      = c.password,
            sid           = sid,
            name          = c.station_name or c.name,
            genre         = c.genre,
            url           = c.url,
            content_type  = mime,
            sample_rate   = c.sample_rate,
            bitrate_kbps  = c.bitrate,
        )
        try:
            sc2.connect()
            self._sc2 = sc2
        except SC2StreamInUse as exc:
            self._log(f"[{c.name}] SC2 stream in use — waiting 35s for server to release SID {sid}…")
            sc2.close()
            self._kill_ffmpeg()
            self._set_status(SlotStatus.ERROR)
            self._maybe_reconnect(delay_override=35)
            return
        except (SC2Error, OSError) as exc:
            self._log(f"[{c.name}] SC2 handshake failed: {exc}")
            sc2.close()
            self._kill_ffmpeg()
            self._set_status(SlotStatus.ERROR)
            self._maybe_reconnect()
            return

        self._log(f"[{c.name}] Connected (SC2 uvox, SID {sid})")
        self._set_status(SlotStatus.CONNECTED)
        self._reconnect_count = 0

        # Relay starts here — FFmpeg has been encoding for the duration of the
        # handshake (~0.5-1 s), so the stdout pipe already has audio queued.
        self._relay_thread = threading.Thread(
            target=self._relay_loop, daemon=True, name=f"relay-{c.id}")
        self._relay_thread.start()

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name=f"monitor-{c.id}")
        self._monitor_thread.start()

    def _connect_ffmpeg_icecast(self) -> None:
        """Icecast / Shoutcast 1 path: FFmpeg handles streaming directly."""
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
                # Pipe broke — FFmpeg died or was killed.  The relay loop will
                # detect the EOF on stdout and handle the reconnect; don't
                # trigger a second concurrent reconnect from here.
                self._log(f"[{self._cfg.name}] Write error — pipe broken.")
                break

    def _monitor_loop(self) -> None:
        """Read FFmpeg stderr; log output only."""
        if not self._proc:
            return
        for raw_line in self._proc.stderr:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                self._log(f"[{self._cfg.name}] {line}")
        # FFmpeg exited — the relay loop will see EOF on stdout and reconnect.
        # Don't call _maybe_reconnect() here; that would race with the relay.

    def _maybe_reconnect(self, delay_override: int = 0) -> None:
        if not self._running or not self._cfg.auto_reconnect:
            return
        if self._reconnecting:
            return   # already queued — don't pile up concurrent reconnects
        max_a = self._cfg.reconnect_max
        if max_a > 0 and self._reconnect_count >= max_a:
            self._log(f"[{self._cfg.name}] Max reconnect attempts reached.")
            return
        self._reconnecting = True
        self._reconnect_count += 1
        delay = delay_override if delay_override > 0 else self._cfg.reconnect_delay
        self._log(
            f"[{self._cfg.name}] Reconnecting in {delay}s "
            f"(attempt {self._reconnect_count}"
            + (f"/{max_a}" if max_a > 0 else "") + ")…"
        )
        def _delayed():
            time.sleep(delay)
            self._reconnecting = False   # ← clear flag so future drops can reconnect
            if self._running:
                self._kill_ffmpeg()
                self._connect()
        threading.Thread(target=_delayed, daemon=True).start()

    def _relay_loop(self) -> None:
        """SC2 path: read encoded ADTS bytes from FFmpeg stdout, send to SC2 socket.

        Rate-limited to the configured bitrate.  Without this, pre-buffered audio
        (encoded during the SC2 handshake) floods the server at startup: the server
        enforces a bitrate window and drops the connection when it receives data
        significantly faster than the declared bitrate.
        """
        proc = self._proc
        sc2  = self._sc2
        name = self._cfg.name
        if not proc or not sc2:
            return

        # Bytes-per-second budget at the configured bitrate
        bps        = (self._cfg.bitrate * 1000) / 8.0
        t_start    = time.monotonic()
        sent_bytes = 0

        try:
            fd = proc.stdout.fileno()
            while self._running and proc and sc2:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                try:
                    sc2.send_audio(chunk)
                    sent_bytes += len(chunk)

                    # Throttle: if we're ahead of the bitrate budget, sleep it off.
                    elapsed = time.monotonic() - t_start
                    surplus = sent_bytes - bps * elapsed
                    if surplus > 0:
                        wait = surplus / bps
                        if wait > 0.005:
                            time.sleep(min(wait, 0.5))

                except OSError as exc:
                    self._log(f"[{name}] SC2 send error: {exc}")
                    break
        except Exception as exc:
            self._log(f"[{name}] SC2 relay error: {exc}")
        finally:
            if self._running:
                self._log(f"[{name}] SC2 relay ended — triggering reconnect")
                self._set_status(SlotStatus.ERROR)
                self._maybe_reconnect()

    def _kill_ffmpeg(self) -> None:
        # Close SC2 socket first so the relay thread unblocks
        sc2 = self._sc2
        self._sc2 = None
        if sc2:
            try:
                sc2.close()
            except Exception:
                pass

        proc = self._proc
        self._proc = None          # clear first to prevent race
        if proc:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.stdout.close()
            except Exception:
                pass
            try:
                proc.kill()        # SIGKILL — don't wait for graceful exit
            except Exception:
                pass
            try:
                proc.wait(timeout=2)   # reap the zombie; fast after kill
            except Exception:
                pass

    # ------------------------------------------------------------------
    # FFmpeg command builders
    # ------------------------------------------------------------------

    def _build_ffmpeg_cmd_sc2(self) -> list[str]:
        """FFmpeg command for SC2: encode to ADTS and write to stdout (pipe:1).
        The SC2 relay thread picks it up and sends it through the uvox socket.
        No icecast muxer, no URL — pure encode-only.
        """
        c       = self._cfg
        out_ch  = 2 if c.channels == "stereo" else 1
        in_ch   = c.source_channels or out_ch   # actual PCM channel count from device
        in_rate = c.source_sample_rate or c.sample_rate
        out_rate = c.sample_rate

        # Native AAC needs ≥32 kbps per channel — auto-downmix to mono when too low
        if c.format in ("AAC", "AAC+") and not self._fdk_available():
            if out_ch == 2 and c.bitrate < 64:
                out_ch = 1
                self._log(f"[{c.name}] Native AAC: {c.bitrate}k stereo too low — using mono")

        # INPUT spec must match actual PCM from the audio engine (in_ch / in_rate).
        # OUTPUT flags (after -i) tell FFmpeg the desired encode rate/channels,
        # triggering resampling and downmix automatically as needed.
        cmd = [
            ffmpeg_path(),
            "-hide_banner", "-loglevel", "warning",
            "-f",  "s16le",
            "-ar", str(in_rate),   # actual capture sample rate
            "-ac", str(in_ch),     # actual capture channel count
            "-i",  "pipe:0",
        ]

        # Output conversion flags (only add when different from input)
        if out_rate != in_rate:
            cmd += ["-ar", str(out_rate)]
        if out_ch != in_ch:
            cmd += ["-ac", str(out_ch)]

        if c.format == "AAC+" and self._fdk_available():
            # HE-AAC v2 (SBR + Parametric Stereo) for stereo < 48 kbps — matches
            # RadioCaster / BUTT profile selection (BUTT aac_encode.cpp: aot=29 for <48k).
            # HE-AAC v1 (SBR only) for higher bitrates or mono.
            if out_ch == 2 and c.bitrate < 48:
                he_profile = "aac_he_v2"
            else:
                he_profile = "aac_he"
            cmd += ["-c:a", "libfdk_aac", "-profile:a", he_profile,
                    "-b:a", f"{c.bitrate}k"]
        elif c.format == "AAC" and self._fdk_available():
            # fdk AAC-LC — better quality than native aac, handles low bitrates cleanly
            cmd += ["-c:a", "libfdk_aac", "-b:a", f"{c.bitrate}k"]
        elif c.format in ("AAC", "AAC+"):
            cmd += ["-c:a", "aac", "-b:a", f"{c.bitrate}k"]
        else:  # MP3
            cmd += ["-c:a", "libmp3lame", "-b:a", f"{c.bitrate}k", "-q:a", "0"]

        # Container format must match the codec
        if c.format == "MP3":
            cmd += ["-f", "mp3", "pipe:1"]
        else:
            cmd += ["-f", "adts", "pipe:1"]
        return cmd

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
            # HE-AAC (AAC+ / SBR) — use libfdk_aac if available, else native aac
            # Native FFmpeg AAC encoder does not support aac_he profile in most builds
            if self._fdk_available():
                cmd += ["-c:a", "libfdk_aac", "-profile:a", "aac_he", "-b:a", f"{c.bitrate}k"]
            else:
                # Fall back: native AAC at the requested bitrate, still tagged as aacp
                cmd += ["-c:a", "aac", "-b:a", f"{c.bitrate}k"]
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
        # SC1 needs legacy SOURCE method; SC2 never reaches here (uses _connect_sc2)
        extra: list[str] = []
        if c.server_type == "shoutcast1":
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
            # shoutcast2: should never reach here — handled by _connect_sc2()
            # Fallback just in case
            return f"icecast://source:{c.password}@{c.server}:{c.port}/"

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
        Shoutcast 2: GET /admin.cgi?mode=viewxml&page=2&sid=X  (stream stats)
        page=3 is the per-listener list — no aggregate count tags there.
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
                sid = getattr(c, "stream_id", 1)
                params = {"mode": "viewxml", "page": "2", "sid": sid, "pass": c.password}
                r = requests.get(url, params=params, timeout=3)
                result = _parse_shoutcast_xml(r.text)
                if "listeners" not in result:
                    # Log the raw response so we know what MRS is actually returning
                    preview = r.text[:400].replace("\n", " ").replace("\r", "")
                    self._log(f"[{c.name}] Stats XML (no listener tag): HTTP {r.status_code} — {preview}")
                return result
        except Exception as exc:
            self._log(f"[{c.name}] Stats fetch failed: {exc}")
            return {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fdk_available() -> bool:
        """Return True if this FFmpeg build includes libfdk_aac (cached)."""
        return _FDK_AVAILABLE

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
    """Extract listener counts from Shoutcast admin.cgi viewxml response.

    Handles both SHOUTcast DNAS 2 and MRS tag naming conventions.
    MRS wraps per-stream data inside <STREAM> elements; we scan the whole
    document with IGNORECASE so both ALLCAPS and lowercase variants match.
    """
    import re
    result = {}

    # Listener count — try standard DNAS tag first, then MRS variants
    for pattern in (
        r"<CURRENTLISTENERS>(\d+)</CURRENTLISTENERS>",
        r"<currentlisteners>(\d+)</currentlisteners>",
        r"<LISTENERS>(\d+)</LISTENERS>",
        r"<listeners>(\d+)</listeners>",
    ):
        m = re.search(pattern, xml, re.IGNORECASE)
        if m:
            result["listeners"] = int(m.group(1))
            break

    # Peak listener count
    for pattern in (
        r"<PEAKLISTENERS>(\d+)</PEAKLISTENERS>",
        r"<MAXLISTENERS>(\d+)</MAXLISTENERS>",
        r"<peaklisteners>(\d+)</peaklisteners>",
        r"<maxlisteners>(\d+)</maxlisteners>",
    ):
        m = re.search(pattern, xml, re.IGNORECASE)
        if m:
            result["peak"] = int(m.group(1))
            break

    # Song/stream title
    for pattern in (
        r"<SONGTITLE>(.*?)</SONGTITLE>",
        r"<TITLE>(.*?)</TITLE>",
        r"<STREAMTITLE>(.*?)</STREAMTITLE>",
    ):
        m = re.search(pattern, xml, re.IGNORECASE | re.DOTALL)
        if m:
            result["title"] = m.group(1).strip()
            break

    return result
