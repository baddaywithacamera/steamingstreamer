"""
mitm_proxy.py — SC2 protocol capture proxy
Sits between RadioCaster and MRS, relays everything transparently,
and hex-dumps both sides so we can reverse-engineer the handshake.

Usage:
  python tools/mitm_proxy.py <local_port> <remote_host> <remote_port>

Example (replace with your actual MRS host/port):
  python tools/mitm_proxy.py 8765 s25.myradiostream.com 10092

Then in RadioCaster set server = 127.0.0.1, port = 8765
RadioCaster will actually connect to MRS successfully (we just log everything).

Press Ctrl+C to stop.
"""

import socket
import threading
import sys
import time
import datetime

# ------------------------------------------------------------------
# Config from command line
# ------------------------------------------------------------------
if len(sys.argv) < 4:
    print("Usage: python mitm_proxy.py <local_port> <remote_host> <remote_port>")
    print("Example: python mitm_proxy.py 8765 s25.myradiostream.com 10092")
    sys.exit(1)

LOCAL_PORT   = int(sys.argv[1])
REMOTE_HOST  = sys.argv[2]
REMOTE_PORT  = int(sys.argv[3])

# How many bytes to hex-dump per direction (rest are relayed silently)
DUMP_BYTES = 4096

conn_counter = 0
lock = threading.Lock()

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def ts():
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

def hex_dump(data: bytes, prefix: str) -> None:
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_str  = " ".join(f"{b:02x}" for b in chunk)
        text_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"  {prefix} {i:04x}:  {hex_str:<48}  |{text_str}|")

# ------------------------------------------------------------------
# Per-connection relay
# ------------------------------------------------------------------

def relay(src: socket.socket, dst: socket.socket,
          label: str, dump_limit: int, conn_id: int) -> None:
    total = 0
    try:
        while True:
            data = src.recv(4096)
            if not data:
                break
            if total < dump_limit:
                cap = min(len(data), dump_limit - total)
                print(f"\n[{ts()}] [{conn_id}] {label}  ({len(data)} bytes)")
                hex_dump(data[:cap], "")
                if cap < len(data):
                    print(f"  ... (truncated, relaying remaining {len(data)-cap} bytes silently)")
            total += len(data)
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try: src.close()
        except: pass
        try: dst.close()
        except: pass

def handle_client(client_sock: socket.socket, addr: tuple) -> None:
    global conn_counter
    with lock:
        conn_counter += 1
        cid = conn_counter

    print(f"\n[{ts()}] [{cid}] >>> New connection from {addr}")

    try:
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.settimeout(10)
        server_sock.connect((REMOTE_HOST, REMOTE_PORT))
        server_sock.settimeout(None)
        print(f"[{ts()}] [{cid}]     Relaying → {REMOTE_HOST}:{REMOTE_PORT}")
    except Exception as e:
        print(f"[{ts()}] [{cid}]     FAILED to connect to server: {e}")
        client_sock.close()
        return

    t_up   = threading.Thread(
        target=relay,
        args=(client_sock, server_sock, "CLIENT → SERVER", DUMP_BYTES, cid),
        daemon=True,
    )
    t_down = threading.Thread(
        target=relay,
        args=(server_sock, client_sock, "SERVER → CLIENT", DUMP_BYTES, cid),
        daemon=True,
    )
    t_up.start()
    t_down.start()
    t_up.join()
    t_down.join()
    print(f"[{ts()}] [{cid}] <<< Connection closed: {addr}")

# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", LOCAL_PORT))
srv.listen(20)

print(f"MITM proxy  127.0.0.1:{LOCAL_PORT}  →  {REMOTE_HOST}:{REMOTE_PORT}")
print(f"Set RadioCaster:  Server = 127.0.0.1 / Port = {LOCAL_PORT}")
print(f"Hex-dumping first {DUMP_BYTES} bytes per direction per connection.")
print("=" * 65)

try:
    while True:
        conn, addr = srv.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        t.start()
except KeyboardInterrupt:
    print("\nProxy stopped.")
