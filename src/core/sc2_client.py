"""
sc2_client.py — Shoutcast 2 / MRS uvox binary protocol client

Protocol reverse-engineered from MITM capture (March 2026).

Packet wire format
------------------
  [0x5A] [0x00] [type_hi] [type_lo] [len_hi] [len_lo]   ← 6-byte header
  [len bytes of string payload]                           ← string, NO null
  [0x00]                                                  ← framing null byte

  length field = len(string payload)  (does NOT include the framing null)

Handshake sequence (client → server, server → client)
------------------------------------------------------
  0x1009  HELLO       "2.1"                          →  "ACK:<challenge>"
  0x1001  AUTH        "2.1:<sid>::<MD5(pw+ch)>"      →  "ACK:2.1:Allow"
  0x1040  MIME        "audio/aacp"                   →  "ACK"
  0x1002  SAMPLERATE  "<rate>:<rate>"                →  "ACK"
  0x1008  BITRATE     "<bps>:0"                      →  "ACK"
  0x1100  NAME        stream name                    →  "ACK"
  0x1101  GENRE       genre                          →  "ACK"
  0x1102  URL         website URL                    →  "ACK"
  0x1103  PUBLIC      "0" or "1"                     →  "ACK"
  0x1006  READY       ""                             →  "ACK"
  0x1004  DATA_MODE   ""                             →  "ACK:Data transfer mode"

After DATA_MODE ACK: raw encoded audio bytes flow directly on the socket.
"""

import logging
import struct
import socket

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Message type constants  (all captured from live RadioCaster ↔ MRS exchange)
# ---------------------------------------------------------------------------
_HELLO      = 0x1009
_AUTH       = 0x1001
_MIME       = 0x1040
_SAMPLERATE = 0x1002
_BITRATE    = 0x1008
_NAME       = 0x1100
_GENRE      = 0x1101
_URL        = 0x1102
_PUBLIC     = 0x1103
_READY      = 0x1006
_DATA_MODE  = 0x1004

# Audio data frame types (Ultravox class + type, per spec §8 / Netshout MessageFlag.cs)
_MP3_DATA    = 0x7000   # class 0x7, type 0x000 — audio/mpeg
_AAC_LC_DATA = 0x8001   # class 0x8, type 0x001 — audio/aac  (AAC-LC)
_AACP_DATA   = 0x8003   # class 0x8, type 0x003 — audio/aacp (HE-AAC v1/v2)

# Hard limit from spec: 16 * 1024 – 6 (header) – 1 (trailer) = 16377 bytes
_MAX_PAYLOAD = 16377

_PROTOCOL_VERSION = "2.1"


# ---------------------------------------------------------------------------
# XTEA cipher (SC2 uvox auth — NOT MD5!)
# Key = challenge zero-padded to 16 bytes
# Plaintext = password zero-padded to 16 bytes, split into two 8-byte blocks
# Byte order: big-endian; 32 rounds
# ---------------------------------------------------------------------------

def _xtea_enc_block(block: bytes, key: bytes) -> bytes:
    """Encrypt one 8-byte block with a 16-byte key (big-endian, 32 rounds)."""
    v0, v1 = struct.unpack(">II", block)
    k0, k1, k2, k3 = struct.unpack(">IIII", key)
    k = (k0, k1, k2, k3)
    delta = 0x9E3779B9
    s     = 0
    mask  = 0xFFFFFFFF
    for _ in range(32):
        v0 = (v0 + (((v1 << 4 ^ v1 >> 5) + v1) ^ (s + k[s & 3])))        & mask
        s  = (s + delta)                                                    & mask
        v1 = (v1 + (((v0 << 4 ^ v0 >> 5) + v0) ^ (s + k[s >> 11 & 3])))  & mask
    return struct.pack(">II", v0, v1)


def _sc2_auth_token(password: str, challenge: str) -> str:
    """Return the 32-char hex auth token used in the SC2 uvox AUTH packet.

    Formula (verified against live RadioCaster ↔ MRS capture):
      key       = challenge encoded as UTF-8, zero-padded to 16 bytes
      plaintext = password  encoded as UTF-8, zero-padded to 16 bytes
      ciphertext = XTEA_BE_32rounds(plaintext[:8], key)
                 + XTEA_BE_32rounds(plaintext[8:], key)
      token = ciphertext.hex()
    """
    key = (challenge.encode("utf-8") + b"\x00" * 16)[:16]
    pt  = (password.encode("utf-8")  + b"\x00" * 16)[:16]
    ct  = _xtea_enc_block(pt[:8], key) + _xtea_enc_block(pt[8:], key)
    return ct.hex()


# ---------------------------------------------------------------------------
class SC2Error(OSError):
    """Raised when the server rejects a handshake step or the connection drops."""

class SC2StreamInUse(SC2Error):
    """Server returned NAK:Stream In Use — SID is still held from a prior session."""


# ---------------------------------------------------------------------------
class SC2Client:
    """
    Minimal Shoutcast 2 (uvox) source encoder client.

    Usage::

        client = SC2Client(host, port, password, sid=3,
                           name="Squirrel FM", genre="Pop",
                           url="http://squirrelfm.ca",
                           content_type="audio/aacp",
                           sample_rate=32000, bitrate_kbps=32)
        client.connect()          # performs full handshake
        client.send_audio(data)   # call repeatedly with encoded audio bytes
        client.close()
    """

    def __init__(
        self,
        host: str,
        port: int,
        password: str,
        sid: int,
        name: str,
        genre: str,
        url: str,
        content_type: str,
        sample_rate: int,
        bitrate_kbps: int,
    ) -> None:
        self.host          = host
        self.port          = port
        self.password      = password.strip()   # guard against paste-in newlines
        self.sid           = sid
        self.name          = name or "STEAMING STREAM"
        self.genre         = genre or "Unknown"
        self.url           = url   or "http://localhost"
        self.content_type  = content_type
        self.sample_rate   = sample_rate
        self.bitrate_kbps  = bitrate_kbps
        self._sock: socket.socket | None = None

        # Derive the Ultravox audio data frame type from the declared MIME type
        if content_type == "audio/mpeg":
            self._audio_msg_type = _MP3_DATA
        elif content_type == "audio/aac":
            self._audio_msg_type = _AAC_LC_DATA
        else:                              # audio/aacp — HE-AAC v1 and v2
            self._audio_msg_type = _AACP_DATA

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open TCP connection and perform the full uvox handshake.

        Raises SC2Error if any step is rejected by the server.
        """
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(10)
        self._sock.connect((self.host, self.port))
        self._sock.settimeout(None)
        log.debug("SC2 TCP connected to %s:%d", self.host, self.port)

        # ── 1. Version hello ──────────────────────────────────────────
        self._send(_HELLO, _PROTOCOL_VERSION)
        _t, resp = self._recv()
        if not resp.startswith("ACK:"):
            raise SC2Error(f"SC2 HELLO rejected by server: {resp!r}")
        challenge = resp[4:]   # everything after "ACK:"
        log.debug("SC2 challenge: %r", challenge)

        # ── 2. Authentication — XTEA cipher, NOT MD5 ─────────────────
        token = _sc2_auth_token(self.password, challenge)
        self._send(_AUTH, f"{_PROTOCOL_VERSION}:{self.sid}::{token}")
        _t, resp = self._recv()
        if "Allow" not in resp:
            raise SC2Error(f"SC2 AUTH rejected: {resp!r}")
        log.debug("SC2 authenticated: %r", resp)

        # ── 3. Stream configuration ───────────────────────────────────
        self._exchange(_MIME,       self.content_type)
        self._exchange(_SAMPLERATE, f"{self.sample_rate}:{self.sample_rate}")
        self._exchange(_BITRATE,    f"{self.bitrate_kbps * 1000}:0")
        self._exchange(_NAME,       self.name)
        self._exchange(_GENRE,      self.genre)
        self._exchange(_URL,        self.url)
        self._exchange(_PUBLIC,     "0")
        self._exchange(_READY,      "")

        # ── 4. Enter data transfer mode ───────────────────────────────
        self._send(_DATA_MODE, "")
        _t, resp = self._recv()
        if "Stream In Use" in resp:
            raise SC2StreamInUse(f"SC2 DATA_MODE rejected: {resp!r}")
        if "Data transfer mode" not in resp:
            raise SC2Error(f"SC2 DATA_MODE rejected: {resp!r}")
        log.debug("SC2 handshake complete — streaming active")

    def send_audio(self, data: bytes) -> None:
        """Wrap encoded audio in Ultravox data frames and send.

        Every byte on this socket must be inside an Ultravox message — the
        server ignores raw bytes and will idle-timeout if it never receives
        valid framed data messages (spec §6.2 Idle Timeout).

        Chunks larger than _MAX_PAYLOAD (16377 bytes) are split into multiple
        frames; in practice os.read(fd, 4096) chunks are always well under
        that limit so this is just a safety rail.
        """
        if not self._sock:
            return
        offset = 0
        while offset < len(data):
            chunk = data[offset : offset + _MAX_PAYLOAD]
            self._sock.sendall(self._frame(self._audio_msg_type, chunk))
            offset += len(chunk)

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
            log.debug("SC2 connection closed")

    # ------------------------------------------------------------------
    # Packet I/O
    # ------------------------------------------------------------------

    def _frame(self, msg_type: int, payload: bytes) -> bytes:
        """Build one Ultravox frame around a binary payload (audio data)."""
        header = struct.pack(">BBHH", 0x5A, 0x00, msg_type, len(payload))
        return header + payload + b"\x00"

    def _send(self, msg_type: int, payload: str) -> None:
        """Build and send one uvox control packet (string payload)."""
        data   = payload.encode("utf-8")
        length = len(data)                      # excludes framing null
        header = struct.pack(">BBHH", 0x5A, 0x00, msg_type, length)
        self._sock.sendall(header + data + b"\x00")

    def _recv(self) -> tuple[int, str]:
        """Read one uvox control packet, return (msg_type, payload_str)."""
        header = self._recv_exact(6)
        if header[0] != 0x5A:
            raise SC2Error(f"SC2 bad sync byte: 0x{header[0]:02x}")
        msg_type = struct.unpack(">H", header[2:4])[0]
        length   = struct.unpack(">H", header[4:6])[0]
        # Read length+1 bytes: covers both "length includes null" and
        # "length excludes null" server conventions; strip all trailing nulls.
        raw      = self._recv_exact(length + 1)
        payload  = raw.rstrip(b"\x00").decode("utf-8", errors="replace")
        return msg_type, payload

    def _exchange(self, msg_type: int, payload: str) -> str:
        """Send a packet and return the server's ACK payload."""
        self._send(msg_type, payload)
        _t, resp = self._recv()
        return resp

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise SC2Error("SC2 connection closed during recv")
            buf.extend(chunk)
        return bytes(buf)
