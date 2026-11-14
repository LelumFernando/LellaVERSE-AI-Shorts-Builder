@echo off
ping -n 6 127.0.0.1 >nul
set "B="
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "B=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not defined B if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "B=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not defined B if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "B=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined B if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "B=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined B if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "B=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not defined B goto fallback
start "" "%B%" --app=http://localhost:8501
exit /b
:fallback
start "" http://localhost:8501
