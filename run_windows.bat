@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

echo Проверка наличия Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не установлен или не добавлен в PATH!
    echo Пожалуйста, скачайте Python 3.12+ с сайта python.org
    echo При установке ОБЯЗАТЕЛЬНО поставьте галочку "Add Python to PATH".
    pause
    exit /b
)

echo Создание виртуального окружения...
if not exist ".venv\Scripts\activate.bat" (
    python -m venv .venv
)

if not exist ".venv\Scripts\activate.bat" (
    echo [ОШИБКА] Не удалось создать виртуальное окружение!
    echo Возможно, у вас работает "заглушка" Windows Store вместо нормального Python.
    echo Удалите заглушку в "Параметры -> Приложения -> Псевдонимы выполнения приложений" или установите Python с python.org.
    pause
    exit /b
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
