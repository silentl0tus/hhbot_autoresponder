@echo off
chcp 65001 > nul
title JobHunter Dashboard

cd /d "%~dp0hh-autoresponder"

if not exist ".venv" (
    echo Виртуальное окружение не найдено. Запустите сначала run_windows.bat!
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo ===========================================
echo Запуск JobHunter Dashboard...
echo Веб-интерфейс доступен по адресу:
echo http://127.0.0.1:8080
echo ===========================================

python -m app.dashboard.server
pause
