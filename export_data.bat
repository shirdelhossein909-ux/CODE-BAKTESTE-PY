@echo off
chcp 65001 >nul
title Export MT5 Data
cd /d "%~dp0"
python export_data.py
