"""
parser.py
---------
Best-effort parser for course schedule text pasted from a registration
system that has no file export (copy the on-screen schedule, paste it
here). Day/time parsing is shared with excel_importer.py so "MWF",
"TR"/"TTh", "Mon/Wed", 12h/24h times, and combined "days + time" cells
like "(E) 3:30PM - 5:00PM MW" all work the same way whether the data
came from a spreadsheet cell or pasted free text.

Two input shapes are handled:

1. TABLE rows -- what you get from selecting and copying an on-screen
   grid (tab-separated when pasted from a browser table, e.g. Rean),
   one course section per line:
       ACCT 201    001    Financial Accounting    3.0    D. Tereladze    (E) 03:30PM - 05:00PM MW
   This is tried first, since it's what most real copy-pastes look like.

2. Plain free-text lines (a fallback for schedules with no clear column
   structure), e.g.:
       COSC121 A Data Structures Mon Wed 09:00-10:30 3
       ITM 201 A Java Programming I MWF 9:00 AM-9:50 AM 3

Course codes are accepted with OR without a space between the department
letters and the number ("ACCT201" and "ACCT 201" both work) and are
normalized to the spaced form, since that's what the rest of the app
(curriculum entries, prerequisites) uses -- so codes actually match up.

If your actual export looks different from either shape, adjust the
regexes/heuristics below -- that adaptation process is itself good
material for the "troubleshooting / tool adaptation" part of a
presentation.
"""

import re

from excel_importer import DAY_ALIASES, _parse_time, _parse_meeting_pattern

# Department letters + course number, space optional between them, e.g.
# "ACCT 201", "ACCT201", "COSC 111A". Real AUPP codes always have the
# space; some schools' don't -- both are accepted.
CODE_RE = re.compile(r"\b([A-Za-z]{2,6})\s?(\d{3}[A-Za-z]?)\b")


def _normalize_code(dept, number):
    return f"{dept.upper()} {number.upper()}"


# ---------------------------------------------------------------------------
# Shape 1: table rows (tab-separated, or column-aligned with 2+ spaces)
# ---------------------------------------------------------------------------

SECTION_RE = re.compile(r"^[A-Za-z0-9]{1,4}(?:/[A-Za-z0-9]{1,4})*$")
_CREDITS_FIELD_RE = re.compile(r"^(\d(?:\.\d)?)\s*(?:cr|credits?)?$", re.IGNORECASE)
_NOISE_FIELDS = ("tbd", "tba", "n/a", "-", "")


def _split_row(line):
    parts = line.split("\t")
    if len(parts) < 3:
        parts = re.split(r"\s{2,}", line.strip())
    return [p.strip() for p in parts]


def _parse_row_based(line):
    """
    Returns a LIST of parsed section dicts (almost always length 1; more
    for a cross-listed row like "COSC 111/CSCI 111"), or None if this
    line doesn't look tabular enough to trust (caller falls back to the
    free-text parser). Requires BOTH a recognizable course code AND a
    recognizable meeting time somewhere in the row -- that combination is
    a strong enough signal that this really is a schedule row, not some
    other kind of pasted text.
    """
    fields = _split_row(line)
    if len(fields) < 3:
        return None

    code = None
    code_field = None
    code_idx = None
    for i, f in enumerate(fields):
        m = CODE_RE.fullmatch(f) or CODE_RE.search(f)
        if m:
            code = _normalize_code(m.group(1), m.group(2))
            code_field = f
            code_idx = i
            break
    if code is None:
        return None

    # A field can hold more than one candidate meeting-time-shaped value --
    # e.g. an online/async course whose Faculty column literally says
    # "Online UA" collides with the Time column saying "Online". A real
    # time RANGE (an actual "9:00AM - 10:30AM" match) is unambiguous, so
    # prefer that over a bare async-keyword guess; among async-keyword-only
    # matches, prefer the LAST one, since the schedule/time column usually
    # comes after the instructor column in these layouts.
    meeting_idx = None
    days = start = end = None
    is_async = False
    async_fallback_idx = None
    for i, f in enumerate(fields):
        if i <= code_idx:
            continue
        d, s, e, async_flag = _parse_meeting_pattern(f)
        if d is not None and not async_flag:
            meeting_idx, days, start, end, is_async = i, d, s, e, False
            break
        if async_flag:
            async_fallback_idx = i
    if meeting_idx is None and async_fallback_idx is not None:
        meeting_idx, days, start, end, is_async = async_fallback_idx, [], None, None, True
    if meeting_idx is None:
        return None

    credits = 3.0
    credits_idx = None
    for i, f in enumerate(fields):
        if i in (code_idx, meeting_idx):
            continue
        m = _CREDITS_FIELD_RE.match(f)
        if m:
            credits, credits_idx = float(m.group(1)), i
            break

    section = "A"
    section_idx = None
    after_code = code_idx + 1
    if after_code < len(fields) and after_code not in (meeting_idx, credits_idx):
        cand = fields[after_code]
        if cand and SECTION_RE.match(cand):
            section, section_idx = cand, after_code

    title_start = (section_idx + 1) if section_idx is not None else after_code
    stop_points = [i for i in (meeting_idx, credits_idx) if i is not None and i >= title_start]
    title_end = min(stop_points) if stop_points else len(fields)
    title_indices = set(range(title_start, title_end))
    title_parts = [fields[i] for i in sorted(title_indices) if fields[i]]
    title = " ".join(title_parts).strip(" .-") or code

    # Instructor: whatever text field is left over that isn't code/section/
    # title/credits/meeting -- commonly sits between credits and the
    # meeting-time column (e.g. "... Credit  Faculty  Time*  Classroom"),
    # but check after the meeting column too in case the layout differs.
    used = {code_idx, meeting_idx} | title_indices
    if section_idx is not None:
        used.add(section_idx)
    if credits_idx is not None:
        used.add(credits_idx)
    instructor = "Staff"
    for i, f in enumerate(fields):
        if i in used:
            continue
        if f and f.lower() not in _NOISE_FIELDS and not re.match(r"^\d", f):
            instructor = f
            break

    # Cross-listed courses sometimes show up as one row with slash-joined
    # codes/sections (e.g. "COSC 111/CSCI 111", section "001/001") --
    # split those into one row per code, same as the Excel importer does,
    # so each still matches its own curriculum entry.
    if "/" in code_field:
        code_parts = [p.strip() for p in code_field.split("/")]
        codes = []
        for p in code_parts:
            m = CODE_RE.fullmatch(p) or CODE_RE.search(p)
            codes.append(_normalize_code(m.group(1), m.group(2)) if m else p)
    else:
        codes = [code]

    section_parts = section.split("/") if "/" in section else []
    title_parts_split = title.split("/") if "/" in title else []
    sections = section_parts if len(section_parts) == len(codes) else [section] * len(codes)
    titles = (
        [t.strip() for t in title_parts_split] if len(title_parts_split) == len(codes) else [title] * len(codes)
    )

    return [
        {
            "code": c,
            "section": sections[idx].strip() or "A",
            "title": titles[idx] or c,
            "days": days,
            "start": start,
            "end": end,
            "credits": credits,
            "instructor": instructor,
            "seats_total": None,
            "seats_available": None,
            "risk": "unknown",
            "online": is_async,
        }
        for idx, c in enumerate(codes)
    ]


# ---------------------------------------------------------------------------
# Shape 2: plain free-text lines (fallback when there's no clear structure)
# ---------------------------------------------------------------------------

def _strict_day_tokens(word):
    """
    A token only counts as "day-shaped" if it fully decomposes into day
    aliases with nothing left over -- otherwise words like "Structures"
    or "Culture" get misread as day codes, since they happen to contain
    single letters ('s', 't', 'r'...) that are valid day abbreviations on
    their own. Returns the list of days, or None if the token isn't
    purely a day specifier.
    """
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return None
    i = 0
    days = []
    while i < len(w):
        matched = False
        for length in (3, 2, 1):
            chunk = w[i:i + length]
            if chunk in DAY_ALIASES:
                day = DAY_ALIASES[chunk]
                if day not in days:
                    days.append(day)
                i += length
                matched = True
                break
        if not matched:
            return None
    return days or None


CREDITS_RE = re.compile(r"(\d(?:\.\d)?)\s*(?:cr|credits?)?\s*$", re.IGNORECASE)
_TIME_TOKEN = r"\d{1,2}(?::\d{2})?\s*(?:[AaPp][Mm])?"
TIME_RANGE_RE = re.compile(rf"({_TIME_TOKEN})\s*(?:-|–|to)\s*({_TIME_TOKEN})")


def _split_words(text):
    return re.findall(r"[A-Za-z0-9./]+", text)


def _parse_free_text(line):
    code_match = CODE_RE.search(line)
    time_match = TIME_RANGE_RE.search(line)
    if not (code_match and time_match):
        return None

    start = _parse_time(time_match.group(1))
    end = _parse_time(time_match.group(2))
    if not start or not end:
        return None

    code = _normalize_code(code_match.group(1), code_match.group(2))
    middle = line[code_match.end():time_match.start()]
    words = _split_words(middle)

    section = "A"
    remaining = words
    if remaining and SECTION_RE.match(remaining[0]) and _strict_day_tokens(remaining[0]) is None:
        section = remaining[0]
        remaining = remaining[1:]

    days = []
    while remaining:
        candidate = _strict_day_tokens(remaining[-1])
        if candidate is None:
            break
        days = candidate + days
        remaining = remaining[:-1]

    if not days:
        return None

    title = " ".join(remaining).strip(" .-") or code
    credits_match = CREDITS_RE.search(line[time_match.end():])
    credits = float(credits_match.group(1)) if credits_match else 3.0

    return {
        "code": code,
        "section": section,
        "title": title,
        "days": days,
        "start": start,
        "end": end,
        "credits": credits,
        "instructor": "Staff",
        "seats_total": None,
        "seats_available": None,
        "risk": "unknown",
        "online": False,
    }


# ---------------------------------------------------------------------------

def parse_schedule_text(raw_text):
    """
    Returns (parsed_sections, unparsed_lines) so the UI can show what it
    understood and let you fix or manually add anything it missed.
    """
    parsed = []
    unparsed = []

    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue

        rows = _parse_row_based(line)
        if rows is None:
            single = _parse_free_text(line)
            rows = [single] if single else None

        if rows is None:
            unparsed.append(line)
        else:
            parsed.extend(rows)

    return parsed, unparsed


if __name__ == "__main__":
    sample = """ACCT 201\t001\tFinancial Accounting\t3.0\tDavid TERELADZE\t(E) 03:30PM - 05:00PM MW\tTBD
COSC121 A Data Structures Mon Wed 09:00-10:30 3
ITM 201 A Java Programming I MWF 9:00 AM-9:50 AM 3
HUMN110 A Arts and Culture TR 1:00 PM-2:15 PM 3cr
this line is garbage and should be unparsed"""
    p, u = parse_schedule_text(sample)
    for row in p:
        print(row)
    print("Unparsed:", u)
