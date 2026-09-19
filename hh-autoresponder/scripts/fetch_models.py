"""
Скрипт для получении списка актуальных моделей Google Gemini
в реальном времени из официальной документации и API.
"""
import asyncio
from app.ai.google_models import fetch_live_google_models


async def main():
    print("🔍 Запрос актуальных моделей Google Gemini...")
    models = await fetch_live_google_models()
    print(f"\n✅ Найдено моделей: {len(models)}")
    print("=" * 40)
    for model in models:
        print(f" • {model}")
    print("=" * 40)


if __name__ == "__main__":
    asyncio.run(main())
