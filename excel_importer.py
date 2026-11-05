"""
excel_importer.py
------------------
Turns a registrar's "courses offered this term" Excel sheet into the same
normalized course-section format the rest of the app uses --

    {code, section, title, days: ["Mon", ...], start: "HH:MM"|None,
     end: "HH:MM"|None, credits, instructor, seats_total, seats_available,
     risk, online}

Every university formats this differently, so this is NOT hardcoded to
one layout. Real-world sheets this has been validated against include
ones with: multiple sheets in one workbook (only one of which is the
actual course list), thousands of blank "Unnamed" columns left over from
spreadsheet formatting, a single combined "days + time" column instead of
separate ones (e.g. "(E) 03:30PM - 05:00PM MW"), and async/online rows
with no meeting time at all.

Flow:
  1. list_sheets(path)                  -> sheet names in the workbook
  2. read_headers(path, sheet_name)     -> usable column names on that sheet
  3. guess_mapping(headers)             -> best-effort column -> field guess
  4. parse_with_mapping(path, mapping, sheet_name) -> normalized rows + errors

The human confirms/fixes the guessed mapping in the UI before anything is
imported, so a wrong guess never silently corrupts data.
"""

import re
import pandas as pd

# The fields we need out of a sheet, and how we describe them in the UI.
# "days"/"start"/"end" are one way to give the meeting schedule; "meeting"
# (a single combined column) is the alternative -- a sheet needs to
# provide one or the other, not necessarily both.
TARGET_FIELDS = {
    "code": "Course code (e.g. COSC121)",
    "section": "Section (e.g. A, 01)",
    "title": "Course title",
    "credits": "Credit hours",
    "days": "Meeting days (e.g. MWF, Mon/Wed) -- if days/time are separate columns",
    "start": "Start time -- if days/time are separate columns",
    "end": "End time -- if days/time are separate columns",
    "meeting": "Combined days + time (e.g. '(E) 3:30PM-5:00PM MW') -- if it's ONE column",
    "instructor": "Instructor",
    "seats_total": "Seats / capacity (optional)",
    "seats_available": "Seats remaining (optional)",
    "department": "Department / academic unit (optional, e.g. 'IT', 'Business') -- lets Browse group and filter by department",
    "location": "Classroom / room (optional) -- shown on the plan and added to calendar events",
    "start_date": "First day of this class (optional) -- calendar events start here",
    "end_date": "Last day of this class (optional) -- calendar events stop here",
    "prerequisites": "Pre-requisite (optional, e.g. 'ITEC 101,MATH 177' or 'NONE') -- shown in Browse",
}

BASE_REQUIRED_FIELDS = ["code", "section", "title", "credits"]

# negative signals: a header matching a field's keyword but ALSO containing
# one of these is almost certainly something else (e.g. "Start Date" is the
# term's start date, not a class's start time) -- skip it for that field.
_GUESS_EXCLUDE = {
    "start": ["date"],
    "end": ["date"],
}

# keywords used to auto-guess which sheet column maps to which target field
_GUESS_KEYWORDS = {
    "code": ["course code", "coursecode", "course #", "course no", "subj", "course id", "code"],
    "section": ["section", "sec", "sect"],
    "title": ["title", "course name", "description", "course title"],
    "credits": ["credit", "credits", "cr hrs", "units"],
    "days": ["day", "days", "meeting days", "schedule day"],
    "start": ["start time", "start", "begin", "from time"],
    "end": ["end time", "end", "finish", "to time"],
    "meeting": ["meeting time", "class time", "time slot", "schedule", "time"],
    "instructor": ["instructor", "faculty", "professor", "teacher"],
    "seats_total": ["capacity", "seats", "max enroll", "seat total", "size"],
    "seats_available": ["available", "open seats", "remaining", "seats left", "seats open"],
    "department": ["acad. dept", "academic dept", "dept", "department", "division", "school", "program"],
    "location": ["classroom", "room", "location", "venue", "building", "bldg"],
    "start_date": ["start date", "begin date", "first day", "begins"],
    "end_date": ["end date", "last day", "finish date", "ends"],
    "prerequisites": ["pre-requisite", "prerequisite", "pre-req", "prereq"],
}

DAY_ALIASES = {
    "m": "Mon", "mo": "Mon", "mon": "Mon", "monday": "Mon",
    "t": "Tue", "tu": "Tue", "tue": "Tue", "tues": "Tue", "tuesday": "Tue",
    "w": "Wed", "we": "Wed", "wed": "Wed", "wednesday": "Wed",
    "r": "Thu", "th": "Thu", "thu": "Thu", "thur": "Thu", "thurs": "Thu", "thursday": "Thu",
    "f": "Fri", "fr": "Fri", "fri": "Fri", "friday": "Fri",
    "s": "Sat", "sa": "Sat", "sat": "Sat", "saturday": "Sat",
    "u": "Sun", "su": "Sun", "sun": "Sun", "sunday": "Sun",
}

_ASYNC_KEYWORDS = ("online", "async", "tba", "tbd", "n/a")


def list_sheets(path):
    return pd.ExcelFile(path).sheet_names


def _clean_columns(df):
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _drop_phantom_columns(df):
    """
    Some real workbooks carry thousands of blank 'Unnamed: N' columns from
    stray cell formatting far outside the actual data range -- occasionally
    with a stray leftover value or two (someone typed a note far off the
    real table once). They're useless for mapping and would make the
    column-picker unusable, so drop any unnamed column that isn't
    meaningfully populated (fewer than 2 values, or under 5% filled).
    """
    keep = []
    min_filled = max(2, len(df) * 0.05)
    for col in df.columns:
        if re.match(r"^Unnamed: \d+$", col) and df[col].notna().sum() < min_filled:
            continue
        keep.append(col)
    return df[keep]


def read_headers(path, sheet_name=0):
    df = pd.read_excel(path, sheet_name=sheet_name)
    df = _clean_columns(df)
    df = _drop_phantom_columns(df)
    return [str(c) for c in df.columns]


def guess_mapping(headers):
    """Best-effort column -> target-field guess, for the UI to pre-fill and let the user correct."""
    mapping = {}
    lower_headers = {h: h.lower().strip() for h in headers}
    for field, keywords in _GUESS_KEYWORDS.items():
        excludes = _GUESS_EXCLUDE.get(field, [])
        best = None
        for h, lh in lower_headers.items():
            if any(ex in lh for ex in excludes):
                continue
            if any(kw in lh for kw in keywords):
                best = h
                break
        if best:
            mapping[field] = best
    return mapping


def _parse_days(raw):
    """
    Handles: 'MWF', 'TR', 'TTh', 'Mon/Wed/Fri', 'Mon, Wed, Fri', 'M W F',
    full day names, and mixed case. Longest aliases are matched first so
    'Th' isn't eaten as 'T' + 'h'.
    """
    if raw is None:
        return []
    text = str(raw).strip()
    if not text or text.lower() in ("nan", "none", "nat"):
        return []

    tokens = re.split(r"[\/,;\s]+", text)
    days = []

    def consume_run(run):
        run = run.lower()
        i = 0
        while i < len(run):
            matched = False
            for length in (3, 2, 1):
                chunk = run[i:i + length]
                if chunk in DAY_ALIASES:
                    day = DAY_ALIASES[chunk]
                    if day not in days:
                        days.append(day)
                    i += length
                    matched = True
                    break
            if not matched:
                i += 1

    for tok in tokens:
        tok = tok.strip(".()")
        if not tok:
            continue
        if len(tok) <= 3 and tok.lower() not in DAY_ALIASES:
            consume_run(tok)
        elif tok.lower() in DAY_ALIASES:
            days.append(DAY_ALIASES[tok.lower()])
        else:
            consume_run(tok)

    seen = []
    for d in days:
        if d not in seen:
            seen.append(d)
    return seen


_TIME_RE = re.compile(r"(\d{1,2}):?(\d{2})?\s*([AaPp][Mm])?")


def _parse_time(raw):
    """Accepts '9:00 AM', '09:00', '900', '13:00', '1:30pm' -> returns 'HH:MM' (24h) or None."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in ("nan", "none", "nat"):
        return None

    m = _TIME_RE.search(text)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    ampm = (m.group(3) or "").lower()

    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


_MEETING_TIME_RANGE_RE = re.compile(
    r"(\d{1,2}:\d{2}\s*[AaPp][Mm])\s*(?:-|–|to)\s*(\d{1,2}:\d{2}\s*[AaPp][Mm])"
)


def _parse_meeting_pattern(raw):
    """
    Parses a single combined 'days + time' cell, e.g.:
        '(E) 03:30PM - 05:00PM MW'   -> days after the time range
        'MWF 9:00-9:50am'            -> days before the time range (fallback)
        'Online' / 'TBA'             -> async, no fixed meeting time

    Returns (days, start, end, is_async). On a genuine parse failure
    (unrecognized text that ISN'T an async marker), returns
    (None, None, None, False) so the caller can flag it as an error
    instead of silently importing bad data.
    """
    if raw is None:
        return None, None, None, False
    text = str(raw).strip()
    if not text or text.lower() in ("nan", "none", "nat"):
        return None, None, None, False

    if any(kw in text.lower() for kw in _ASYNC_KEYWORDS):
        return [], None, None, True

    m = _MEETING_TIME_RANGE_RE.search(text)
    if not m:
        return None, None, None, False

    start = _parse_time(m.group(1))
    end = _parse_time(m.group(2))
    if not start or not end:
        return None, None, None, False

    after = text[m.end():]
    before = text[:m.start()]
    days = _parse_days(after) or _parse_days(before)
    if not days:
        return None, None, None, False

    return days, start, end, False


def _risk_from_seats(total, available):
    if available is None:
        return "unknown"
    try:
        available = float(available)
    except (TypeError, ValueError):
        return "unknown"
    if available <= 0:
        return "full"
    if available <= 5:
        return "fills fast"
    return "low"


_NO_LOCATION = {"", "tbd", "tba", "tbc", "n/a", "na", "nan", "none", "nat", "-"}


def parse_prerequisites(raw):
    """'ITEC 101,MATH 177' -> ['ITEC 101', 'MATH 177']; 'NONE' / blank -> [].
    Text that isn't a course code (e.g. 'Year 3/4') is kept as written."""
    if raw is None or (not isinstance(raw, str) and pd.isna(raw)):
        return []
    out = []
    for part in re.split(r"[,;&]|\band\b", str(raw), flags=re.I):
        part = " ".join(part.split())
        if not part or part.lower() in ("none", "nan", "n/a", "na", "-", "—"):
            continue
        m = re.fullmatch(r"([A-Za-z]{2,5})\s*-?\s*(\d{3}[A-Za-z]?)", part)
        part = f"{m.group(1).upper()} {m.group(2).upper()}" if m else part
        if part not in out:
            out.append(part)
    return out


def _clean_location(raw):
    """A room name, or None when the sheet only says TBD/blank."""
    if raw is None or (not isinstance(raw, str) and pd.isna(raw)):
        return None
    text = str(raw).strip()
    return None if text.lower() in _NO_LOCATION else text


def _parse_date(raw):
    """Any date-looking cell ('2026-08-17', 'December 4, 2026', a real Excel
    date) -> 'YYYY-MM-DD', or None if it isn't one."""
    if raw is None or (not isinstance(raw, str) and pd.isna(raw)):
        return None
    parsed = pd.to_datetime(raw, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def parse_with_mapping(path, mapping, sheet_name=0):
    """
    mapping: {target_field: source_column_name}. Needs code/section/title/
    credits plus EITHER (days, start, end) OR (meeting).

    Returns (rows, errors) where errors is a list of {row, reason} for
    lines that couldn't be parsed -- surfaced in the UI so nothing gets
    silently dropped.
    """
    missing_base = [f for f in BASE_REQUIRED_FIELDS if f not in mapping]
    has_separate = all(f in mapping for f in ("days", "start", "end"))
    has_combined = "meeting" in mapping
    if missing_base or not (has_separate or has_combined):
        problems = list(missing_base)
        if not (has_separate or has_combined):
            problems.append("days+start+end (or a single combined 'meeting' column)")
        raise ValueError(f"Missing required column mapping for: {', '.join(problems)}")

    df = pd.read_excel(path, sheet_name=sheet_name)
    df = _clean_columns(df)
    rows = []
    errors = []

    for i, record in df.iterrows():
        excel_row = i + 2  # account for header row + 0-index
        try:
            code = str(record.get(mapping["code"])).strip()
            section = str(record.get(mapping["section"])).strip()
            title = str(record.get(mapping["title"])).strip()

            if not code or code.lower() in ("nan", "nat", "none"):
                errors.append({"row": excel_row, "reason": "missing course code"})
                continue

            is_async = False
            if has_combined:
                raw_meeting = record.get(mapping["meeting"])
                days, start, end, is_async = _parse_meeting_pattern(raw_meeting)
                if days is None:
                    errors.append({"row": excel_row, "reason": f"couldn't parse meeting time: {raw_meeting!r}"})
                    continue
            else:
                days = _parse_days(record.get(mapping["days"]))
                start = _parse_time(record.get(mapping["start"]))
                end = _parse_time(record.get(mapping["end"]))
                if not days:
                    errors.append({"row": excel_row, "reason": f"couldn't parse days: {record.get(mapping['days'])!r}"})
                    continue
                if not start or not end:
                    errors.append({"row": excel_row, "reason": f"couldn't parse time: {record.get(mapping['start'])!r} - {record.get(mapping['end'])!r}"})
                    continue

            credits_raw = record.get(mapping["credits"])
            try:
                credits = float(credits_raw)
            except (TypeError, ValueError):
                credits = 3.0

            seats_total = None
            seats_available = None
            if "seats_total" in mapping:
                v = record.get(mapping["seats_total"])
                seats_total = None if pd.isna(v) else float(v)
            if "seats_available" in mapping:
                v = record.get(mapping["seats_available"])
                seats_available = None if pd.isna(v) else float(v)

            instructor = "Staff"
            if "instructor" in mapping:
                v = record.get(mapping["instructor"])
                instructor = "Staff" if pd.isna(v) else str(v).strip()

            department = None
            if "department" in mapping:
                v = record.get(mapping["department"])
                if not pd.isna(v):
                    dep = str(v).strip()
                    if dep and dep.lower() not in ("nan", "none", "nat"):
                        department = dep

            prerequisites = parse_prerequisites(record.get(mapping["prerequisites"])) if "prerequisites" in mapping else []
            location = _clean_location(record.get(mapping["location"])) if "location" in mapping else None
            start_date = _parse_date(record.get(mapping["start_date"])) if "start_date" in mapping else None
            end_date = _parse_date(record.get(mapping["end_date"])) if "end_date" in mapping else None

            # Cross-listed courses sometimes appear as one row with slash-
            # joined codes/sections (e.g. "COSC 111/CSCI 111", "001/001") --
            # split those into one row per code so each still matches its
            # own curriculum entry, instead of becoming an unmatchable
            # code nobody's degree audit actually contains.
            codes = [c.strip() for c in code.split("/")] if "/" in code else [code]
            sections = [s.strip() for s in section.split("/")] if "/" in section else []
            titles = [t.strip() for t in title.split("/")] if "/" in title else []
            if len(sections) != len(codes):
                sections = [section] * len(codes)
            if len(titles) != len(codes):
                titles = [title] * len(codes)

            for idx, c in enumerate(codes):
                rows.append({
                    "code": c,
                    "section": sections[idx] or "A",
                    "title": titles[idx] or c,
                    "days": days,
                    "start": start,
                    "end": end,
                    "credits": credits,
                    "instructor": instructor,
                    "seats_total": seats_total,
                    "seats_available": seats_available,
                    "risk": "unknown" if is_async else _risk_from_seats(seats_total, seats_available),
                    "online": is_async,
                    "department": department,
                    "location": location,
                    "start_date": start_date,
                    "end_date": end_date,
                    "prerequisites": prerequisites,
                })
        except Exception as e:  # keep going on a single bad row
            errors.append({"row": excel_row, "reason": str(e)})

    return rows, errors
