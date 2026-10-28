#!/bin/bash
# Переходим в директорию, где лежит сам скрипт (важно для запуска из Наутилуса)
cd "$(dirname "$0")" || { echo "Не удалось перейти в папку скрипта"; read -p "Нажмите Enter для выхода..."; exit 1; }

echo "Переход в папку проекта..."
cd hh-autoresponder || { echo "Не удалось найти папку hh-autoresponder"; read -p "Нажмите Enter для выхода..."; exit 1; }

# Обход ограничения PEP 668 (externally-managed-environment) при запуске под root в Ubuntu
export PIP_BREAK_SYSTEM_PACKAGES=1

# Проверяем валидность виртуального окружения
# Если .venv перенесли с другого ПК/архитектуры или пути изменились — интерпретатор не запустится
if [ -d ".venv" ]; then
    if ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
        echo "Внимание: обнаружен несовместимый или повреждённый .venv"
        echo "(папка .venv была скопирована с другого ПК или изменились абсолютные пути)."
        echo "Удаление старого .venv и создание чистого окружения под эту систему..."
        rm -rf .venv
    fi
fi

if [ ! -d ".venv" ]; then
    echo "Создание виртуального окружения..."
    python3 -m venv .venv 2>/dev/null || {
        echo "python3 -m venv не сработал. Пробуем через uv..."
        python3 -m pip install uv --break-system-packages > /dev/null 2>&1 || true
        uv venv .venv 2>/dev/null || python3 -m venv .venv || {
            echo "КРИТИЧЕСКАЯ ОШИБКА: Не удалось создать .venv."
            echo "Установите пакет venv в систему: apt update && apt install -y python3-venv python3-pip"
            read -p "Нажмите Enter для выхода..."
            exit 1
        }
    }
fi

echo "Активация виртуального окружения..."
source .venv/bin/activate || {
    echo "Не удалось активировать виртуальное окружение."
    read -p "Нажмите Enter для выхода..."
    exit 1
}

echo "Установка зависимостей..."
python3 -m pip install --upgrade pip > /dev/null 2>&1 || true
python3 -m pip install uv > /dev/null 2>&1 || true

# Установка зависимостей проекта через uv или pip с откатом
if command -v uv >/dev/null 2>&1; then
    uv pip install -e . || python3 -m pip install -e .
else
    python3 -m pip install -e .
fi

echo "Установка браузеров Playwright..."
# На ARM64 (aarch64) в Ubuntu/proot ставим Chromium со всеми системными библиотеками
python3 -m playwright install --with-deps chromium 2>/dev/null \
    || python3 -m playwright install chromium 2>/dev/null \
    || playwright install --with-deps chromium 2>/dev/null \
    || playwright install chromium 2>/dev/null \
    || true

echo "==========================================="
echo "Запуск hh-autoresponder..."
echo "==========================================="

# Исправляем проблему httpx, который не понимает схему socks:// (нужно socks5://)
export http_proxy="${http_proxy/socks:\/\//socks5:\/\/}"
export https_proxy="${https_proxy/socks:\/\//socks5:\/\/}"
export all_proxy="${all_proxy/socks:\/\//socks5:\/\/}"
export HTTP_PROXY="${HTTP_PROXY/socks:\/\//socks5:\/\/}"
export HTTPS_PROXY="${HTTPS_PROXY/socks:\/\//socks5:\/\/}"
export ALL_PROXY="${ALL_PROXY/socks:\/\//socks5:\/\/}"

python3 -m app.main

echo "Работа скрипта завершена."
read -p "Нажмите Enter для выхода..."
