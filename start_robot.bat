@echo off
chcp 65001 >nul
title Zone Trading Robot
cd /d "%~dp0"
:loop
echo ================================================
echo  [ROBOT] Starting live_trader.py ...
echo  (Exit: press Ctrl+C then Y)
echo ================================================
python live_trader.py
echo.
echo  [ROBOT] Stopped or crashed! Restarting in 10 seconds...
timeout /t 10
goto loop
