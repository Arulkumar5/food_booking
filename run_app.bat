@echo off
title Nestora 1-Click Mobile Booking Server
color 0A
echo ========================================================
echo   Starting Nestora 1-Click Mobile Booking Server...
echo ========================================================
echo.

cd /d "%~dp0"
python server.py

pause
