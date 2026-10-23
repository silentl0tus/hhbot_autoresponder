#!/bin/bash
# Переходим в директорию, где лежит сам скрипт
cd "$(dirname "$0")" || { echo "Не удалось перейти в папку скрипта"; read -p "Нажмите Enter для выхода..."; exit 1; }

echo "Переход в папку проекта..."
cd hh-autoresponder || { echo "Не удалось найти папку hh-autoresponder"; read -p "Нажмите Enter для выхода..."; exit 1; }

if [ ! -d ".venv" ]; then
    echo "Виртуальное окружение не найдено. Запустите сначала run_linux.sh!"
    read -p "Нажмите Enter для выхода..."
    exit 1
fi

echo "Активация виртуального окружения..."
source .venv/bin/activate

echo "==========================================="
echo "Запуск JobHunter Dashboard..."
echo "Веб-интерфейс доступен по адресу:"
echo "http://127.0.0.1:8080"
echo "==========================================="

python3 -m app.dashboard.server
