@echo off
chcp 65001 >nul
title PS5 Pad - LMHT Keyboard (WASD) [Wi-Fi]
set "DEFAULT_IP=192.168.1.7"
set /p "IP=Nhap IP iPhone hien trong app (Enter de dung %DEFAULT_IP%): "
if "%IP%"=="" set "IP=%DEFAULT_IP%"
echo.
echo Dang ket noi %IP%:7777 o che do LMHT Keyboard (WASD)...
echo Nhan Ctrl+C de dung.
echo.
python -u "%~dp0pc\companion.py" wifi "%IP%" --lol-wasd
if errorlevel 1 pause
