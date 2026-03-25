"""
sc2_diag.py — SC2 / MRS raw handshake diagnostic tool

Connects to your MRS server and shows EVERY byte exchanged during
the HELLO → AUTH sequence, so we can see exactly what challenge
the server is sending and whether our XTEA token matches.

Usage:
    python tools/sc2_diag.py <host> <port> <password> [sid]

Example:
    python tools/sc2_diag.py streaming.myradiostream.com 8000 powaperu2570 3
"""

import socket
import struct
import sys


# ── XTEA (exact copy from sc2_client.py) ─────────────────────────────────────

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


# ── Raw packet I/O ─────────────────────────────────────────────────────────────

def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError("Connection closed during recv")
        buf.extend(chunk)
    return bytes(buf)


def send_packet(sock, msg_type, payload_str):
    data   = payload_str.encode("utf-8")
    length = len(data)
    header = struct.pack(">BBHH", 0x5A, 0x00, msg_type, length)
    wire   = header + data + b"\x00"
    print(f"  >> SEND type=0x{msg_type:04X} len={length} payload={payload_str!r}")
    print(f"     hex: {wire.hex()}")
    sock.sendall(wire)


def recv_packet(sock):
    header = recv_exact(sock, 6)
    print(f"  << RECV header hex: {header.hex()}")
    if header[0] != 0x5A:
        raise RuntimeError(f"Bad sync byte: 0x{header[0]:02x}")
    msg_type = struct.unpack(">H", header[2:4])[0]
    length   = struct.unpack(">H", header[4:6])[0]
    print(f"     type=0x{msg_type:04X}  declared length={length}")

    # Strategy A: read exactly `length` bytes (no extra byte)
    raw_a = recv_exact(sock, length)
    # Peek at what the next byte is (the framing null, or possibly part of next packet)
    next_byte = recv_exact(sock, 1)

    print(f"     payload bytes ({length}): {raw_a.hex()}  = {raw_a!r}")
    print(f"     next byte after payload:  0x{next_byte[0]:02x}  (should be 0x00 null)")

    payload = raw_a.rstrip(b"\x00").decode("utf-8", errors="replace")
    print(f"     decoded payload: {payload!r}")

    if next_byte[0] != 0x00:
        print("  *** WARNING: byte after payload is NOT null — length field may include null!")
        print("      Challenge may have been mis-parsed. Adjusting...")
        # The length apparently included the null, so actual payload is length-1 bytes
        actual_payload = raw_a[:-1].decode("utf-8", errors="replace")
        print(f"      adjusted payload: {actual_payload!r}")

    return msg_type, payload


# ── Main diagnostic ────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    host     = sys.argv[1]
    port     = int(sys.argv[2])
    password = sys.argv[3]
    sid      = int(sys.argv[4]) if len(sys.argv) > 4 else 1

    print(f"\n{'='*60}")
    print(f"SC2 Diagnostic — {host}:{port}  SID={sid}  pw={password!r}")
    print(f"{'='*60}\n")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((host, port))
    print(f"[+] TCP connected to {host}:{port}\n")

    # ── HELLO ──────────────────────────────────────────────────────────
    print("--- STEP 1: HELLO ---")
    send_packet(sock, 0x1009, "2.1")
    _t, hello_resp = recv_packet(sock)
    print(f"\n  Parsed HELLO response: {hello_resp!r}")

    # Parse challenge
    if hello_resp.startswith("ACK:"):
        challenge = hello_resp[4:]
    else:
        challenge = hello_resp
    print(f"  Challenge string: {challenge!r}")
    print(f"  Challenge hex:    {challenge.encode('utf-8').hex()}\n")

    # ── Compute token ──────────────────────────────────────────────────
    token = _sc2_auth_token(password, challenge)
    print(f"--- STEP 2: AUTH ---")
    print(f"  Password:  {password!r}")
    print(f"  Challenge: {challenge!r}")
    print(f"  XTEA token: {token}")

    auth_payload = f"2.1:{sid}::{token}"
    send_packet(sock, 0x1001, auth_payload)
    _t, auth_resp = recv_packet(sock)
    print(f"\n  AUTH server response: {auth_resp!r}")

    if "Allow" in auth_resp:
        print("\n  *** AUTH ACCEPTED! ***")
    else:
        print("\n  *** AUTH REJECTED ***")
        print("\n  Trying alternate challenge parsings...")

        # Try without "ACK:" prefix at all
        for alt_challenge in [hello_resp, hello_resp.strip(), hello_resp.rstrip("\x00")]:
            alt_token = _sc2_auth_token(password, alt_challenge)
            print(f"    challenge={alt_challenge!r}  =>  {alt_token}")

    sock.close()
    print("\n[+] Done.")


if __name__ == "__main__":
    main()
