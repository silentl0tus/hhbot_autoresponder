#!/bin/bash
# Переходим в директорию, где лежит сам скрипт (важно для запуска из Наутилуса)
cd "$(dirname "$0")" || { echo "Не удалось перейти в папку скрипта"; read -p "Нажмите Enter для выхода..."; exit 1; }

echo "Переход в папку проекта..."
cd hh-autoresponder || { echo "Не удалось найти папку hh-autoresponder"; read -p "Нажмите Enter для выхода..."; exit 1; }

# Обход ограничения PEP 668 (externally-managed-environment) при запуске под root в Ubuntu
export PIP_BREAK_SYSTEM_PACKAGES=1

if [ ! -d ".venv" ]; then
    echo "Создание виртуального окружения..."
    python3 -m venv .venv 2>/dev/null || {
        echo "python3 -m venv не сработал (возможно, отсутствует пакет python3-venv). Создание через uv..."
        python3 -m pip install uv --break-system-packages > /dev/null 2>&1 || true
        uv venv .venv || python3 -m venv .venv
    }
fi

echo "Активация виртуального окружения..."
source .venv/bin/activate

echo "Установка зависимостей..."
python3 -m pip install --upgrade pip > /dev/null 2>&1 || true
python3 -m pip install uv > /dev/null 2>&1 || true
uv pip install -e .

echo "Установка браузеров Playwright..."
# На ARM64 (aarch64) в Ubuntu/proot ставим Chromium со всеми системными библиотеками
playwright install --with-deps chromium 2>/dev/null || playwright install chromium || playwright install

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
