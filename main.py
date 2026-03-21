#!/usr/bin/env python3
"""
STEAMING STREAM
Multi-bitrate audio encoder for internet broadcasters.

GPL v3 — https://github.com/baddaywithacamera/steamingstreamer
"""

import sys
from src.app import SteamingStreamApp


def main():
    app = SteamingStreamApp(sys.argv)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
