import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import gspread
import structlog
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, WorksheetNotFound

from app.config import settings

log = structlog.get_logger()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

DASHBOARD_TITLE = "Дашборд"
LOG_HEADER = [
    "Дата",
    "Ссылка на описание",
    "Позиция",
    "Компания",
    "Контакт",
    "CV (ссылка)",
    "CL (ссылка)",
    "Статус",
    "Комментарий",
    "Vacancy ID",
    "Платформа",
    "Зарплата",
]

STATUS_MAPPING = {
    "discard": "Отказ",
    "invitations": "Приглашение",
    "invitation": "Приглашение",
    "pending": "Ждем ответа",
    "response": "Ждем ответа",
    "active": "Ждем ответа",
    "consider": "Ждем ответа",
}

AUTO_STATUSES = {"ждем ответа", "ошибка", "отказ", "приглашение", "успешно (backfill)"}
VACANCY_ID_RE = re.compile(r"(?:vacancy(?:id=|/)|vacancies/)(\d+)", re.I)

_client = None
_spreadsheet = None
_client_url = None
_formatting_applied = False


@dataclass
class SyncResult:
    updated: int = 0
    matched: int = 0
    unmatched: int = 0
    error: str | None = None
    invitations: int = 0
    discards: int = 0
    pending: int = 0
    invitation_previews: list[str] = field(default_factory=list)


def reset_client():
    """Drop cached gspread client (tests and 401 recovery)."""
    global _client, _spreadsheet, _client_url, _formatting_applied
    _client = None
    _spreadsheet = None
    _client_url = None
    _formatting_applied = False


def extract_vacancy_id(url: str = "", explicit: str | None = None) -> str:
    if explicit:
        return str(explicit).strip()
    m = VACANCY_ID_RE.search(url or "")
    return m.group(1) if m else ""


def _col_letter(n: int) -> str:
    """1-based column index to A1 letter."""
    string = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        string = chr(65 + remainder) + string
    return string


def _is_retryable(exc: Exception) -> bool:
    text = str(exc)
    if any(code in text for code in ("429", "500", "502", "503", "401", "UNAUTHENTICATED")):
        return True
    if isinstance(exc, APIError):
        try:
            code = int(getattr(getattr(exc, "response", None), "status_code", 0) or 0)
            return code in (401, 429, 500, 502, 503) or code >= 500
        except Exception:
            return True
    return False


def _with_retry(fn, attempts: int = 3):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            if _is_retryable(e) and i < attempts - 1:
                log.warning("google_sheets_retry", attempt=i + 1, error=str(e)[:160])
                reset_client()
                time.sleep(2 ** i)
                continue
            raise
    raise last


def _get_spreadsheet():
    global _client, _spreadsheet, _client_url
    if not settings.google_sheet_url:
        return None
    creds_path = Path(settings.google_sheets_credentials_path)
    if not creds_path.exists():
        log.warning("google_sheets_credentials_not_found", path=str(creds_path))
        raise FileNotFoundError(f"Google credentials not found: {creds_path}")
    if _spreadsheet is not None and _client_url == settings.google_sheet_url:
        return _spreadsheet
    credentials = Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)
    _client = gspread.authorize(credentials)
    _spreadsheet = _client.open_by_url(settings.google_sheet_url)
    _client_url = settings.google_sheet_url
    return _spreadsheet


def _header_index(header: list, *needles: str, default: int) -> int:
    lowered = [str(v).lower() for v in header]
    for i, name in enumerate(lowered):
        if all(n in name for n in needles):
            return i
    return default


def _ensure_log_header(worksheet, header: list[str]) -> list[str]:
    if not header:
        worksheet.update("A1", [LOG_HEADER], value_input_option="USER_ENTERED")
        return list(LOG_HEADER)
    extra = [col for col in ("Vacancy ID", "Платформа", "Зарплата") if col not in header]
    if extra:
        new_header = list(header) + extra
        worksheet.update("A1", [new_header], value_input_option="USER_ENTERED")
        return new_header
    return header


def _is_protected_status(current: str) -> bool:
    low = (current or "").strip().lower()
    if not low:
        return False
    if low in AUTO_STATUSES or low.startswith("ошибка"):
        return False
    return True


def _ensure_status_formatting(sh, worksheet) -> None:
    global _formatting_applied
    if _formatting_applied:
        return
    try:
        meta = sh.fetch_sheet_metadata()
        if isinstance(meta, dict):
            for sheet in meta.get("sheets") or []:
                props = sheet.get("properties") or {}
                if props.get("sheetId") == worksheet.id and sheet.get("conditionalFormats"):
                    _formatting_applied = True
                    return
        sheet_id = worksheet.id
        status_col = 7  # H, 0-based
        requests = []
        colors = [
            ("Приглашение", {"red": 0.72, "green": 0.88, "blue": 0.72}),
            ("Отказ", {"red": 0.96, "green": 0.76, "blue": 0.76}),
            ("Ошибка", {"red": 0.96, "green": 0.82, "blue": 0.68}),
            ("Ждем ответа", {"red": 1.0, "green": 0.95, "blue": 0.75}),
        ]
        for idx, (text, color) in enumerate(colors):
            requests.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "startColumnIndex": status_col,
                            "endColumnIndex": status_col + 1,
                        }],
                        "booleanRule": {
                            "condition": {
                                "type": "TEXT_EQ",
                                "values": [{"userEnteredValue": text}],
                            },
                            "format": {"backgroundColor": color},
                        },
                    },
                    "index": idx,
                }
            })
        sh.batch_update({"requests": requests})
        _formatting_applied = True
    except Exception as e:
        log.debug("google_sheets_formatting_skip", error=str(e)[:160])


def _parse_row_date(value: str) -> datetime | None:
    raw = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:19] if fmt.endswith("%S") else raw[:10], fmt)
        except ValueError:
            continue
    return None


def _refresh_dashboard(sh, all_values: list[list], synced_at: str | None = None) -> None:
    try:
        try:
            dash = sh.worksheet(DASHBOARD_TITLE)
        except WorksheetNotFound:
            dash = sh.add_worksheet(title=DASHBOARD_TITLE, rows=40, cols=4)
        except Exception:
            try:
                dash = sh.add_worksheet(title=DASHBOARD_TITLE, rows=40, cols=4)
            except Exception as e:
                log.warning("google_sheets_dashboard_open_error", error=str(e)[:160])
                return

        header = all_values[0] if all_values else LOG_HEADER
        status_idx = _header_index(header, "статус", default=7)
        date_idx = _header_index(header, "дата", default=0)
        url_idx = _header_index(header, "ссылка", default=1)
        title_idx = _header_index(header, "позиция", default=2)
        company_idx = _header_index(header, "компания", default=3)

        counts = {"Ждем ответа": 0, "Отказ": 0, "Приглашение": 0, "Ошибка": 0}
        invites: list[tuple[str, str, str]] = []
        now = datetime.now()
        cut7 = now - timedelta(days=7)
        cut30 = now - timedelta(days=30)
        total7 = inv7 = total30 = inv30 = 0

        for row in all_values[1:]:
            status = row[status_idx] if len(row) > status_idx else ""
            if status in counts:
                counts[status] += 1
            elif (status or "").startswith("Ошибка"):
                counts["Ошибка"] += 1
            dt = _parse_row_date(row[date_idx] if len(row) > date_idx else "")
            is_invite = status == "Приглашение"
            if dt and dt >= cut30:
                total30 += 1
                if is_invite:
                    inv30 += 1
            if dt and dt >= cut7:
                total7 += 1
                if is_invite:
                    inv7 += 1
            if is_invite and len(invites) < 10:
                title = row[title_idx] if len(row) > title_idx else ""
                company = row[company_idx] if len(row) > company_idx else ""
                url = row[url_idx] if len(row) > url_idx else ""
                invites.append((f"{company}: {title}".strip(": "), url, status))

        def pct(num, den):
            return f"{(100 * num / den):.0f}%" if den else "—"

        stamp = synced_at or datetime.now().strftime("%Y-%m-%d %H:%M")
        values = [
            ["Дашборд мониторинга", ""],
            ["last_sync", stamp],
            ["", ""],
            ["Статус", "Количество"],
            ["Ждем ответа", counts["Ждем ответа"]],
            ["Отказ", counts["Отказ"]],
            ["Приглашение", counts["Приглашение"]],
            ["Ошибка", counts["Ошибка"]],
            ["", ""],
            ["Конверсия приглашений 7д", pct(inv7, total7)],
            ["Конверсия приглашений 30д", pct(inv30, total30)],
            ["", ""],
            ["Последние приглашения", "Ссылка"],
        ]
        for label, url, _ in invites:
            values.append([label[:80], url])
        dash.update("A1", values, value_input_option="USER_ENTERED")
    except Exception as e:
        log.warning("google_sheets_dashboard_error", error=str(e)[:200])


def _upsert_row_sync(
    date_str: str,
    title: str,
    company: str,
    url: str,
    status: str,
    cover_letter: str,
    score_str: str,
    platform: str,
    salary: str,
    vacancy_id: str,
) -> None:
    sh = _get_spreadsheet()
    worksheet = sh.get_worksheet(0)
    all_values = worksheet.get_all_values() or []
    header = _ensure_log_header(worksheet, all_values[0] if all_values else [])
    if all_values:
        all_values[0] = header
    else:
        all_values = [header]

    url_idx = _header_index(header, "ссылка", "описание", default=1)
    if url_idx == 1 and not any("ссылка" in str(v).lower() and "описание" in str(v).lower() for v in header):
        url_idx = _header_index(header, "ссылка", default=1)
    status_idx = _header_index(header, "статус", default=7)
    cl_idx = _header_index(header, "cl", default=6)
    comment_idx = _header_index(header, "коммент", default=8)
    vac_idx = _header_index(header, "vacancy id", default=9)
    plat_idx = _header_index(header, "платформ", default=10)
    salary_idx = _header_index(header, "зарплат", default=11)

    vac_id = extract_vacancy_id(url, vacancy_id or None)
    found_row = None  # 1-based sheet row
    for i, row in enumerate(all_values[1:], start=2):
        row_vid = ""
        if vac_idx < len(row):
            row_vid = str(row[vac_idx]).strip()
        if not row_vid:
            row_vid = extract_vacancy_id(row[url_idx] if len(row) > url_idx else "")
        if vac_id and row_vid == vac_id:
            found_row = i
            break
        if not vac_id and url and len(row) > url_idx and row[url_idx] == url:
            found_row = i
            break

    def cell(col_idx: int, row_num: int) -> str:
        return f"{_col_letter(col_idx + 1)}{row_num}"

    if found_row:
        updates = []
        current_status = (
            all_values[found_row - 1][status_idx]
            if len(all_values[found_row - 1]) > status_idx
            else ""
        )
        if not _is_protected_status(current_status):
            updates.append({"range": cell(status_idx, found_row), "values": [[status]]})
        updates.append({"range": cell(cl_idx, found_row), "values": [[cover_letter]]})
        updates.append({"range": cell(comment_idx, found_row), "values": [[score_str]]})
        if vac_id:
            updates.append({"range": cell(vac_idx, found_row), "values": [[vac_id]]})
        if platform:
            updates.append({"range": cell(plat_idx, found_row), "values": [[platform]]})
        if salary:
            updates.append({"range": cell(salary_idx, found_row), "values": [[salary]]})
        worksheet.batch_update(updates, value_input_option="USER_ENTERED")
        log.info("google_sheets_row_updated", row=found_row, vacancy_id=vac_id)
    else:
        width = max(len(header), 12)
        row_data = [""] * width
        row_data[0] = date_str
        row_data[url_idx] = url
        row_data[2 if 2 < width else 0] = title
        title_idx = _header_index(header, "позиция", default=2)
        company_idx = _header_index(header, "компания", default=3)
        contact_idx = _header_index(header, "контакт", default=4)
        cv_idx = _header_index(header, "cv", default=5)
        row_data[title_idx] = title
        row_data[company_idx] = company
        row_data[contact_idx] = ""
        row_data[cv_idx] = f"Автоотклик ({platform or 'hh'})"
        row_data[cl_idx] = cover_letter
        row_data[status_idx] = status
        row_data[comment_idx] = score_str
        row_data[vac_idx] = vac_id
        row_data[plat_idx] = platform
        row_data[salary_idx] = salary
        worksheet.append_row(row_data, value_input_option="USER_ENTERED")
        log.info("google_sheets_row_appended", url=settings.google_sheet_url, vacancy_id=vac_id)
        all_values.append(row_data)

    _ensure_status_formatting(sh, worksheet)
    _refresh_dashboard(sh, all_values)


def _sync_statuses_sync(parsed_statuses: list[dict]) -> SyncResult:
    result = SyncResult()
    tabs = [((s.get("tab") or "").lower()) for s in parsed_statuses]
    result.invitations = sum(1 for t in tabs if t in ("invitations", "invitation"))
    result.discards = sum(1 for t in tabs if t == "discard")
    result.pending = sum(1 for t in tabs if t in ("pending", "response", "active", "consider", ""))
    result.invitation_previews = [
        f"{(s.get('company') or '').strip()}: {(s.get('title') or '')[:50]}".strip(": ")
        for s in parsed_statuses
        if (s.get("tab") or "").lower() in ("invitations", "invitation")
    ][:5]

    if not settings.google_sheet_url:
        return result

    sh = _get_spreadsheet()
    worksheet = sh.get_worksheet(0)
    log.info("google_sheets_sync_input", raw_count=len(parsed_statuses))

    update_map: dict[str, str] = {}
    for s in parsed_statuses:
        tab = (s.get("tab") or "").lower()
        status = (s.get("status") or "").lower()
        new_status = STATUS_MAPPING.get(tab) or STATUS_MAPPING.get(status)
        if not new_status:
            log.debug("google_sheets_sync_ignored_status", tab=tab, status=status)
            continue
        vac_id = extract_vacancy_id(s.get("vacancy_url") or "", s.get("vacancy_id") or None)
        if vac_id:
            update_map[vac_id] = new_status

    log.info("google_sheets_sync_mapped", mapped_count=len(update_map))
    if not update_map:
        all_values = worksheet.get_all_values() or []
        _refresh_dashboard(sh, all_values, datetime.now().strftime("%Y-%m-%d %H:%M"))
        return result

    all_values = worksheet.get_all_values() or []
    if not all_values:
        result.unmatched = len(update_map)
        return result

    header = _ensure_log_header(worksheet, all_values[0])
    all_values[0] = header
    url_idx = _header_index(header, "ссылка", "описание", default=1)
    if url_idx == 1:
        url_idx = _header_index(header, "ссылка", default=1)
    status_idx = _header_index(header, "статус", default=7)
    vac_idx = _header_index(header, "vacancy id", default=9)
    log.info("google_sheets_sync_columns", url_col=url_idx, status_col=status_idx)

    updates = []
    matched_ids: set[str] = set()
    for i, row in enumerate(all_values):
        if i == 0:
            continue
        url_col = row[url_idx] if len(row) > url_idx else ""
        current_status = row[status_idx] if len(row) > status_idx else ""
        vac_id = ""
        if vac_idx < len(row):
            vac_id = str(row[vac_idx]).strip()
        if not vac_id:
            vac_id = extract_vacancy_id(url_col)
        if not vac_id:
            continue
        new_status = update_map.get(vac_id)
        if not new_status:
            continue
        matched_ids.add(vac_id)
        if _is_protected_status(current_status):
            continue
        if new_status != current_status:
            updates.append({
                "range": f"{_col_letter(status_idx + 1)}{i + 1}",
                "values": [[new_status]],
            })

    result.matched = len(matched_ids)
    result.unmatched = max(0, len(update_map) - len(matched_ids))
    result.updated = len(updates)
    log.info(
        "google_sheets_sync_sheet_matches",
        matched=result.matched,
        to_update=result.updated,
        unmatched=result.unmatched,
    )

    if updates:
        worksheet.batch_update(updates, value_input_option="USER_ENTERED")
    log.info("google_sheets_statuses_synced", count=result.updated)
    _ensure_status_formatting(sh, worksheet)
    _refresh_dashboard(
        sh,
        all_values,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    return result


async def append_application(
    date_str: str,
    title: str,
    company: str,
    url: str,
    status: str,
    cover_letter: str,
    ai_score: float = 0.0,
    platform: str = "",
    salary: str = "",
    vacancy_id: str = "",
) -> bool:
    """Upsert an application row. Returns False if Sheets write failed."""
    if not settings.google_sheet_url:
        return True

    score_str = f"AI Score: {int(ai_score)}" if ai_score is not None else ""

    def _run():
        _with_retry(lambda: _upsert_row_sync(
            date_str, title, company, url, status, cover_letter,
            score_str, platform, salary, vacancy_id,
        ))

    try:
        await asyncio.to_thread(_run)
        return True
    except Exception as e:
        log.error("google_sheets_append_error", error=str(e))
        try:
            from app.utils import notifier
            await notifier.send(
                f"❌ <b>Google Sheets</b>: не удалось записать отклик\n"
                f"{(title or '')[:80]}\n<code>{str(e)[:180]}</code>"
            )
        except Exception as ne:
            log.warning("google_sheets_notify_error", error=str(ne)[:120])
        return False


async def sync_statuses_to_sheets(parsed_statuses: list[dict]) -> SyncResult:
    """Sync HH.ru statuses to Google Sheets. Returns SyncResult (updated count in .updated)."""
    if not settings.google_sheet_url:
        result = SyncResult()
        tabs = [((s.get("tab") or "").lower()) for s in parsed_statuses]
        result.invitations = sum(1 for t in tabs if t in ("invitations", "invitation"))
        result.discards = sum(1 for t in tabs if t == "discard")
        result.invitation_previews = [
            f"{(s.get('company') or '').strip()}: {(s.get('title') or '')[:50]}".strip(": ")
            for s in parsed_statuses
            if (s.get("tab") or "").lower() in ("invitations", "invitation")
        ][:5]
        return result

    def _run():
        return _with_retry(lambda: _sync_statuses_sync(parsed_statuses))

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        log.error("google_sheets_sync_error", error=str(e))
        return SyncResult(error=str(e)[:240])
