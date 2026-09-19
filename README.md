<div align="center">

<svg width="800" height="200" viewBox="0 0 800 200" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#0a0f0a"/>
      <stop offset="100%" style="stop-color:#0d1f14"/>
    </linearGradient>
    <linearGradient id="accent" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" style="stop-color:#22c55e"/>
      <stop offset="100%" style="stop-color:#4ade80"/>
    </linearGradient>
    <linearGradient id="accentV" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" style="stop-color:#22c55e"/>
      <stop offset="100%" style="stop-color:#15803d"/>
    </linearGradient>
  </defs>
  <rect width="800" height="200" fill="url(#bg)" rx="14"/>
  <rect x="0" y="0" width="5" height="200" fill="url(#accentV)" rx="2"/>
  <rect x="0" y="0" width="800" height="2" fill="url(#accent)" rx="1" opacity="0.4"/>
  <rect x="30" y="26" width="188" height="22" rx="11" fill="#22c55e18" stroke="#22c55e40" stroke-width="1"/>
  <circle cx="46" cy="37" r="4" fill="#22c55e"/>
  <text x="116" y="42" font-family="'Courier New', monospace" font-size="11" fill="#22c55e" text-anchor="middle" letter-spacing="1">TELEGRAM BOT · hh.ru</text>
  <text x="30" y="98" font-family="Georgia, 'Times New Roman', serif" font-size="40" font-weight="bold" fill="#f8f8f8" letter-spacing="-1">hh-autoresponder</text>
  <text x="30" y="128" font-family="'Courier New', monospace" font-size="13" fill="#6b7280" letter-spacing="0.5">Автоотклики на вакансии hh.ru. Бесплатно, open-source.</text>
  <rect x="30" y="152" width="112" height="26" rx="5" fill="#12211a" stroke="#22553a" stroke-width="1"/>
  <text x="86" y="169" font-family="'Courier New', monospace" font-size="11" fill="#7dd3a8" text-anchor="middle">авто-отклики</text>
  <rect x="152" y="152" width="100" height="26" rx="5" fill="#12211a" stroke="#22553a" stroke-width="1"/>
  <text x="202" y="169" font-family="'Courier New', monospace" font-size="11" fill="#7dd3a8" text-anchor="middle">Python 3.12+</text>
  <rect x="262" y="152" width="92" height="26" rx="5" fill="#12211a" stroke="#22553a" stroke-width="1"/>
  <text x="308" y="169" font-family="'Courier New', monospace" font-size="11" fill="#7dd3a8" text-anchor="middle">MIT лицензия</text>
  <text x="668" y="120" font-family="Georgia, serif" font-size="72" fill="#ffffff05" font-weight="bold">hh</text>
</svg>

<br/>

[![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)]()
[![Version](https://img.shields.io/badge/version-1.0.0-e63946?style=flat-square)]()

</div>

<br/>

# hh-autoresponder — умный бот автооткликов на вакансии hh.ru и Хабр Карьера

**Автоотклики на hh.ru и Хабр Карьеру на полном автопилоте.** Телеграм-бот находит вакансии по вашим поисковым критериям, фильтрует их без лишней траты токенов, генерирует уникальные персонализированные сопроводительные письма с помощью **бесплатных нейросетей**, очеловечивает их встроенным гуманизатором (Анти-ИИ) и безопасно отправляет отклики с имитацией поведения человека.

Полностью бесплатный, с открытым исходным кодом (open-source), запускается на вашем ПК или удаленном Linux-сервере (VPS). Все управление, настройка нейросетей, мониторинг и детальный лог — прямо в вашем Telegram.

> ⚠️ **Дисклеймер.** Автоматические отклики на вакансии формально могут нарушать правила платформ. Бот оснащен механизмами рандомизации задержек и динамическими суточными лимитами для защиты от антифрод-систем, однако соблюдайте разумные лимиты. Проект предназначен для личного использования.

---

> [!WARNING]
> **Важное требование к сети: VPN / Proxy и Раздельное туннелирование**
> Для корректной работы бота требуется учитывать сетевые особенности:
> 1. **Telegram API и провайдеры нейросетей (Google Gemini, OpenRouter)** могут требовать доступ без региональных ограничений. Бот поддерживает отдельную настройку прокси для ИИ прямо из Telegram!
> 2. 🔴 **Критичный нюанс:** Трафик к сайтам **hh.ru** и **api.hh.ru** должен идти **напрямую с чистого российского IP-адреса** (в обход зарубежных VPN/Proxy). HeadHunter блокирует зарубежные IP и публичные датацентровые подсети (выдавая капчу или Cloudflare 403). При использовании системного VPN настройте раздельное туннелирование (split tunneling).

---

## 🌟 Ключевые особенности и возможности

- 🤖 **100% Бесплатный AI-слой:**
  - Поддержка провайдера **OpenRouter** со сверхбыстрой бесплатной моделью **`deepseek/deepseek-v4-flash-0731:free`** (работает с нулевым балансом).
  - Поддержка **Google Gemini** (бесплатный тариф Gemini Flash).
  - Надежный таймаут запросов (240 сек) и поддержка thinking/reasoning моделей (автоматическое извлечение ответов из полей рассуждения).
  - Экономия ресурсов: фильтрация вакансий по стоп-словам и стеку выполняется локально через `Rule Analyzer` без обращения к LLM. Нейросеть привлекается строго для составления письма под конкретную вакансию.
- 📱 **Интерактивное управление через Telegram (Aiogram 3):**
  - Раздел «💎 Баланс AI» / «🤖 Настройки ИИ»: переключение между OpenRouter и Gemini в один клик.
  - Сохранение API-ключей для каждого провайдера раздельно (ключи не стираются при переключении пресетов).
  - Кнопка **«⚡ Проверить подключение»**: мгновенный тест доступности нейросети с замером времени ответа и диагностикой ошибок прямо в Telegram.
  - Ввод и смена API-ключей через защищенные диалоги Telegram без необходимости перезапуска бота.
  - Настройка AI Proxy непосредственно из интерфейса бота.
- 🎯 **Высокоточный парсинг вакансий через официальный API:**
  - Детальная информация о вакансии (полное описание, стек, требования, название компании) запрашивается через официальный API `api.hh.ru/vacancies/<id>` с использованием авторизованного OAuth Bearer токена. Это исключает блокировки Cloudflare и гарантирует, что ИИ получит исчерпывающий контекст, а не пустой HTML-шаблон.
- ✍️ **Гуманизатор текста (Анти-AI):**
  - Очищает сгенерированные сопроводительные письма от роботизированных штампов, канцеляризмов и шаблонных фраз («Я с большим интересом прочитал...», «Уверен, что мой опыт станет идеальным...»), делая письмо живым, емким и убедительным для рекрутера.
- 🛡️ **Антифрод и мимикрия под человека:**
  - Случайные задержки между откликами.
  - Динамические суточные лимиты (случайное число откликов каждый день между `DAILY_MIN` и `DAILY_MAX`).
  - Учет «тихих часов» (бот не откликается и не шумит уведомлениями ночью).
- ⬆️ **Автоподнятие резюме:**
  - Автоматическое поднятие резюме в поиске hh каждые 4 часа для удержания профиля в топе выдачи работодателей.
- 📊 **Прозрачная статистика и экспорт:**
  - Интерактивная воронка откликов в Telegram (отправлено, отказы, приглашения, в ожидании).
  - Опциональная синхронизация с Google Таблицами каждые 24 часа.

---

## 📋 Системные требования

- **ОС:** Linux (Ubuntu 20.04+, Debian, Arch, CentOS), Windows 10/11, macOS.
- **Python:** 3.12+ (рекомендуется пакетный менеджер `uv`).
- **Telegram:** Созданный бот в [@BotFather](https://t.me/BotFather) и ваш числовой ID из [@userinfobot](https://t.me/userinfobot).
- **HeadHunter:** Аккаунт на hh.ru с активным опубликованным резюме.
- **AI-ключ (бесплатный):**
  - Ключ **OpenRouter** (бесплатно на [openrouter.ai](https://openrouter.ai/)) с установленным кредитным лимитом **"Unlimited"**.
  - ИЛИ бесплатный ключ **Google Gemini** из [Google AI Studio](https://aistudio.google.com/).

База данных — локальный SQLite (`app.db`). Установка сторонних сервисов (PostgreSQL, Redis, Docker) **не требуется**.

---

## 🚀 Инструкция по вводу в эксплуатацию (Quickstart)

### Шаг 1. Клонирование и подготовка конфигурации

1. Склонируйте репозиторий на ваш компьютер или сервер:
   ```bash
   git clone https://github.com/silentl0tus/hhbot_autoresponder.git
   cd hhbot_autoresponder
   ```

2. Создайте файл конфигурации `.env` на основе примера:
   ```bash
   cp hh-autoresponder/.env.example hh-autoresponder/.env
   ```

3. Откройте `hh-autoresponder/.env` в текстовом редакторе и настройте параметры:
   ```env
   # Обязательные параметры Telegram
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ  # Токен от @BotFather
   TELEGRAM_CHAT_ID=123456789                               # Числовой ID от @userinfobot

   # Выбор AI провайдера (по умолчанию бесплатный OpenRouter)
   LLM_PROVIDER=openrouter
   OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxx     # Бесплатный ключ с openrouter.ai
   LLM_MODEL=deepseek/deepseek-v4-flash-0731:free           # 100% бесплатная модель

   # Поисковые запросы на hh.ru (через точку с запятой)
   SEARCH_QUERIES=Python разработчик;Backend developer;Django;FastAPI

   # Фильтрация по опыту, зарплате и ключевым словам
   EXPERIENCE=between1And3
   TARGET_KEYWORDS=python,fastapi,django,postgresql,asyncio,docker
   NEGATIVE_KEYWORDS=bitrix,1c,senior,lead,php,wordpress
   ```

4. **Заполните резюме:**
   Создайте файл `hh-autoresponder/data/resume.txt` и вставьте туда полный текст вашего резюме (навыки, опыт работы, проекты). Нейросеть использует этот контекст для генерации точечных ответов на вопросы работодателей и составления персонализированных писем.

---

### Шаг 2. Получение бесплатного AI-ключа OpenRouter

1. Зарегистрируйтесь на сайте [openrouter.ai](https://openrouter.ai/).
2. Перейдите в раздел **Keys** (`https://openrouter.ai/settings/keys`) и нажмите **Create Key**.
3. 🔴 **КРИТИЧЕСКИ ВАЖНО:** При создании ключа (или в его редактировании) в поле **Credit limit** оставьте значение пустым или выберите **Unlimited** (без ограничения баланса).
   > *Если на ключе установлен лимит $0, OpenRouter заблокирует запросы с ошибкой `HTTP 403: Key limit exceeded`, даже при использовании бесплатных моделей с суффиксом `:free`!*
4. Скопируйте ключ вида `sk-or-v1-...` в переменную `OPENROUTER_API_KEY` в `.env` (или сохраните его, чтобы ввести через интерфейс Telegram).

---

### Шаг 3. Первичный вход на HeadHunter (Авторизация)

Для работы откликов боту необходимы авторизационные cookies и OAuth-токен. Для этого используется скрипт с открытием браузера.

#### На Linux / Ubuntu с графическим интерфейсом:
```bash
chmod +x run_linux.sh login_linux.sh

# Первичная установка окружения и зависимостей (один раз)
./run_linux.sh
# Прервите выполнение (Ctrl+C) после завершения установки

# Запуск браузера для авторизации на hh.ru
./login_linux.sh
```
В открывшемся браузере авторизуйтесь в вашем аккаунте hh.ru (по SMS, коду из почты или паролю). После успешного входа скрипт автоматически сохранит сессию в `hh-autoresponder/data/hh_session.json` и OAuth-токен в `hh_oauth_token.json`, после чего окно закроется.

#### На Windows:
1. Запустите двойным кликом **`run_windows.bat`** (создастся окружение и скачаются зависимости).
2. Запустите **`login_windows.bat`** — в окне браузера войдите в hh.ru. Сессия сохранится автоматически.

#### На удаленном сервере без графической оболочки (Headless VPS):
Авторизуйтесь локально на своем ПК через `login_linux.sh` / `login_windows.bat`, после чего скопируйте папку `hh-autoresponder/data/` (содержащую `hh_session.json` и `hh_oauth_token.json`) на ваш сервер по SSH/SFTP.

*(Опционально: если планируете откликаться на Хабр Карьере, аналогично выполните `./login_habr_linux.sh` или `login_habr_windows.bat`)*

---

### Шаг 4. Запуск бота и ввод в работу

1. Запустите бота:
   - **Linux:** `./run_linux.sh`
   - **Windows:** `run_windows.bat`
2. Откройте вашего бота в Telegram и отправьте команду `/start`.
3. Перейдите в меню **«💎 Баланс AI»** (или «⚙️ Настройки» ➡️ «🤖 Настройки ИИ»):
   - Убедитесь, что выбран провайдер **OpenRouter** (активная модель: `deepseek/deepseek-v4-flash-0731:free`).
   - Нажмите **«⚡ Проверить подключение»**. Бот отправит тестовый запрос и пришлет отчет:
     ```text
     ✅ Тест AI пройден успешно!
     Модель: deepseek/deepseek-v4-flash-0731:free
     Время ответа: 2.15 сек
     ```
4. В главном меню нажмите кнопку **«🟢 Автоотклик»**.
   Бот начнет плановый сбор вакансий, их скоринг и рассылку откликов с человеческими задержками. Отчеты о каждом действии будут приходить прямо в чат!

---

## 🖥️ Развертывание в качестве фоновой службы на Linux (systemd)

Для бесперебойной круглосуточной работы бота на сервере настройте демон `systemd`:

1. Создайте юнит-файл службы:
   ```bash
   sudo nano /etc/systemd/system/hh-autoresponder.service
   ```

2. Вставьте конфигурацию (замените `YOUR_USER` и `/path/to/hhbot_autoresponder` на ваши реальные пути):
   ```ini
   [Unit]
   Description=HH Autoresponder Telegram Bot
   After=network.target

   [Service]
   Type=simple
   User=YOUR_USER
   WorkingDirectory=/path/to/hhbot_autoresponder/hh-autoresponder
   ExecStart=/path/to/hhbot_autoresponder/hh-autoresponder/.venv/bin/python -m app.main
   Restart=always
   RestartSec=15
   Environment=PYTHONUNBUFFERED=1

   [Install]
   WantedBy=multi-user.target
   ```

3. Активируйте и запустите службу:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable hh-autoresponder
   sudo systemctl start hh-autoresponder
   ```

4. Просмотр логов в реальном времени:
   ```bash
   journalctl -u hh-autoresponder -f
   ```

---

## 📈 Выгрузка в Google Таблицы (Опционально)

Бот умеет автоматически выгружать историю откликов и статусы (Отказ, Приглашение, В ожидании) в вашу личную Google Таблицу.

1. Создайте Google Таблицу с колонками: `Дата`, `Ссылка`, `Позиция`, `Компания`, `Контакт`, `CV`, `CL`, `Статус`, `Комментарий`.
2. Создайте сервисный аккаунт в [Google Cloud Console](https://console.cloud.google.com/), скачайте JSON-ключ и предоставьте email'у сервисного аккаунта права **Редактора** в вашей таблице.
3. Сохраните ключ в `hh-autoresponder/configs/google_credentials.json`.
4. В `.env` укажите ссылку на таблицу:
   ```env
   GOOGLE_SHEET_URL=https://docs.google.com/spreadsheets/d/ВАШ_ID/edit
   GOOGLE_SHEETS_CREDENTIALS_PATH=configs/google_credentials.json
   ```

---

## 🛠 Устранение неполадок (FAQ / Troubleshooting)

- **Ошибка `HTTP 403: Key limit exceeded (total limit)` от OpenRouter:**
  Откройте [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys), нажмите Edit у используемого ключа и очистите поле Credit Limit (установите Unlimited).
- **Ошибка `404 / 401: Invalid API Key`:**
  Проверьте правильность ключа. В Telegram нажмите «💎 Баланс AI» ➡️ «✏️ Изменить ключ OpenRouter» и вставьте корректный ключ. Нажмите «⚡ Проверить подключение».
- **Ошибка `Unknown scheme for proxy URL URL('socks://...')`:**
  Скрипты запуска автоматически преобразуют `socks://` в `socks5://`. Если запускаете вручную без скриптов, убедитесь, что переменная `ALL_PROXY` содержит протокол `socks5://`.
- **Зависание или таймаут генерации письма:**
  Бесплатные модели в часы пиковой нагрузки могут отвечать до 30–90 секунд. В боте установлен увеличенный таймаут в 240 секунд, что предотвращает срывы запросов.
- **Playwright host validation warning / отсутствие библиотек браузера на Linux:**
  Выполните команду:
  ```bash
  cd hh-autoresponder && source .venv/bin/activate && sudo playwright install-deps
  ```

---

## 📝 Лицензия

Проект распространяется под открытой лицензией [MIT](LICENSE). 
