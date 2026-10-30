import asyncio
from app.config import settings
from app.parsers.hh_login import OTPLoginSession


async def main():
    print("=" * 60)
    print("🔐 Авторизация на hh.ru через консоль (OTP по SMS/почте)")
    print("=" * 60)

    default_phone = getattr(settings, "hh_login", "")
    prompt = (
        f"Введите номер телефона или почту [{default_phone}]: " if default_phone else "Введите номер телефона (+7...): "
    )

    val = input(prompt).strip()
    phone = val if val else default_phone
    if not phone:
        print("❌ Номер телефона не указан. Отмена.")
        return

    print(f"\n⏳ Открываю форму входа hh.ru и запрашиваю код для {phone}...")
    sess = OTPLoginSession()
    res = await sess.start(phone)

    if res.get("status") == "code_sent":
        print("\n📩 Код подтверждения отправлен (в SMS, push или на почту)!")
        code = input("👉 Введите полученный код: ").strip()
        if not code:
            print("❌ Код не введён. Отмена.")
            await sess.cancel()
            return

        print("⏳ Проверяю код и получаю токены сессии...")
        res_code = await sess.submit_code(code)
        if res_code.get("status") == "ok":
            print("\n✅ ВХОД ВЫПОЛНЕН УСПЕШНО!")
            print("📁 Сессия и куки сохранены в data/browser_sessions/hh_state.json")
            print("Бот теперь может продолжать отклики и поиск.")
        else:
            err = res_code.get("error")
            print(f"\n❌ Ошибка ввода кода: {err}")
    elif res.get("status") == "captcha":
        print("\n⚠️ hh.ru запросил графическую капчу. Картинка сохранена в data/hh_login_captcha.png")
        print("Попробуйте авторизоваться через скрипт на ноутбуке (login_hh_desktop.py) или позже.")
        await sess.cancel()
    else:
        err = res.get("error")
        print(f"\n❌ Не удалось запросить код: {err}")
        await sess.cancel()


if __name__ == "__main__":
    asyncio.run(main())
