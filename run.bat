@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Animal TV Generator
where python >nul 2>nul || (echo Chua cai Python 3.10+. Tai tai https://www.python.org/downloads/ & pause & exit /b 1)
if not exist ".deps_ok" (
  echo Dang cai thu vien lan dau...
  python -m pip install -r requirements.txt || (pause & exit /b 1)
  echo ok> .deps_ok
)
where ffmpeg >nul 2>nul || if not exist "bin\ffmpeg.exe" (
  python -c "from app import ffmpeg_util as f; f.ffmpeg()" 2>nul || (
    echo Chua co FFmpeg, dang cai bang winget...
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
  )
)
echo Mo http://localhost:8765  (dong cua so nay de tat tool)
python -m app.main
pause
