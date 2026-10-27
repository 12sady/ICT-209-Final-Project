"""
curriculum_parser.py
---------------------
Parses a curriculum/degree-requirements table copied from a registration
system's on-screen curriculum view (there's usually no file export for
this, so paste-then-parse is the practical option -- see README).

Expected shape (tab-separated, as a spreadsheet-style copy-paste usually
comes out), one course per line:

    Course Code    Course Name    CATEGORY    Sub-Category    Credits    Course requisites
    COSC 121       Computer Science A    Major        3    -
    ICT 209        Fundamentals of AI    Electives    3    h: ITEC 101

Multiple such tables pasted together (e.g. a "core" block and an
"electives" block copied separately) are handled fine -- repeated header
rows and blank/metadata lines ("Academic Year: -", "Semester: -") are
just skipped.

Category conventions this was built against: "Major", "Core/Major", and
anything literally marked "(Required)" count as REQUIRED; "Electives",
"Major Electives", and a bare "General Education" (no "(Required)") count
as ELECTIVE/optional and are not auto-added to required courses.

Course requisites use a "h: X, Y" (hard/must-complete-first) or
"s: X, Y" (soft, e.g. a suggested corequisite) prefix, or "-" for none.
Only hard requisites are treated as blocking prerequisites -- a soft one
doesn't stop the planner from scheduling the course.
"""

import re

_HEADER_MARKERS = ("course code", "coursecode")
_METADATA_PREFIXES = ("academic year", "semester")

REQUIRED_CATEGORIES = {"major", "core/major"}


def _split_row(line):
    parts = line.split("\t")
    if len(parts) < 5:
        parts = re.split(r"\s{2,}", line.strip())
    return [p.strip() for p in parts]


def _is_required_category(category):
    cat = (category or "").strip().lower()
    if "(required)" in cat:
        return True
    return cat in REQUIRED_CATEGORIES


def _parse_requisites(raw):
    """Returns (hard, soft) lists of course codes."""
    text = (raw or "").strip()
    if not text or text == "-":
        return [], []
    low = text.lower()
    if low.startswith("h:"):
        codes = text[2:].strip()
        return [c.strip() for c in codes.split(",") if c.strip()], []
    if low.startswith("s:"):
        codes = text[2:].strip()
        return [], [c.strip() for c in codes.split(",") if c.strip()]
    # No h:/s: marker but not empty -- treat as a hard requisite list,
    # best-effort (better to over-flag a prereq than silently drop it).
    return [c.strip() for c in text.split(",") if c.strip()], []


def parse_curriculum_text(raw_text):
    """
    Returns {"courses": [...], "unparsed": [...]}.
    Each course: {code, name, category, sub_category, credits, required,
                   hard_prereqs, soft_prereqs}
    """
    courses = []
    unparsed = []
    seen_codes = set()

    for line in raw_text.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        low = line.strip().lower()
        if any(low.startswith(m) for m in _HEADER_MARKERS):
            continue
        if any(low.startswith(m) for m in _METADATA_PREFIXES):
            continue

        parts = _split_row(line)
        if len(parts) < 5:
            unparsed.append(line)
            continue

        # Columns: Code, Name, CATEGORY, Sub-Category, Credits, Requisites
        # Sub-Category is very often blank (shows up as an empty field).
        code, name, category = parts[0], parts[1], parts[2]
        rest = parts[3:]

        if not re.match(r"^[A-Za-z]{2,6}\s?\d{3}", code):
            unparsed.append(line)
            continue

        # Find the credits value (a small number) among the remaining
        # fields, since Sub-Category may or may not be present/blank.
        credits = None
        credits_idx = None
        for idx, val in enumerate(rest):
            if re.match(r"^\d+(\.\d+)?$", val):
                credits = float(val)
                credits_idx = idx
                break
        sub_category = rest[0] if credits_idx not in (0, None) else ""
        requisites_raw = rest[credits_idx + 1] if credits_idx is not None and credits_idx + 1 < len(rest) else ""

        hard, soft = _parse_requisites(requisites_raw)

        if code in seen_codes:
            continue
        seen_codes.add(code)

        courses.append({
            "code": code,
            "name": name,
            "category": category,
            "sub_category": sub_category,
            "credits": credits if credits is not None else 3.0,
            "required": _is_required_category(category),
            "hard_prereqs": hard,
            "soft_prereqs": soft,
        })

    return {"courses": courses, "unparsed": unparsed}
