@echo off

chcp 65001 >nul
goto :start_script
:start_script

set PYTHONUTF8=1

cd /d "%~dp0"



echo Проверка наличия Python...

python --version >nul 2>&1

if errorlevel 1 (

    echo [ВНИМАНИЕ] Python не установлен или не добавлен в PATH!

    echo Выполняется автоматическое скачивание Python 3.12...

    curl -L -o python_installer.exe https://www.python.org/ftp/python/3.12.3/python-3.12.3-amd64.exe

    if exist python_installer.exe (

        echo Установка Python (в тихом режиме, это займет около минуты)...

        start /wait python_installer.exe /quiet InstallAllUsers=0 PrependPath=1 Include_test=0

        del python_installer.exe

        echo.

        echo [УСПЕХ] Python успешно установлен!

        echo ВАЖНО: Окно нужно перезапустить, чтобы пути обновились.

        echo Закройте это окно и запустите run_windows.bat заново!

        pause

        exit /b

    ) else (

        echo [ОШИБКА] Не удалось скачать установщик. Пожалуйста, скачайте Python 3.12+ с сайта python.org

        pause

        exit /b

    )

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

