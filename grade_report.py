"""
grade_report.py
---------------
Reads an AUPP SIS "Grade Report" PDF and turns it into a list of courses
with term and grade, then matches them to the student's curriculum.

Pure logic except `read_pdf` (which needs pdfplumber). The parsing works on
word positions, not on plain text, because in plain text a minus grade runs
into the next line ("B-" + "ENGL 101" -> "BENGL 101").

Layout of the report (checked against a real one):
  - Two columns per page. The LEFT column runs on over every page first, then
    the RIGHT column, so a term box can start at the bottom of page 1's left
    column and continue at the top of page 2's left column.
  - Each term box: "Spring 2023  UA UE UC GR" header, one line per course
    (code, title, units attempted / earned / carried, grade), then
    "Units- Attempted ... Term GPA" and "Academic Standing ... Cum GPA".
  - A code can wrap onto a second line, e.g. "ENGL 101" + "(ENR)".
  - Grades: letter grades, P (pass, not in GPA), RG (registered = in progress),
    "*" marks a repeated course.
  - The SUMMARY at the end gives "Cumulative GPA".

Personal details at the top (ID, name, date of birth) are never read out.
"""

import re

import gpa

TERMS = ("Spring", "Summer", "Fall", "Winter")
_SUBJECT_RE = re.compile(r"^[A-Z]{2,5}\*?$")
_NUMBER_RE = re.compile(r"^\d{3}[A-Z]?\*?$")
_YEAR_RE = re.compile(r"^\d{4}$")
_NUM_RE = re.compile(r"^\d+(\.\d+)?$")
_LINE_TOL = 3.0      # words whose tops differ by less than this are on one line
_COL_TOL = 8.0       # how far a value may sit from its column header (UA/UE/UC/GR)

IN_PROGRESS = {"RG"}                 # registered this term, no grade yet
NOT_PASSED = {"F", "NP", "W", "I", "AU"}


# ---------------------------------------------------------------------------
# PDF -> words  (the only part that needs pdfplumber)
# ---------------------------------------------------------------------------

def read_pdf(fileobj):
    """Words of every page: [{"width", "height", "words": [{x0, top, text}]}].
    Raises ValueError with a plain message if it isn't a readable PDF."""
    try:
        import pdfplumber
    except ImportError:
        raise ValueError("Reading PDFs needs the pdfplumber package: run  pip install pdfplumber  and restart the app.")
    pages = []
    try:
        with pdfplumber.open(fileobj) as pdf:
            for p in pdf.pages:
                words = [{"x0": float(w["x0"]), "top": float(w["top"]), "text": w["text"]}
                         for w in p.extract_words()]
                pages.append({"width": float(p.width), "height": float(p.height), "words": words})
    except Exception:
        raise ValueError("That file couldn't be read as a PDF. Download the grade report again from SIS and try once more.")
    return pages


# ---------------------------------------------------------------------------
# words -> courses
# ---------------------------------------------------------------------------

def _lines(words):
    """Group words into lines (top to bottom), each line sorted left to right."""
    out = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if out and abs(w["top"] - out[-1][0]["top"]) < _LINE_TOL:
            out[-1].append(w)
        else:
            out.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in out]


def _near(line, x):
    """Text of the word in `line` that starts near x (a table column), or ''."""
    for w in line:
        if abs(w["x0"] - x) <= _COL_TOL:
            return w["text"]
    return ""


def _float(s):
    return float(s) if _NUM_RE.match(s or "") else None


def parse_pages(pages):
    """Pages of words (see read_pdf) -> {"courses", "terms", "cum_gpa", "warnings"}.

    courses: [{"code", "name", "term", "grade", "attempted", "carried", "repeated"}] in report order.
    terms:   [{"term", "term_gpa", "cum_gpa"}].
    """
    # Split every page into its left and right column, then read all left
    # columns first, then all right columns (that's how the report flows).
    columns = {"left": [], "right": []}
    for p in pages:
        mid = p["width"] / 2
        top_cut, bottom_cut = 25, p["height"] - 25        # browser print header/footer
        left, right = [], []
        for w in p["words"]:
            if not top_cut < w["top"] < bottom_cut:
                continue
            (left if w["x0"] < mid else right).append(w)
        columns["left"].append(left)
        columns["right"].append(right)

    courses, terms, warnings = [], [], []
    cum_gpa = None

    for side in ("left", "right"):
        cols = None          # x positions of UA/UE/UC/GR for this side (same on every page)
        code_x = None        # x where course codes start on this side
        term = None
        current = None       # course still waiting for its grade line

        for words in columns[side]:
            for line in _lines(words):
                texts = [w["text"] for w in line]

                # SUMMARY: "Cumulative GPA: 3.61"
                if "Cumulative" in texts:
                    i = texts.index("Cumulative")
                    for t in texts[i + 1:]:
                        if _float(t) is not None:
                            cum_gpa = _float(t)
                            break
                    current = None
                    continue

                # Term header: "Fall 2025  UA UE UC GR"
                if len(texts) >= 2 and texts[0] in TERMS and _YEAR_RE.match(texts[1]) and "GR" in texts:
                    term = f"{texts[0]} {texts[1]}"
                    cols = {k: next(w["x0"] for w in line if w["text"] == k) for k in ("UA", "UE", "UC", "GR")}
                    code_x = line[0]["x0"]
                    terms.append({"term": term, "term_gpa": None, "cum_gpa": None})
                    current = None
                    continue
                if cols is None:
                    continue          # still in the page heading (name, ID, ...)

                if texts[0].startswith("Units"):
                    if "GPA:" in texts and terms:
                        terms[-1]["term_gpa"] = _float(texts[texts.index("GPA:") + 1] if texts.index("GPA:") + 1 < len(texts) else "")
                    current = None
                    continue
                if texts[0] == "Academic":
                    if "GPA:" in texts and terms:
                        terms[-1]["cum_gpa"] = _float(texts[texts.index("GPA:") + 1] if texts.index("GPA:") + 1 < len(texts) else "")
                    current = None
                    continue

                at_code = abs(line[0]["x0"] - code_x) <= _COL_TOL
                starts_course = (at_code and len(texts) >= 2 and _SUBJECT_RE.match(texts[0])
                                 and _NUMBER_RE.match(texts[1]))
                if starts_course:
                    current = {"code": f"{texts[0]} {texts[1]}", "name": "", "term": term,
                               "grade": "", "attempted": None, "carried": None, "repeated": False}
                    if term is None:
                        warnings.append(f"Found {current['code']} before any term heading; skipped it.")
                        current = None
                        continue
                    courses.append(current)
                    rest = line[2:]
                elif at_code and current is not None and texts[0].startswith("("):
                    current["code"] += " " + texts[0]          # "ENGL 101" + "(ENR)"
                    rest = line[1:]
                else:
                    rest = line

                if current is None:
                    continue
                name = [w["text"] for w in rest if w["x0"] < cols["UA"] - _COL_TOL]
                if name:
                    current["name"] = (current["name"] + " " + " ".join(name)).strip()
                grade = _near(rest, cols["GR"])
                if grade and not current["grade"]:
                    current["grade"] = grade
                    current["attempted"] = _float(_near(rest, cols["UA"]))
                    current["carried"] = _float(_near(rest, cols["UC"]))

    for c in courses:
        if "*" in c["code"] or "*" in c["grade"]:
            c["repeated"] = True
            c["code"] = c["code"].replace("*", "").strip()
            c["grade"] = c["grade"].replace("*", "").strip()
        c["grade"] = c["grade"].upper()
        if not c["grade"]:
            warnings.append(f"{c['code']} ({c['term']}) has no grade on the report.")
    return {"courses": courses, "terms": terms, "cum_gpa": cum_gpa, "warnings": warnings}


# ---------------------------------------------------------------------------
# courses -> what to change in the student's curriculum
# ---------------------------------------------------------------------------

def _norm(code):
    return re.sub(r"\s+", "", str(code or "")).upper()


def _base(code):
    """'MATH234A' -> 'MATH234' (drop a trailing section letter)."""
    n = _norm(code)
    return n[:-1] if re.search(r"\d[A-Z]$", n) else n


def status_of(grade):
    g = gpa.normalize_grade(grade)
    if grade in IN_PROGRESS:
        return "in_progress"
    if not g:
        return "unknown_grade"
    if g in NOT_PASSED:
        return "not_passed"
    return "completed"


def match(parsed, catalog):
    """Pair each course on the report with a course in the curriculum.

    Returns rows: {"report_code", "code" (curriculum code or None), "match"
    ("exact" | "similar" | "none"), "name", "term", "grade", "credits",
    "status", "repeated"}. A course taken twice keeps only its latest attempt.
    """
    by_norm = {_norm(c["code"]): c for c in catalog}
    by_base = {}
    for c in catalog:
        by_base.setdefault(_base(c["code"]), []).append(c)

    latest = {}
    for c in parsed["courses"]:
        key = _norm(c["code"])
        old = latest.get(key)
        if old is None or (gpa.term_key(c["term"]) or 0) >= (gpa.term_key(old["term"]) or 0):
            latest[key] = c

    rows = []
    for c in latest.values():
        hit, how = by_norm.get(_norm(c["code"])), "exact"
        if hit is None and "(" not in c["code"]:
            similar = by_base.get(_base(c["code"])) or []
            hit, how = (similar[0], "similar") if len(similar) == 1 else (None, "none")
        if hit is None:
            how = "none"
        credits = c["carried"] if c["carried"] else c["attempted"]
        if hit is not None and not credits:
            credits = hit.get("credits")
        rows.append({
            "report_code": c["code"], "code": hit["code"] if hit else None, "match": how,
            "name": (hit or {}).get("name") or c["name"], "report_name": c["name"],
            "term": c["term"], "grade": gpa.normalize_grade(c["grade"]) or c["grade"],
            "credits": credits or 0, "status": status_of(c["grade"]), "repeated": c["repeated"],
        })
    rows.sort(key=lambda r: (gpa.term_key(r["term"]) or 0, r["report_code"]))
    return rows


EXTRA_CATEGORY = "From grade report"


def add_in_progress(req, items):
    """Courses the report shows as in progress (RG) that are NOT in the curriculum yet: add them under
    EXTRA_CATEGORY and remember them as in progress. items: [{"code", "name", "credits"}].
    Returns (new_req, number_added_to_the_catalog)."""
    out = dict(req)
    catalog = [dict(c) for c in req.get("catalog", [])]
    known = {_norm(c["code"]) for c in catalog}
    in_progress = list(req.get("in_progress", []))
    done = {_norm(c) for c in req.get("completed", [])}
    added = 0
    for it in items or []:
        code = str((it or {}).get("code") or "").strip()
        if not code or _norm(code) in done:
            continue
        if _norm(code) not in known:
            try:
                credits = float(it.get("credits") or 0)
            except (TypeError, ValueError):
                credits = 0
            catalog.append({"code": code, "name": str(it.get("name") or "")[:200], "category": EXTRA_CATEGORY, "sub_category": "",
                            "credits": (int(credits) if credits.is_integer() else credits) if credits > 0 else 3,
                            "required": False, "hard_prereqs": [], "soft_prereqs": []})
            known.add(_norm(code))
            added += 1
        if code not in in_progress:
            in_progress.append(code)
    out.update(catalog=catalog, in_progress=in_progress)
    return out, added


def apply(req, picked):
    """Merge picked rows into a requirements dict (a copy is returned).

    picked: [{"code", "grade", "term", "add": {"name", "credits"}?}] where `code`
    is the curriculum code, or the report code together with "add" for a course
    that isn't in the curriculum yet (it's added under EXTRA_CATEGORY).
    Only completed courses (passing grade or P) are applied. Returns
    (new_req, counts) or raises ValueError with a plain message.
    """
    out = dict(req)
    catalog = [dict(c) for c in req.get("catalog", [])]
    codes = {c["code"] for c in catalog}
    completed = list(req.get("completed", []))
    sems = dict(req.get("completed_semesters") or {})
    grades = dict(req.get("grades") or {})
    added = marked = graded = 0

    for p in picked:
        code = str(p.get("code") or "").strip()
        grade = gpa.normalize_grade(p.get("grade"))
        if not code:
            raise ValueError("A course in the list has no code.")
        if status_of(grade) != "completed":
            raise ValueError(f"{code}: only passed courses can be marked completed (got '{p.get('grade')}').")
        if code not in codes:
            extra = p.get("add")
            if not isinstance(extra, dict):
                raise ValueError(f"{code} isn't in your curriculum.")
            try:
                credits = float(extra.get("credits") or 0)
            except (TypeError, ValueError):
                credits = 0
            if credits <= 0:
                raise ValueError(f"{code}: needs a credit value to be added.")
            catalog.append({"code": code, "name": str(extra.get("name") or "")[:200], "category": EXTRA_CATEGORY,
                            "sub_category": "", "credits": int(credits) if credits.is_integer() else credits,
                            "required": False, "hard_prereqs": [], "soft_prereqs": []})
            codes.add(code)
            added += 1
        if code not in completed:
            completed.append(code)
            marked += 1
        term = str(p.get("term") or "").strip()
        if gpa.term_key(term):
            sems[code] = term
        grades[code] = grade
        graded += 1

    out.update(catalog=catalog, completed=completed, completed_semesters=sems, grades=grades)
    out["required_remaining"] = [c["code"] for c in catalog if c.get("required") and c["code"] not in set(completed)]
    return out, {"added_to_curriculum": added, "newly_completed": marked, "grades_set": graded}
