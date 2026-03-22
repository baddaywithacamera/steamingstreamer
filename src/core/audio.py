"""
STEAMING STREAM — Audio Capture Engine
GPL v3 — https://github.com/baddaywithacamera/steamingstreamer

Captures audio from a system device (WASAPI loopback on Windows,
PulseAudio monitor on Linux) and distributes raw PCM to encoder slots.

PCM format: 16-bit signed int, little-endian, interleaved stereo.
This matches what FFmpeg expects on stdin with -f s16le.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Callable, Optional

try:
    import numpy as np
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Device info
# ---------------------------------------------------------------------------

@dataclass
class DeviceInfo:
    index:       int
    name:        str
    channels:    int
    sample_rate: float
    is_loopback: bool = False

    def display_name(self) -> str:
        tag = "  [loopback]" if self.is_loopback else ""
        return f"{self.name}{tag}"


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class AudioEngine:
    """
    Captures audio from one device and distributes raw PCM to all
    registered encoder slots via their feed() method.

    Level callbacks fire on the audio thread — use Qt queued connections
    or thread-safe signals to update the UI.
    """

    def __init__(self):
        self._stream = None
        self._slots:    list     = []
        self._running:  bool     = False
        self._on_level: Optional[Callable[[float, float], None]] = None
        self._on_log:   Optional[Callable[[str], None]]          = None

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def set_on_level(self, cb: Callable[[float, float], None]) -> None:
        """cb(left_rms, right_rms) — called on audio thread at ~30fps."""
        self._on_level = cb

    def set_on_log(self, cb: Callable[[str], None]) -> None:
        self._on_log = cb

    # ------------------------------------------------------------------
    # Slot management
    # ------------------------------------------------------------------

    def add_slot(self, slot) -> None:
        self._slots.append(slot)

    def clear_slots(self) -> None:
        self._slots.clear()

    # ------------------------------------------------------------------
    # Device enumeration
    # ------------------------------------------------------------------

    @staticmethod
    def list_devices() -> list[DeviceInfo]:
        """Return all usable input devices, loopback devices first."""
        if not SOUNDDEVICE_AVAILABLE:
            return []

        results: list[DeviceInfo] = []
        loopbacks: list[DeviceInfo] = []

        try:
            all_devs = sd.query_devices()
        except Exception:
            return []

        for i, d in enumerate(all_devs):
            name = d["name"]
            is_loopback = "loopback" in name.lower()

            if d["max_input_channels"] > 0:
                dev = DeviceInfo(
                    index=i,
                    name=name,
                    channels=d["max_input_channels"],
                    sample_rate=d["default_samplerate"],
                    is_loopback=is_loopback,
                )
                if is_loopback:
                    loopbacks.append(dev)
                else:
                    results.append(dev)

            elif platform.system() == "Windows" and d["max_output_channels"] > 0:
                # Offer output devices as WASAPI loopback candidates
                loopbacks.append(DeviceInfo(
                    index=i,
                    name=name,
                    channels=min(d["max_output_channels"], 2),
                    sample_rate=d["default_samplerate"],
                    is_loopback=True,
                ))

        return loopbacks + results

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------

    def start(
        self,
        device_index:    int,
        sample_rate:     int  = 44100,
        channels:        int  = 2,
        buffer_size:     int  = 1024,
        is_loopback:     bool = False,
    ) -> None:
        if not SOUNDDEVICE_AVAILABLE:
            self._log("sounddevice not available — audio capture disabled.")
            return

        self._running = True

        kwargs: dict = dict(
            device=device_index if device_index >= 0 else None,
            samplerate=float(sample_rate),
            channels=channels,
            dtype="int16",
            blocksize=buffer_size,
            callback=self._callback,
        )

        # WASAPI loopback on Windows
        if is_loopback and platform.system() == "Windows":
            try:
                kwargs["extra_settings"] = sd.WasapiSettings(loopback=True)
            except (AttributeError, TypeError):
                pass  # Device is already a loopback input, or sounddevice version
                      # doesn't support the loopback flag — open it normally

        try:
            self._stream = sd.InputStream(**kwargs)
            self._stream.start()
            self._log(
                f"Audio capture started — device {device_index}, "
                f"{sample_rate} Hz, {channels}ch."
            )
        except Exception as exc:
            self._running = False
            self._log(f"Audio capture failed to start: {exc}")
            raise

    def stop(self) -> None:
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._log("Audio capture stopped.")

    # ------------------------------------------------------------------
    # Audio callback (runs on sounddevice audio thread)
    # ------------------------------------------------------------------

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            self._log(f"Audio buffer: {status}")

        raw = bytes(indata)

        # Level metering (RMS per channel)
        if self._on_level and SOUNDDEVICE_AVAILABLE:
            try:
                arr = indata.astype(np.float32) / 32768.0
                if arr.shape[1] >= 2:
                    l_rms = float(np.sqrt(np.mean(arr[:, 0] ** 2)))
                    r_rms = float(np.sqrt(np.mean(arr[:, 1] ** 2)))
                else:
                    v = float(np.sqrt(np.mean(arr ** 2)))
                    l_rms = r_rms = v
                # Boost RMS to approximate VU meter response
                l_rms = min(1.0, l_rms * 3.0)
                r_rms = min(1.0, r_rms * 3.0)
                self._on_level(l_rms, r_rms)
            except Exception:
                pass

        # Distribute PCM to encoder slots
        for slot in self._slots:
            slot.feed(raw)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        if self._on_log:
            self._on_log(msg)
