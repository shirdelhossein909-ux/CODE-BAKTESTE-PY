@echo off
chcp 65001 >nul
title Backtest - Zone Strategy
cd /d "%~dp0"
echo ================================================
echo  [BACKTEST] Running run_backtest.py ...
echo  (This may take several minutes)
echo ================================================
echo.
python run_backtest.py
echo.
echo ================================================
echo  [BACKTEST] Finished. Results are in the output folder.
echo ================================================
pause
