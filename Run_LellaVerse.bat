@echo off
title LellaVerse AI Shorts Builder - Next-Gen Edition
cd /d "%~dp0"

echo ================================================================
echo       LELLAVERSE AI SHORTS BUILDER - TURBO EDITION
echo       Fast 9:16 Shorts ^& Sinhala/English Dynamic Subtitles
echo ================================================================
echo.

REM 1. Locate FFmpeg or Auto-Add from WinGet package folder
where ffmpeg >nul 2>&1
if errorlevel 1 (
    for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*") do (
        if exist "%%D\ffmpeg-*\bin\ffmpeg.exe" (
            for /d %%B in ("%%D\ffmpeg-*\bin") do set "PATH=%%B;%PATH%"
        )
    )
)

where ffmpeg >nul 2>&1 || (
    echo [*] Installing FFmpeg multimedia engine via winget...
    winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    echo [*] FFmpeg installed. Please restart this launcher.
    pause & exit /b
)

REM 2. Virtual Environment Setup
if not exist "venv\Scripts\activate.bat" (
    echo [*] First-time setup: Creating Python virtual environment...
    python -m venv venv >nul 2>&1 || py -3 -m venv venv >nul 2>&1 || (
        echo [!] Python 3.10+ is required. Please install Python from python.org.
        pause & exit /b
    )
    call venv\Scripts\activate.bat
    echo [*] Installing optimized dependencies for your PC...
    python -m pip install --upgrade pip
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

REM 3. Launch App and Browser Window
echo [*] Launching LellaVerse AI Shorts Builder...
start "" /min "%~dp0open_browser.bat"
streamlit run app.py --server.headless true --browser.gatherUsageStats false
pause
