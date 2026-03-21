# -*- mode: python ; coding: utf-8 -*-
#
# STEAMING STREAM — PyInstaller spec
# GPL v3 — https://github.com/baddaywithacamera/steamingstreamer
#
# Build:
#   pyinstaller steamingstream.spec
#
# The output is a single .exe in dist/
# FFmpeg must be placed in the project root (or tools/) before building:
#   Windows: ffmpeg.exe
#   Linux:   ffmpeg
#
# To grab a static FFmpeg build:
#   Windows: https://www.gyan.dev/ffmpeg/builds/  (ffmpeg-release-essentials.zip)
#   Linux:   https://johnvansickle.com/ffmpeg/

import os
import sys
from pathlib import Path

block_cipher = None

# ---------------------------------------------------------------------------
# Locate bundled FFmpeg binary
# ---------------------------------------------------------------------------

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))

_ffmpeg_candidates = [
    os.path.join(SPEC_DIR, "ffmpeg.exe"),
    os.path.join(SPEC_DIR, "ffmpeg"),
    os.path.join(SPEC_DIR, "tools", "ffmpeg.exe"),
    os.path.join(SPEC_DIR, "tools", "ffmpeg"),
]

_ffmpeg_src = None
for _c in _ffmpeg_candidates:
    if os.path.isfile(_c):
        _ffmpeg_src = _c
        break

if _ffmpeg_src is None:
    print(
        "\n"
        "WARNING: ffmpeg binary not found in project root or tools/.\n"
        "The built .exe will require FFmpeg to be installed on PATH.\n"
        "To bundle FFmpeg, place ffmpeg.exe (Windows) or ffmpeg (Linux)\n"
        "in the project root before running PyInstaller.\n"
    )
    binaries = []
else:
    binaries = [(_ffmpeg_src, ".")]
    print(f"Bundling FFmpeg from: {_ffmpeg_src}")

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

a = Analysis(
    ["main.py"],
    pathex=[SPEC_DIR],
    binaries=binaries,
    datas=[],
    hiddenimports=[
        # sounddevice needs these at runtime
        "sounddevice",
        "cffi",
        "_cffi_backend",
        # Flask / Werkzeug internals
        "flask",
        "werkzeug",
        "werkzeug.serving",
        "werkzeug.debug",
        "jinja2",
        "click",
        # requests
        "requests",
        "urllib3",
        "charset_normalizer",
        "certifi",
        "idna",
        # numpy
        "numpy",
        "numpy.core._multiarray_umath",
        # PyQt6 platform plugin (Windows)
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "scipy",
        "pandas",
        "PIL",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ---------------------------------------------------------------------------
# Single-file executable
# ---------------------------------------------------------------------------

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="SteamingStream",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,         # no console window (windowed app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="assets/icon.ico",  # uncomment when icon is ready
)
