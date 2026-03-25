"""
capture_source.py — Fake Shoutcast/Icecast listener
Prints the raw SOURCE handshake sent by any encoder (RadioCaster, STEAMING STREAM, etc.)
then closes the connection.

Usage:
  python tools/capture_source.py [port]   (default port: 8765)

In RadioCaster (or STEAMING STREAM):
  Server:  127.0.0.1
  Port:    8765   (or whatever you chose)
  Keep all other settings the same (password, SID, bitrate, etc.)

Press Ctrl+C to stop.
"""

import socket
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

def run():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", PORT))
    srv.listen(5)
    print(f"Listening on 127.0.0.1:{PORT}  — point your encoder here")
    print("=" * 60)

    while True:
        conn, addr = srv.accept()
        print(f"\n>>> Connection from {addr}")
        data = b""
        conn.settimeout(3.0)
        try:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                # Stop reading after the HTTP header block (blank line)
                if b"\r\n\r\n" in data:
                    break
        except socket.timeout:
            pass

        print("--- RAW REQUEST (hex + text) ---")
        for line in data.split(b"\n"):
            stripped = line.rstrip(b"\r")
            try:
                print(" ", stripped.decode("utf-8"))
            except UnicodeDecodeError:
                print(" ", stripped.hex())
        print("--- END ---")

        # Send a minimal ICY 200 OK so the encoder thinks it connected
        # (lets us see if it sends anything after the headers too)
        try:
            conn.sendall(b"ICY 200 OK\r\n\r\n")
            # Drain a bit more to catch any post-header data
            conn.settimeout(2.0)
            extra = b""
            try:
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    extra += chunk
                    if len(extra) > 512:   # first ~512 bytes of audio is plenty
                        break
            except socket.timeout:
                pass
            if extra:
                print(f"[{len(extra)} bytes of audio data followed — encoder thinks it's live]")
        except Exception:
            pass
        finally:
            conn.close()

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\nStopped.")
