"""
sheet.py
--------
Pure helpers for the printable registration-day sheet (no Flask, no files).
"""

from datetime import date, datetime


def countdown(registration_date, today):
    """Days until registration opens. registration_date: 'YYYY-MM-DD' or None.
    Returns None when no (valid) date is set, otherwise
    {state: 'future'|'today'|'past', days: int >= 0, date, label}."""
    if not registration_date:
        return None
    try:
        when = datetime.strptime(str(registration_date)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    if isinstance(today, datetime):
        today = today.date()
    delta = (when - today).days
    pretty = f"{when.strftime('%A')} {when.day} {when.strftime('%B %Y')}"
    if delta > 0:
        return {"state": "future", "days": delta, "date": when.isoformat(),
                "label": f"Registration opens in {delta} day{'s' if delta != 1 else ''} ({pretty})"}
    if delta == 0:
        return {"state": "today", "days": 0, "date": when.isoformat(), "label": f"Registration opens today ({pretty})"}
    return {"state": "past", "days": -delta, "date": when.isoformat(),
            "label": f"Registration opened {-delta} day{'s' if -delta != 1 else ''} ago ({pretty})"}


def when_text(section):
    """'Mon/Wed 09:00-10:30' or 'Online / no fixed time'."""
    if section.get("online") or not section.get("start") or not section.get("end") or not section.get("days"):
        return "Online / no fixed time"
    return f"{'/'.join(section['days'])} {section['start']}-{section['end']}"


def sheet_row(section, backups):
    """One printable row: the chosen section plus its backup sections."""
    return {
        "code": section["code"], "section": section["section"], "title": section.get("title") or "",
        "when": when_text(section), "room": section.get("location") or "", "instructor": section.get("instructor") or "",
        "credits": section.get("credits"), "risk": section.get("risk") or "unknown",
        "backups": [{"section": b["section"], "when": when_text(b), "room": b.get("location") or ""} for b in backups],
    }


def total_credits(sections):
    return sum(float(s.get("credits") or 0) for s in sections)
