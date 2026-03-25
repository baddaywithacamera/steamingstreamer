"""
sc2_stream_test.py — Minimal SC2 streaming test (no app, no WASAPI)

Bypasses the full application and streams a generated sine wave directly
to the MRS server to isolate whether the 10053 drops are in the app layer
or in the SC2 protocol / network layer.

Usage:
    python tools/sc2_stream_test.py <host> <port> <password> <sid>

Example:
    python tools/sc2_stream_test.py s25.myradiostream.com 10092 yourpassword 3

What it does:
  1. Full SC2 uvox handshake (same as sc2_client.py)
  2. Starts FFmpeg with a GENERATED 440 Hz sine wave (no capture device needed)
  3. Streams HE-AAC v2 ADTS to the server
  4. Reports elapsed time every second and any errors
  5. Runs for 60 seconds or until dropped
"""

import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time


# ── XTEA (copy from sc2_client.py) ────────────────────────────────────────────

def _xtea_enc_block(block: bytes, key: bytes) -> bytes:
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
    key = (challenge.encode("utf-8") + b"\x00" * 16)[:16]
    pt  = (password.encode("utf-8")  + b"\x00" * 16)[:16]
    ct  = _xtea_enc_block(pt[:8], key) + _xtea_enc_block(pt[8:], key)
    return ct.hex()


# ── Packet I/O ────────────────────────────────────────────────────────────────

def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError("Connection closed during recv")
        buf.extend(chunk)
    return bytes(buf)


def send_pkt(sock, msg_type, payload):
    data   = payload.encode("utf-8")
    header = struct.pack(">BBHH", 0x5A, 0x00, msg_type, len(data))
    sock.sendall(header + data + b"\x00")


def recv_pkt(sock):
    header   = recv_exact(sock, 6)
    msg_type = struct.unpack(">H", header[2:4])[0]
    length   = struct.unpack(">H", header[4:6])[0]
    raw      = recv_exact(sock, length + 1)
    payload  = raw.rstrip(b"\x00").decode("utf-8", errors="replace")
    return msg_type, payload


def exchange(sock, msg_type, payload):
    send_pkt(sock, msg_type, payload)
    _, resp = recv_pkt(sock)
    return resp


# ── Handshake ─────────────────────────────────────────────────────────────────

def handshake(sock, password, sid, sample_rate=44100, bitrate_kbps=32):
    # HELLO
    send_pkt(sock, 0x1009, "2.1")
    _, resp = recv_pkt(sock)
    if not resp.startswith("ACK:"):
        raise RuntimeError(f"HELLO rejected: {resp!r}")
    challenge = resp[4:]
    print(f"  HELLO OK  challenge={challenge!r}")

    # AUTH
    token = _sc2_auth_token(password.strip(), challenge)
    send_pkt(sock, 0x1001, f"2.1:{sid}::{token}")
    _, resp = recv_pkt(sock)
    if "Allow" not in resp:
        raise RuntimeError(f"AUTH rejected: {resp!r}")
    print(f"  AUTH OK   response={resp!r}")

    # Stream config
    exchange(sock, 0x1040, "audio/aacp")
    exchange(sock, 0x1002, f"{sample_rate}:{sample_rate}")
    exchange(sock, 0x1008, f"{bitrate_kbps * 1000}:0")
    exchange(sock, 0x1100, "SC2 Stream Test")
    exchange(sock, 0x1101, "Test")
    exchange(sock, 0x1102, "http://localhost")
    exchange(sock, 0x1103, "0")
    exchange(sock, 0x1006, "")

    # DATA_MODE
    send_pkt(sock, 0x1004, "")
    _, resp = recv_pkt(sock)
    if "Data transfer mode" not in resp:
        raise RuntimeError(f"DATA_MODE rejected: {resp!r}")
    print(f"  DATA_MODE OK")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)

    host         = sys.argv[1]
    port         = int(sys.argv[2])
    password     = sys.argv[3]
    sid          = int(sys.argv[4])
    sample_rate  = int(sys.argv[5]) if len(sys.argv) > 5 else 44100
    bitrate_kbps = int(sys.argv[6]) if len(sys.argv) > 6 else 32
    duration_s   = int(sys.argv[7]) if len(sys.argv) > 7 else 60

    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"

    print(f"\nSC2 Stream Test  {host}:{port}  SID={sid}")
    print(f"Format: AAC+ (HE-AAC v2)  {bitrate_kbps}kbps  {sample_rate}Hz stereo")
    print(f"Source: generated 440 Hz sine wave  Duration: {duration_s}s\n")

    # ── TCP connect + handshake ───────────────────────────────────────────
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((host, port))
    sock.settimeout(None)
    print(f"TCP connected to {host}:{port}")

    try:
        handshake(sock, password, sid, sample_rate, bitrate_kbps)
    except Exception as exc:
        print(f"HANDSHAKE FAILED: {exc}")
        sock.close()
        sys.exit(1)

    # ── Start FFmpeg with a generated sine wave (no capture device) ───────
    # lavfi sine source: infinite 440 Hz tone at 44100 Hz stereo
    cmd = [
        ffmpeg,
        "-hide_banner", "-loglevel", "warning",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:sample_rate={sample_rate}:duration={duration_s}",
        "-ac", "2",                           # stereo
        "-c:a", "libfdk_aac",
        "-profile:a", "aac_he_v2",
        "-b:a", f"{bitrate_kbps}k",
        "-f", "adts",
        "pipe:1",
    ]
    print(f"\nFFmpeg cmd: {' '.join(cmd)}\n")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    # Stderr logger
    def log_stderr():
        for line in proc.stderr:
            print(f"  [ffmpeg] {line.decode('utf-8', errors='replace').strip()}")
    threading.Thread(target=log_stderr, daemon=True).start()

    # ── Relay loop ────────────────────────────────────────────────────────
    start = time.time()
    bytes_sent = 0
    last_report = 0
    fd = proc.stdout.fileno()

    print("Streaming... (Ctrl+C to stop)\n")
    try:
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                print(f"\nFFmpeg finished after {time.time()-start:.1f}s")
                break
            sock.sendall(chunk)
            bytes_sent += len(chunk)

            elapsed = time.time() - start
            if int(elapsed) > last_report:
                last_report = int(elapsed)
                print(f"  t={elapsed:5.1f}s  sent={bytes_sent//1024}KB  "
                      f"rate={bytes_sent*8/elapsed/1000:.1f}kbps")

    except OSError as exc:
        elapsed = time.time() - start
        print(f"\n*** CONNECTION DROPPED at t={elapsed:.1f}s: {exc}")
        print(f"    Sent {bytes_sent} bytes ({bytes_sent*8/1000:.0f}kbits) before drop")
    except KeyboardInterrupt:
        elapsed = time.time() - start
        print(f"\nStopped by user at t={elapsed:.1f}s  sent={bytes_sent//1024}KB")
    finally:
        proc.kill()
        sock.close()
        print("\nDone.")


if __name__ == "__main__":
    main()
