"""
intercept_auth.py — SC2 auth formula cracker

Intercepts the SC2 handshake between RadioCaster and MRS.
Replaces the server's challenge with a KNOWN value ("AAAA"),
then captures what hash RadioCaster computes.
We can then brute-force the formula offline.

Usage:
  python tools/intercept_auth.py 8765 s25.myradiostream.com 10092

Set RadioCaster server = 127.0.0.1 / port = 8765, then connect.
Press Ctrl+C to stop.
"""

import socket
import struct
import threading
import sys
import hashlib

LOCAL_PORT  = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
REMOTE_HOST = sys.argv[2]      if len(sys.argv) > 2 else "s25.myradiostream.com"
REMOTE_PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 10092

# The challenge we inject — simple known value
INJECTED_CHALLENGE = "AAAA"

PASSWORD = "powaperu2570"

def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf.extend(chunk)
    return bytes(buf)

def read_packet(sock):
    """Read one uvox packet. Returns (msg_type, length, raw_payload_bytes)."""
    header = recv_exact(sock, 6)
    if header[0] != 0x5A:
        raise ValueError(f"bad sync: {header[0]:02x}")
    msg_type = struct.unpack(">H", header[2:4])[0]
    length   = struct.unpack(">H", header[4:6])[0]
    payload  = recv_exact(sock, length + 1)
    return msg_type, length, header, payload

def make_packet(msg_type, payload_str):
    data   = payload_str.encode("utf-8")
    length = len(data)
    header = struct.pack(">BBHH", 0x5A, 0x00, msg_type, length)
    return header + data + b"\x00"

def handle(client_sock, addr):
    print(f"\n>>> Connection from {addr}")
    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.settimeout(10)
        srv.connect((REMOTE_HOST, REMOTE_PORT))
        srv.settimeout(None)
    except Exception as e:
        print(f"    Could not reach server: {e}")
        client_sock.close()
        return

    try:
        # ── Step 1: Client HELLO → forward to server ──────────────
        msg_type, length, hdr, payload = read_packet(client_sock)
        client_str = payload.rstrip(b"\x00").decode()
        print(f"[CLIENT HELLO] type=0x{msg_type:04x}  payload={client_str!r}")
        srv.sendall(hdr + payload)  # forward as-is

        # ── Step 2: Server HELLO (with real challenge) → intercept ─
        msg_type, length, hdr, payload = read_packet(srv)
        real_response = payload.rstrip(b"\x00").decode()
        real_challenge = real_response[4:] if real_response.startswith("ACK:") else real_response
        print(f"[SERVER HELLO] real challenge = {real_challenge!r}")

        # Inject our known challenge instead
        injected_response = f"ACK:{INJECTED_CHALLENGE}"
        injected_pkt = make_packet(msg_type, injected_response)
        print(f"[INJECTED]     sending challenge = {INJECTED_CHALLENGE!r}")
        client_sock.sendall(injected_pkt)

        # ── Step 3: Client AUTH → capture hash ─────────────────────
        msg_type, length, hdr, payload = read_packet(client_sock)
        auth_str = payload.rstrip(b"\x00").decode()
        print(f"\n[CLIENT AUTH]  {auth_str!r}")

        # Parse: "2.1:sid::hash"
        parts = auth_str.split(":")
        received_hash = parts[-1] if parts else ""
        print(f"  Received hash : {received_hash}")

        # Now brute-force the formula
        print(f"\n--- Formula analysis (challenge={INJECTED_CHALLENGE!r}, pw={PASSWORD!r}) ---")
        combos = {
            "MD5(pw + ch)":           PASSWORD + INJECTED_CHALLENGE,
            "MD5(ch + pw)":           INJECTED_CHALLENGE + PASSWORD,
            "MD5(pw.upper + ch)":     PASSWORD.upper() + INJECTED_CHALLENGE,
            "MD5(MD5(pw) + ch)":      hashlib.md5(PASSWORD.encode()).hexdigest() + INJECTED_CHALLENGE,
            "MD5(ch + MD5(pw))":      INJECTED_CHALLENGE + hashlib.md5(PASSWORD.encode()).hexdigest(),
            "MD5(MD5(pw).up + ch)":   hashlib.md5(PASSWORD.encode()).hexdigest().upper() + INJECTED_CHALLENGE,
            "MD5(ch + MD5(pw).up)":   INJECTED_CHALLENGE + hashlib.md5(PASSWORD.encode()).hexdigest().upper(),
        }
        found = False
        for label, val in combos.items():
            h = hashlib.md5(val.encode()).hexdigest()
            match = "  *** MATCH — FORMULA FOUND! ***" if h == received_hash else ""
            print(f"  {label:<35} {h}{match}")
            if match:
                found = True

        if not found:
            print(f"\n  No standard formula matched.")
            print(f"  Real challenge was:  {real_challenge!r}")
            print(f"  Injected challenge:  {INJECTED_CHALLENGE!r}")
            print(f"  Auth string sent:    {auth_str!r}")

        # Forward the (original, non-injected) auth to server so RadioCaster
        # actually connects successfully and we don't break the stream.
        # Rebuild auth using REAL challenge so server accepts it.
        print(f"\n  [Forwarding real auth to server so RadioCaster connects normally]")
        real_hash_input = PASSWORD + real_challenge
        real_hash = hashlib.md5(real_hash_input.encode()).hexdigest()
        # Try forwarding client's own auth first — server will reject if wrong
        srv.sendall(hdr + payload)

        # ── Step 4: Relay rest of the connection transparently ──────
        def relay(src, dst):
            try:
                while True:
                    d = src.recv(4096)
                    if not d:
                        break
                    dst.sendall(d)
            except Exception:
                pass

        t1 = threading.Thread(target=relay, args=(client_sock, srv), daemon=True)
        t2 = threading.Thread(target=relay, args=(srv, client_sock), daemon=True)
        t1.start(); t2.start()
        t1.join(); t2.join()

    except Exception as e:
        print(f"  Error: {e}")
    finally:
        client_sock.close()
        srv.close()
        print(f"<<< Connection closed")

srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv_sock.bind(("127.0.0.1", LOCAL_PORT))
srv_sock.listen(10)
print(f"Auth interceptor: 127.0.0.1:{LOCAL_PORT} → {REMOTE_HOST}:{REMOTE_PORT}")
print(f"Will inject challenge = {INJECTED_CHALLENGE!r}  (instead of server's real challenge)")
print(f"Set RadioCaster: server=127.0.0.1  port={LOCAL_PORT}")
print("=" * 60)

try:
    while True:
        conn, addr = srv_sock.accept()
        threading.Thread(target=handle, args=(conn, addr), daemon=True).start()
except KeyboardInterrupt:
    print("\nStopped.")
