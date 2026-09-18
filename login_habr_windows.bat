@echo off
cd /d "%~dp0"

echo Активация виртуального окружения...
if not exist ".venv" (
    echo Сначала запустите run_windows.bat, чтобы установить зависимости!
    pause
    exit /b
)
call .venv\Scripts\activate.bat

echo Переход в папку проекта...
cd hh-autoresponder

echo ===========================================
echo Запуск ручной авторизации на Хабр Карьера...
echo Пожалуйста, войдите в свой аккаунт в открывшемся браузере.
echo После успешного входа скрипт сохранит сессию и закроется.
echo ===========================================
python -m app.parsers.habr_login

echo.
echo Сессия сохранена! Теперь вы можете запускать run_windows.bat для работы бота.
pause
