#!/usr/bin/env bash
# ==============================================================================
# Скрипт синхронизации сессии hh.ru (hh_state.json) с ноутбука на смартфон
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/sync_config.env"

# Загрузка локальной конфигурации (если есть)
if [ -f "$CONFIG_FILE" ]; then
    # shellcheck disable=SC1090
    source "$CONFIG_FILE"
fi

# Параметры по умолчанию (можно переопределить через переменные окружения или аргументы)
SESSION_FILE="${1:-$SCRIPT_DIR/hh_state.json}"
PHONE_TARGET="${2:-${PHONE_ADB_TARGET:-}}"
PROOT_APP_DIR="${PHONE_PROOT_PATH:-/data/data/com.termux/files/usr/var/lib/proot-distro/containers/ubuntu/rootfs/root/bot/hh_autoresponder/hh-autoresponder}"
PM2_APP="${PM2_PROCESS_NAME:-hh-autoresponder}"

echo "=================================================================="
echo "📲 Синхронизация сессии hh.ru на смартфон (POCO F6 Pro)"
echo "=================================================================="

# 1. Проверка наличия целевого устройства
if [ -z "$PHONE_TARGET" ]; then
    echo "❌ Ошибка: Не указан адрес устройства (PHONE_ADB_TARGET)."
    echo "Создайте файл sync_config.env на основе sync_config.env.example или передайте адрес параметром:"
    echo "  $0 /путь/к/hh_state.json 100.x.x.x:5555"
    exit 1
fi

# 2. Проверка наличия файла сессии
if [ ! -f "$SESSION_FILE" ]; then
    # Попробуем поискать в data/browser_sessions/hh_state.json
    if [ -f "$SCRIPT_DIR/hh-autoresponder/data/browser_sessions/hh_state.json" ]; then
        SESSION_FILE="$SCRIPT_DIR/hh-autoresponder/data/browser_sessions/hh_state.json"
    else
        echo "❌ Ошибка: Файл сессии '$SESSION_FILE' не найден."
        echo "Сначала выполните вход на ноутбуке через ./login_hh_desktop.py"
        exit 1
    fi
fi

echo "📁 Используется файл сессии: $SESSION_FILE"
echo "🌐 Целевое устройство ADB:   $PHONE_TARGET"

# 3. Проверка adb
if ! command -v adb >/dev/null 2>&1; then
    echo "❌ Ошибка: Утилита adb не найдена. Установите её: sudo apt install -y adb"
    exit 1
fi

# 4. Подключение к смартфону
if ! adb devices | grep -q "$PHONE_TARGET"; then
    echo "⏳ Подключение к ADB $PHONE_TARGET..."
    timeout 5 adb connect "$PHONE_TARGET" >/dev/null 2>&1 || true
fi

# Проверка доступности
if ! timeout 5 adb -s "$PHONE_TARGET" get-state >/dev/null 2>&1; then
    echo "❌ Ошибка: Устройство $PHONE_TARGET недоступно по ADB."
    echo "Убедитесь, что Tailscale/Wi-Fi подключен и ADB запущен на смартфоне."
    exit 1
fi

# 5. Передача файла во временную директорию смартфона
TMP_REMOTE="/data/local/tmp/hh_state_sync.json"
echo "📤 Отправка файла сессии на смартфон..."
adb -s "$PHONE_TARGET" push "$SESSION_FILE" "$TMP_REMOTE" >/dev/null

# 6. Копирование файла в PRoot Ubuntu под root и установка прав
TARGET_PATH="$PROOT_APP_DIR/data/browser_sessions/hh_state.json"
echo "⚙️ Установка сессии в PRoot Ubuntu..."
adb -s "$PHONE_TARGET" shell "su -c '
    mkdir -p \"$(dirname "$TARGET_PATH")\"
    cp \"$TMP_REMOTE\" \"$TARGET_PATH\"
    chmod 644 \"$TARGET_PATH\"
    chown 10152:10152 \"$TARGET_PATH\" 2>/dev/null || true
    rm -f \"$TMP_REMOTE\"
'"

# 7. Перезапуск бота в PM2
echo "🔄 Перезапуск процесса $PM2_APP в PM2..."
adb -s "$PHONE_TARGET" shell "su -c '
    su 10152 -c \"PATH=/data/data/com.termux/files/usr/bin:\$PATH proot-distro login ubuntu -- pm2 restart $PM2_APP\"
'" >/dev/null 2>&1 || {
    echo "⚠️ Предупреждение: Не удалось автоматически перезапустить бота в PM2. Возможно процесс называется иначе."
}

echo ""
echo "✅ Сессия hh.ru успешно обновлена на смартфоне!"
echo "Бот продолжит работу с новыми куками."
