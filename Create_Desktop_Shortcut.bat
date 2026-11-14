@echo off
powershell -NoProfile -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\LellaVerse AI Shorts Builder.lnk');$s.TargetPath='%~dp0Run_LellaVerse.bat';$s.WorkingDirectory='%~dp0';$s.IconLocation='%~dp0assets\icon.ico';$s.Save()"
echo Desktop shortcut created!
pause
