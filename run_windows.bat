@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

echo Проверка наличия Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python не установлен. Пожалуйста, скачайте и установите Python 3.12+ с сайта python.org
    pause
    exit /b
)

echo Создание виртуального окружения (если еще не создано)...
if not exist ".venv" (
    python -m venv .venv
)

echo Активация виртуального окружения...
call .venv\Scripts\activate.bat

echo Установка зависимостей (uv и пакеты проекта)...
cd hh-autoresponder
python -m pip install --upgrade pip >nul
python -m pip install -e .

echo Установка браузеров Playwright...
python -m playwright install

echo.
echo ===========================================
echo Запуск hh-autoresponder...
echo ===========================================
python -m app.main

echo.
pause
