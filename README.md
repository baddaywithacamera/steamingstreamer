# STEAMING STREAM

Multi-bitrate audio encoder and stream broadcaster for internet radio.
Broadcasts from any WASAPI audio source to Shoutcast 2 / Icecast servers.

Built as a free replacement for paid stream encoders, designed to work
alongside RadioDJ, StationPlaylist, and other playout software.

## Features

- Multi-stream encoding: AAC + MP3, multiple bitrates simultaneously
- WASAPI loopback capture on Windows (record system audio directly)
- Shoutcast 2, Shoutcast 1, and Icecast 2 server support
- Now-playing metadata from file, HTTP, or static text
- HTTP metadata API — accepts pushes from RadioDJ, StationPlaylist, etc.
- Scalable LED VU meters
- Dark-themed PyQt6 UI
- Config saved per-profile to `%APPDATA%\SteamingStream\`
- Single `.exe` distribution — no install required

## Requirements

- Windows 10/11 (primary target; Linux supported)
- Python 3.11+

```
pip install pyqt6 sounddevice numpy watchdog flask
```

## Running from source

```
python main.py
```

## Building the .exe

1. Drop `ffmpeg.exe` in the project root
   (get a static build from https://www.gyan.dev/ffmpeg/builds/ — essentials zip)

2. Install PyInstaller:
   ```
   pip install pyinstaller
   ```

3. Run:
   ```
   build.bat
   ```

Output: `dist\SteamingStream.exe` — fully self-contained, FFmpeg bundled.

## Metadata push (RadioDJ / StationPlaylist)

Point your playout software's "now playing" HTTP push at:

```
http://localhost:9000/metadata?song=Artist - Title&pass=yourpassword
```

Or with separate fields:

```
http://localhost:9000/api/metadata?title=Title&artist=Artist
```

Configure the port and password in Settings → API.

## License

GNU General Public License v3 — see [LICENSE](LICENSE).

Releases bundling FFmpeg include GPL-licensed components.
FFmpeg source: https://ffmpeg.org/download.html
Full third-party credits: [CREDITS](CREDITS)
