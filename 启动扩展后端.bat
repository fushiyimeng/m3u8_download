@echo off
chcp 65001 >nul
cd /d "%~dp0"
title m3u8 local receiver (127.0.0.1:18888)
echo.
echo   m3u8 local receiver for browser extension
echo   URL: http://127.0.0.1:18888/api/ping
echo   Keep this window open while downloading.
echo.
python m3u8_download.py --serve 127.0.0.1:18888 %*
echo.
echo server stopped.
pause