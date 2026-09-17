# 🏗 Architecture & Context (For AI Agents & Developers)

> **Goal:** High-density context for LLM agents to understand the codebase without burning tokens on reading all files.

## 📌 Tech Stack
- **Language:** Python 3.12+ (AsyncIO heavy)
- **Telegram UI:** `aiogram` (v3+)
- **Scraping / Automation:** `playwright` (for interactive questionnaires), `beautifulsoup4`, `httpx` (for HH API)
- **Database:** `sqlalchemy[asyncio]` + `aiosqlite` (SQLite)
- **Task Scheduling:** `apscheduler`
- **Config & Validation:** `pydantic`, `pydantic-settings`
- **AI Integration:** Direct HTTP requests via `httpx` to OpenAI-compatible endpoints (Claude/Gemini/etc).

## 📂 Project Structure (`hh-autoresponder/app/`)

* **`main.py`** — Entry point. Initializes the database, starts the APScheduler, and launches the Aiogram polling.
* **`config.py`** — Loads `.env` using Pydantic Settings.
* **`database.py`** — SQLAlchemy async engine and sessionmaker setup.
* **`models/`** — SQLAlchemy ORM models:
  - `vacancy.py` (stores parsed vacancies and their scores)
  - `application.py` (tracks apply status and history)
  - `session.py` (stores cookies/tokens for HH auth)
* **`bot/`** — Telegram bot layer:
  - `handlers.py` (Message routers, `/start`, UI buttons to toggle auto-responder)
  - `keyboards.py` (Inline/Reply keyboards)
* **`parsers/`** — Core interaction with hh.ru:
  - `hh_api.py` (Fast search and standard applies via reverse-engineered mobile API)
  - `hh_playwright.py` (Heavy lifting: handles complex questionnaires, cover letters, and tests via headless browser)
  - `hh_login.py` / `manual_login.py` (Handles initial auth and session saving)
* **`workers/`** — Background business logic (orchestrated by APScheduler):
  - `scheduler.py` (Cron jobs config)
  - `vacancy_worker.py` (Fetches new vacancies periodically)
  - `apply_worker.py` (Picks up pending vacancies and attempts to apply)
* **`ai/`** — Intelligence layer:
  - `rule_analyzer.py` (Rule-based scoring: TARGET, NEGATIVE, and STACK keyword matching without using LLM tokens)
  - `claude.py` (LLM client for dynamic questionnaire answering and sentiment analysis)
  - `prompts.py` (System prompts)
* **`utils/`** — Helpers (anti-detect for playwright, rate limiters, notifications).

## 🔄 Core Workflow

1. **Scheduling:** `APScheduler` triggers `vacancy_worker` every `CHECK_INTERVAL_SEC`.
2. **Fetching:** `vacancy_worker` calls `hh_api` to fetch vacancies matching `SEARCH_QUERIES_RAW`.
3. **Scoring:** Vacancies are passed to `rule_analyzer`. If title contains negative keywords -> rejected. If it contains target keywords -> accepted. Stack keywords increase the score.
4. **Queueing:** Passed vacancies are saved to SQLite.
5. **Applying:** `apply_worker` processes the queue. It first tries `hh_api` for a fast 1-click apply.
6. **Fallback (Complex Applies):** If HH requires a test/questionnaire, `hh_playwright` takes over. It launches a headless browser, injects saved cookies, parses the DOM for questions, calls `ai/claude.py` to generate answers based on `resume.txt`, and submits the form.
7. **Notification:** Success/Fail statuses are pushed to the Telegram admin via `bot.handlers`.

## 🧠 LLM Usage Strategy
LLMs are **NOT** used for searching or basic filtering (to save money and increase speed). Filtering is purely deterministic (`rule_analyzer`). LLMs are invoked strictly for:
1. Answering mandatory open-ended questions in employer tests.
2. Generating context-aware responses if a recruiter replies in the HH chat.
