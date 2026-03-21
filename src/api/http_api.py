"""
STEAMING STREAM — RadioCaster-Compatible HTTP API
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

Exposes a small HTTP server that mirrors RadioCaster's metadata update API.
Any playout software that knows how to push metadata to RadioCaster
(RadioDJ, StationPlaylist, etc.) will work with STEAMING STREAM unchanged.

Endpoints:
  GET  /metadata?song=TITLE[&pass=PASSWORD]
       RadioDJ / SPL metadata push. Updates all connected streams.

  GET  /api/metadata?title=TITLE[&artist=ARTIST]
       Alternative form used by some playout tools.

  GET  /status
       Returns JSON with stream status, listener counts, current track.

  GET  /
       Health check — returns "STEAMING STREAM OK".

Runs in a daemon thread. Failure to bind is non-fatal (logged, app continues).
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

try:
    from flask import Flask, jsonify, request
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False


class HttpApi:
    """
    RadioCaster-compatible metadata ingestion API.

    Usage:
        api = HttpApi(port=9000, password="secret")
        api.set_on_metadata(lambda title: push_to_all_streams(title))
        api.start()
        ...
        api.stop()
    """

    def __init__(self, port: int = 9000, password: str = ""):
        self._port       = port
        self._password   = password
        self._thread:    Optional[threading.Thread] = None
        self._on_metadata: Optional[Callable[[str], None]] = None
        self._on_log:    Optional[Callable[[str], None]]   = None
        self._status_cb: Optional[Callable[[], dict]]      = None
        self._server     = None

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def set_on_metadata(self, cb: Callable[[str], None]) -> None:
        """Called with the new title whenever a metadata update arrives."""
        self._on_metadata = cb

    def set_on_log(self, cb: Callable[[str], None]) -> None:
        self._on_log = cb

    def set_status_provider(self, cb: Callable[[], dict]) -> None:
        """Called when /status is requested. Return a serialisable dict."""
        self._status_cb = cb

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not FLASK_AVAILABLE:
            self._log("Flask not available — HTTP API disabled.")
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="http-api"
        )
        self._thread.start()

    def stop(self) -> None:
        # Flask dev server can't be stopped cleanly — daemon thread exits with app
        pass

    # ------------------------------------------------------------------
    # Flask app
    # ------------------------------------------------------------------

    def _run(self) -> None:
        app = Flask("steaming-stream-api")
        app.logger.disabled = True

        # Suppress Flask startup banner
        import logging
        log = logging.getLogger("werkzeug")
        log.setLevel(logging.ERROR)

        # ----------------------------------------------------------------
        # Routes
        # ----------------------------------------------------------------

        @app.route("/")
        def health():
            return "STEAMING STREAM OK", 200

        @app.route("/metadata")
        def metadata_radiodj():
            """
            RadioDJ / RadioCaster format:
              GET /metadata?song=Artist - Title&pass=password
            """
            song = request.args.get("song", "").strip()
            pw   = request.args.get("pass", "")
            if self._password and pw != self._password:
                return "Unauthorized", 401
            if song:
                self._dispatch_metadata(song)
                return "OK", 200
            return "No song parameter", 400

        @app.route("/api/metadata")
        def metadata_alt():
            """
            Alternative form used by some playout tools:
              GET /api/metadata?title=Title&artist=Artist
            or
              GET /api/metadata?song=Artist - Title
            """
            song   = request.args.get("song", "").strip()
            title  = request.args.get("title", "").strip()
            artist = request.args.get("artist", "").strip()

            if not song:
                if artist and title:
                    song = f"{artist} - {title}"
                else:
                    song = title or artist

            if song:
                self._dispatch_metadata(song)
                return jsonify({"status": "ok", "title": song})
            return jsonify({"status": "error", "message": "no title"}), 400

        @app.route("/status")
        def status():
            data = self._status_cb() if self._status_cb else {}
            return jsonify(data)

        # ----------------------------------------------------------------

        try:
            self._log(f"HTTP API listening on http://localhost:{self._port}")
            app.run(
                host="0.0.0.0",
                port=self._port,
                debug=False,
                use_reloader=False,
            )
        except OSError as exc:
            self._log(f"HTTP API failed to bind on port {self._port}: {exc}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _dispatch_metadata(self, title: str) -> None:
        self._log(f"HTTP API metadata: {title}")
        if self._on_metadata:
            self._on_metadata(title)

    def _log(self, msg: str) -> None:
        if self._on_log:
            self._on_log(msg)
