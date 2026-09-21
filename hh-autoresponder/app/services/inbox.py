"""Build a short 'what to do next' list from scheduler cache + SQLite."""
from sqlalchemy import select, func

from app.config import settings
from app.database import async_session
from app.models.application import Application, ApplicationStatus
from app.models.message import RecruiterMessage
from app.models.vacancy import Vacancy, VacancyStatus


async def collect_inbox(scheduler=None) -> dict:
    unread = 0
    queue = 0
    today_sent = 0
    async with async_session() as session:
        unread = await session.scalar(
            select(func.count(RecruiterMessage.id)).where(RecruiterMessage.is_read.is_(False))
        ) or 0
        queue = await session.scalar(
            select(func.count(Vacancy.id)).where(Vacancy.status == VacancyStatus.APPROVED)
        ) or 0
        today_sent = await session.scalar(
            select(func.count(Application.id)).where(
                Application.status == ApplicationStatus.SENT,
                func.date(Application.created_at) == func.current_date(),
            )
        ) or 0

    paused = set()
    invitations = 0
    previews: list[str] = []
    sheets_at = None
    sheets_error = None
    unmatched = 0
    hh_limit = settings.max_applies_per_day_hh_max
    if scheduler:
        paused = set(getattr(scheduler, "paused_platforms", set()) or []) | set(
            getattr(scheduler, "manual_paused_platforms", set()) or []
        )
        invitations = int(getattr(scheduler, "sheets_invitations", 0) or 0)
        previews = list(getattr(scheduler, "sheets_invitation_previews", None) or [])
        sheets_at = getattr(scheduler, "sheets_last_sync_at", None)
        sheets_error = getattr(scheduler, "sheets_last_error", None)
        unmatched = int(getattr(scheduler, "sheets_last_unmatched", 0) or 0)
        hh_limit = getattr(scheduler, "max_applies_per_day_hh", hh_limit)

    return {
        "unread": unread,
        "queue": queue,
        "today_sent": today_sent,
        "hh_limit": hh_limit,
        "paused": sorted(paused),
        "invitations": invitations,
        "invitation_previews": previews,
        "sheets_at": sheets_at,
        "sheets_error": sheets_error,
        "unmatched": unmatched,
    }


def format_inbox(data: dict, heading: bool = True) -> str:
    lines = []
    if heading:
        lines.append("📌 <b>Что делать дальше</b>")
        lines.append("")

    invitations = data.get("invitations") or 0
    unread = data.get("unread") or 0
    paused = data.get("paused") or []
    queue = data.get("queue") or 0
    today_sent = data.get("today_sent") or 0
    hh_limit = data.get("hh_limit") or 0
    sheets_error = data.get("sheets_error")
    unmatched = data.get("unmatched") or 0
    sheets_at = data.get("sheets_at")

    if invitations:
        lines.append(f"🎉 <b>{invitations}</b> приглашений — ответить в hh.ru")
        for prev in (data.get("invitation_previews") or [])[:3]:
            lines.append(f"  • {prev}")
    if unread:
        lines.append(f"💬 Непрочитанных чатов: <b>{unread}</b>")
    if paused:
        labels = {"hh": "hh.ru", "habr": "Хабр"}.get
        names = ", ".join(labels(p, p) for p in paused)
        lines.append(f"🔐 На паузе: <b>{names}</b> — перелогин")
    lines.append(f"📦 Очередь одобренных: <b>{queue}</b> · сегодня {today_sent}/{hh_limit}")

    if sheets_error:
        lines.append(f"📑 Таблица: ошибка синхронизации — <code>{sheets_error[:120]}</code>")
    elif sheets_at:
        extra = f", не сматчилось {unmatched}" if unmatched else ""
        lines.append(f"📑 Таблица: последний sync {sheets_at}{extra}")
    else:
        lines.append("📑 Таблица: синхронизация ещё не выполнялась")

    if heading and not invitations and not unread and not paused and not sheets_error:
        lines.insert(2, "Пока нет срочных действий.")

    return "\n".join(lines).strip()


def inbox_has_actions(data: dict) -> bool:
    return bool(
        data.get("invitations")
        or data.get("unread")
        or data.get("paused")
        or data.get("sheets_error")
    )
