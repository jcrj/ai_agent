import asyncio
import logging
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

try:
    import caldav
except ImportError:
    caldav = None

from config import settings

logger = logging.getLogger(__name__)

ICLOUD_CALDAV_URL = "https://caldav.icloud.com/"
_SGT = timezone(timedelta(hours=8))

# In-memory cache of last-listed events per user, for index-based modify/delete.
# Maps user_id -> list of (calendar_url, event_uid) in display order.
_last_listed: dict[int, list[tuple[str, str]]] = {}


# ─── Sync CalDAV helpers (wrapped by asyncio.to_thread) ───────────────────────

def _get_client(user_id: int):
    if caldav is None:
        return None
    creds = settings.get_icloud_credentials(user_id) if settings else None
    if not creds:
        return None
    username, password = creds
    return caldav.DAVClient(url=ICLOUD_CALDAV_URL, username=username, password=password)


def _get_all_calendars(client: caldav.DAVClient) -> list:
    principal = client.principal()
    calendars = principal.calendars()
    if not calendars:
        raise RuntimeError("No calendars found for this iCloud account.")
    return calendars


def _find_calendar_by_name(calendars: list, name: str):
    name_lower = name.lower()
    for cal in calendars:
        if cal.name and cal.name.lower() == name_lower:
            return cal
    for cal in calendars:
        if cal.name and name_lower in cal.name.lower():
            return cal
    return None


def _get_write_calendar(client: caldav.DAVClient, user_id: int):
    calendars = _get_all_calendars(client)
    cal_name = settings.get_calendar_name(user_id) if settings else None
    if cal_name:
        found = _find_calendar_by_name(calendars, cal_name)
        if found:
            return found
        logger.warning(f"Calendar '{cal_name}' not found, falling back to first calendar")
    return calendars[0]


def _extract_event_data(event, calendar_name: str | None = None) -> dict:
    vevent = event.vobject_instance.vevent
    start = vevent.dtstart.value if hasattr(vevent, 'dtstart') else None
    end = vevent.dtend.value if hasattr(vevent, 'dtend') else None
    all_day = start is not None and not isinstance(start, datetime)

    return {
        'uid': vevent.uid.value if hasattr(vevent, 'uid') else None,
        'summary': vevent.summary.value if hasattr(vevent, 'summary') else '(no title)',
        'start': start,
        'end': end,
        'location': vevent.location.value if hasattr(vevent, 'location') else None,
        'description': vevent.description.value if hasattr(vevent, 'description') else None,
        'all_day': all_day,
        'calendar_name': calendar_name,
    }


def _format_event_line(idx: int, data: dict) -> str:
    summary = data.get('summary', '(no title)')
    start = data.get('start')
    end = data.get('end')
    location = data.get('location')
    cal_name = data.get('calendar_name')

    if data.get('all_day'):
        time_str = f"{start.strftime('%Y-%m-%d')} (all day)" if start else "?"
    elif isinstance(start, datetime) and isinstance(end, datetime):
        time_str = f"{start.strftime('%Y-%m-%d %H:%M')}-{end.strftime('%H:%M')}"
    elif isinstance(start, datetime):
        time_str = start.strftime('%Y-%m-%d %H:%M')
    else:
        time_str = "?"

    line = f"{idx}. 📅 {time_str} — {summary}"
    if cal_name:
        line += f" [{cal_name}]"
    if location:
        line += f" (📍 {location})"
    return line


def _parse_iso(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_SGT)
    return dt


# ─── Sync operations ─────────────────────────────────────────────────────────

def _list_events_sync(user_id: int, days_ahead: int) -> tuple[list[dict], str | None]:
    client = _get_client(user_id)
    if not client:
        return [], "Calendar not configured for this user. Set the iCloud credentials environment variables."
    try:
        calendars = _get_all_calendars(client)
        now = datetime.now(_SGT)
        end = now + timedelta(days=days_ahead)

        all_events = []
        for cal in calendars:
            try:
                events = cal.search(start=now, end=end, event=True, expand=True)
                for e in events:
                    all_events.append(_extract_event_data(e, calendar_name=cal.name))
            except Exception as cal_err:
                logger.warning(f"Failed to read calendar '{cal.name}': {cal_err}")

        all_events.sort(key=lambda x: x.get('start') if isinstance(x.get('start'), datetime) else datetime.max.replace(tzinfo=_SGT))
        return all_events, None
    except Exception as e:
        logger.error(f"CalDAV list failed: {e}", exc_info=True)
        return [], f"Failed to fetch calendar: {e}"


def _find_event_across_calendars(client: caldav.DAVClient, match_text: str,
                                  days_back: int = 7, days_forward: int = 30):
    """Search all calendars for the best fuzzy match."""
    calendars = _get_all_calendars(client)
    now = datetime.now(_SGT)
    start = now - timedelta(days=days_back)
    end = now + timedelta(days=days_forward)

    best_ratio = 0.0
    best_event = None
    best_data = None
    match_lower = match_text.lower()

    for cal in calendars:
        try:
            events = cal.search(start=start, end=end, event=True, expand=True)
            for event in events:
                data = _extract_event_data(event, calendar_name=cal.name)
                summary = (data.get('summary') or '').lower()
                ratio = SequenceMatcher(None, match_lower, summary).ratio()
                if match_lower in summary:
                    ratio = max(ratio, 0.85)
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_event = event
                    best_data = data
        except Exception as cal_err:
            logger.warning(f"Failed to search calendar '{cal.name}': {cal_err}")

    if best_ratio < 0.4:
        return None, None
    return best_event, best_data


def _get_event_by_uid_across_calendars(client: caldav.DAVClient, uid: str):
    """Search all calendars for an event by UID."""
    calendars = _get_all_calendars(client)
    for cal in calendars:
        try:
            event = cal.event_by_uid(uid)
            return event, _extract_event_data(event, calendar_name=cal.name)
        except Exception:
            continue
    return None, None


def _resolve_event_sync(user_id: int, match_reference: str | None, index: int | None):
    """Try fuzzy match first, then fall back to index from last listed events."""
    client = _get_client(user_id)
    if not client:
        return None, None, "Calendar not configured for this user."

    try:
        if match_reference:
            event, data = _find_event_across_calendars(client, match_reference)
            if event:
                return event, data, None

        if index and user_id in _last_listed:
            entries = _last_listed[user_id]
            if 1 <= index <= len(entries):
                _cal_url, uid = entries[index - 1]
                event, data = _get_event_by_uid_across_calendars(client, uid)
                if event:
                    return event, data, None

        return None, None, "Could not find a matching event. Try 'list events' first, then reference it by name or number."
    except Exception as e:
        logger.error(f"CalDAV resolve failed: {e}", exc_info=True)
        return None, None, f"Failed to search calendar: {e}"


def _add_event_sync(user_id: int, title: str, start: datetime, end: datetime,
                    location: str | None, description: str | None):
    client = _get_client(user_id)
    if not client:
        return None, "Calendar not configured for this user."
    try:
        cal = _get_write_calendar(client, user_id)
        kwargs = {'dtstart': start, 'dtend': end, 'summary': title}
        if location:
            kwargs['location'] = location
        if description:
            kwargs['description'] = description
        event = cal.save_event(**kwargs)
        return _extract_event_data(event, calendar_name=cal.name), None
    except Exception as e:
        logger.error(f"CalDAV add failed: {e}", exc_info=True)
        return None, f"Failed to add event: {e}"


def _modify_event_sync(user_id: int, match_reference: str | None, index: int | None,
                       new_title: str | None, new_start: datetime | None, new_end: datetime | None,
                       new_location: str | None, new_description: str | None):
    event, old_data, error = _resolve_event_sync(user_id, match_reference, index)
    if error or not event:
        return None, None, error or "Event not found."

    try:
        vevent = event.vobject_instance.vevent
        if new_title:
            vevent.summary.value = new_title
        if new_start:
            vevent.dtstart.value = new_start
        if new_end:
            if hasattr(vevent, 'dtend'):
                vevent.dtend.value = new_end
            else:
                vevent.add('dtend').value = new_end
        if new_location:
            if hasattr(vevent, 'location'):
                vevent.location.value = new_location
            else:
                vevent.add('location').value = new_location
        if new_description:
            if hasattr(vevent, 'description'):
                vevent.description.value = new_description
            else:
                vevent.add('description').value = new_description

        event.save()
        new_data = _extract_event_data(event)
        return old_data, new_data, None
    except Exception as e:
        logger.error(f"CalDAV modify failed: {e}", exc_info=True)
        return None, None, f"Failed to modify event: {e}"


def _delete_event_sync(user_id: int, match_reference: str | None, index: int | None):
    event, data, error = _resolve_event_sync(user_id, match_reference, index)
    if error or not event:
        return None, error or "Event not found."
    try:
        event.delete()
        return data, None
    except Exception as e:
        logger.error(f"CalDAV delete failed: {e}", exc_info=True)
        return None, f"Failed to delete event: {e}"


# ─── Async public API ────────────────────────────────────────────────────────

async def list_events(user_id: int, user_name: str, days_ahead: int = 7) -> str:
    events, error = await asyncio.to_thread(_list_events_sync, user_id, days_ahead)
    if error:
        return f"❌ {error}"
    if not events:
        return f"📅 No events in the next {days_ahead} days for {user_name}."

    _last_listed[user_id] = [
        (e.get('calendar_name', ''), e['uid']) for e in events if e.get('uid')
    ]

    lines = [f"📅 Upcoming events for {user_name} (next {days_ahead} days):"]
    for i, e in enumerate(events, 1):
        lines.append(_format_event_line(i, e))
    return '\n'.join(lines)


async def add_event(user_id: int, title: str, start_iso: str, end_iso: str | None,
                    location: str | None = None, description: str | None = None) -> str:
    try:
        start = _parse_iso(start_iso)
        end = _parse_iso(end_iso) if end_iso else start + timedelta(hours=1)
    except (ValueError, AttributeError) as e:
        return f"❌ Invalid date format ({e}). Use ISO 8601 like 2026-05-19T14:00:00."

    data, error = await asyncio.to_thread(_add_event_sync, user_id, title, start, end, location, description)
    if error:
        return f"❌ {error}"

    lines = [f"✅ Event created: {data['summary']}"]
    lines.append(f"📅 {start.strftime('%Y-%m-%d %H:%M')}-{end.strftime('%H:%M')}")
    if data.get('calendar_name'):
        lines.append(f"🗓️ Calendar: {data['calendar_name']}")
    if location:
        lines.append(f"📍 {location}")
    return '\n'.join(lines)


async def modify_event(user_id: int, match_reference: str | None, index: int | None,
                       new_title: str | None = None, new_start_iso: str | None = None,
                       new_end_iso: str | None = None, new_location: str | None = None,
                       new_description: str | None = None) -> str:
    try:
        new_start = _parse_iso(new_start_iso) if new_start_iso else None
        new_end = _parse_iso(new_end_iso) if new_end_iso else None
    except (ValueError, AttributeError) as e:
        return f"❌ Invalid date format ({e}). Use ISO 8601 like 2026-05-19T14:00:00."

    if not any([new_title, new_start, new_end, new_location, new_description]):
        return "❌ No changes specified. Tell me what to update (title, time, location, or description)."

    old_data, new_data, error = await asyncio.to_thread(
        _modify_event_sync, user_id, match_reference, index,
        new_title, new_start, new_end, new_location, new_description,
    )
    if error:
        return f"❌ {error}"

    lines = [f"✏️ Event updated: {new_data['summary']}"]
    new_start_dt = new_data.get('start')
    new_end_dt = new_data.get('end')
    old_start = old_data.get('start')
    if isinstance(new_start_dt, datetime):
        time_line = f"📅 {new_start_dt.strftime('%Y-%m-%d %H:%M')}"
        if isinstance(new_end_dt, datetime):
            time_line += f"-{new_end_dt.strftime('%H:%M')}"
        if isinstance(old_start, datetime) and old_start != new_start_dt:
            time_line += f" (was {old_start.strftime('%Y-%m-%d %H:%M')})"
        lines.append(time_line)
    if new_data.get('location'):
        lines.append(f"📍 {new_data['location']}")
    return '\n'.join(lines)


async def delete_event(user_id: int, match_reference: str | None, index: int | None) -> str:
    data, error = await asyncio.to_thread(_delete_event_sync, user_id, match_reference, index)
    if error:
        return f"❌ {error}"
    title = data.get('summary', '(no title)') if data else '(no title)'
    return f"🗑️ Deleted: {title}"
