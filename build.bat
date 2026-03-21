@echo off
REM STEAMING STREAM — Windows build script
REM Produces a single SteamingStream.exe in dist\
REM
REM Requirements:
REM   pip install pyinstaller pyqt6 sounddevice numpy watchdog flask
REM
REM FFmpeg:
REM   Drop ffmpeg.exe in this folder before building.
REM   Get a static build from: https://www.gyan.dev/ffmpeg/builds/
REM   (ffmpeg-release-essentials.zip -> bin\ffmpeg.exe)

echo ============================================================
echo  STEAMING STREAM build
echo ============================================================

REM Check for ffmpeg.exe
if not exist ffmpeg.exe (
    echo.
    echo WARNING: ffmpeg.exe not found in project root.
    echo The .exe will require FFmpeg installed on PATH at runtime.
    echo To bundle FFmpeg, place ffmpeg.exe here before building.
    echo.
)

REM Check for PyInstaller
pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: PyInstaller not found. Run:
    echo   pip install pyinstaller
    exit /b 1
)

echo Cleaning previous build...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo Building...
pyinstaller steamingstream.spec

if errorlevel 1 (
    echo.
    echo BUILD FAILED. Check output above.
    exit /b 1
)

echo.
echo ============================================================
echo  Done!  dist\SteamingStream.exe
echo ============================================================
pause
