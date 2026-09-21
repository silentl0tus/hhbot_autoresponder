"""Write HH negotiation statuses into SQLite Application / Vacancy rows."""
import structlog
from sqlalchemy import select

from app.database import async_session
from app.models.application import Application, ApplicationStatus
from app.models.vacancy import Vacancy, VacancyStatus
from app.services.google_sheets import extract_vacancy_id

log = structlog.get_logger()

_TAB_TO_APP = {
    "invitations": ApplicationStatus.INVITED,
    "invitation": ApplicationStatus.INVITED,
    "discard": ApplicationStatus.REJECTED,
    "pending": ApplicationStatus.VIEWED,
    "response": ApplicationStatus.VIEWED,
    "active": ApplicationStatus.VIEWED,
    "consider": ApplicationStatus.VIEWED,
}

_APP_RANK = {
    ApplicationStatus.FAILED: 0,
    ApplicationStatus.PENDING: 0,
    ApplicationStatus.SENT: 1,
    ApplicationStatus.VIEWED: 2,
    ApplicationStatus.REJECTED: 3,
    ApplicationStatus.INVITED: 4,
}


async def sync_hh_statuses_to_db(parsed_statuses: list[dict]) -> int:
    """Update local Application/Vacancy from HH tabs. Returns rows changed."""
    if not parsed_statuses:
        return 0

    by_ext: dict[str, ApplicationStatus] = {}
    for s in parsed_statuses:
        vac_id = extract_vacancy_id(s.get("vacancy_url") or "", s.get("vacancy_id") or None)
        if not vac_id:
            continue
        tab = (s.get("tab") or "").lower()
        new_status = _TAB_TO_APP.get(tab)
        if not new_status:
            continue
        prev = by_ext.get(vac_id)
        if prev is None or _APP_RANK.get(new_status, 0) >= _APP_RANK.get(prev, 0):
            by_ext[vac_id] = new_status

    if not by_ext:
        return 0

    changed = 0
    async with async_session() as session:
        vacancies = (await session.execute(
            select(Vacancy).where(
                Vacancy.platform == "hh",
                Vacancy.external_id.in_(list(by_ext.keys())),
            )
        )).scalars().all()
        vac_by_ext = {v.external_id: v for v in vacancies}
        if not vac_by_ext:
            return 0

        apps = (await session.execute(
            select(Application)
            .where(Application.vacancy_id.in_([v.id for v in vacancies]))
            .order_by(Application.created_at.desc())
        )).scalars().all()
        latest_by_vac: dict[int, Application] = {}
        for app in apps:
            if app.vacancy_id not in latest_by_vac:
                latest_by_vac[app.vacancy_id] = app

        for ext_id, new_status in by_ext.items():
            vacancy = vac_by_ext.get(ext_id)
            if not vacancy:
                continue
            app = latest_by_vac.get(vacancy.id)
            if app:
                current_rank = _APP_RANK.get(app.status, 0)
                new_rank = _APP_RANK.get(new_status, 0)
                # Allow invite <-> reject transitions; never drop invite/reject to viewed.
                if new_status in (ApplicationStatus.INVITED, ApplicationStatus.REJECTED) or new_rank > current_rank:
                    if app.status != new_status:
                        app.status = new_status
                        changed += 1
            if new_status == ApplicationStatus.INVITED:
                if vacancy.status != VacancyStatus.INTERVIEW:
                    vacancy.status = VacancyStatus.INTERVIEW
                    changed += 1
            elif new_status == ApplicationStatus.REJECTED:
                if vacancy.status not in (VacancyStatus.INTERVIEW,):
                    if vacancy.status != VacancyStatus.RESPONSE_RECEIVED:
                        vacancy.status = VacancyStatus.RESPONSE_RECEIVED
                        changed += 1

        await session.commit()

    log.info("hh_statuses_synced_to_db", changed=changed)
    return changed
