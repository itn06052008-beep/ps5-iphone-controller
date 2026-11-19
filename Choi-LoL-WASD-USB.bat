@echo off
chcp 65001 >nul
title PS5 Pad - LMHT Keyboard (WASD) [Cap USB]
echo Dang ket noi iPhone qua cap USB o che do LMHT Keyboard (WASD)...
echo Nhan Ctrl+C de dung.
echo.
python -u "%~dp0pc\companion.py" usb --lol-wasd
if errorlevel 1 pause
