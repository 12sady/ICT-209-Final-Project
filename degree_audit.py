"""
degree_audit.py
---------------
Reads an AUPP SIS "Official Degree Audit" PDF and turns it into the student's
own curriculum: every course with the audit's category, the credits each
category needs, and which courses are passed / in progress.

The sample plans are public and the same for everyone; the degree audit is
private and differs per student (catalog year, category rules), so uploading
it is the accurate way to get your real curriculum.

Pure logic except `read_pdf` (which needs pdfplumber). Parsing works on word
positions, like grade_report.py. Layout (checked against a real audit):

  - Page 1 header: "Catalog Term : Fall 2024" and "Degree : Bachelor of ...".
    The student's ID, name and date of birth are never read out.
  - A table with the columns  Category | AUPP CSN | Course Name | Credits |
    Semester | Grade | Credits Earned. Cells wrap: a code can put its number on
    the next line ("MATH" + "234A"), the semester its year ("Summer" + "2026"),
    and the category "(Required)".
  - Category looks like "M - Major", "ME - Major Electives",
    "GER - General Education (Required)", "CM - Core/Major". A BLANK category
    is a shaded row: "Shaded courses are not included in the credit totals".
  - Grade RG = registered (in progress, not passed yet). No grade and no
    semester = not taken yet.
  - Last page: a summary "Required: Completed:" with the total and one line per
    category. It is used to size each category and to cross-check our reading.
"""

import copy
import re

import gpa
import grade_report

_SUBJECT_RE = re.compile(r"^[A-Z]{2,5}$")
_NUMBER_RE = re.compile(r"^\d{3}[A-Z]?$")
_NUM_RE = re.compile(r"^\d+(\.\d+)?$")
_CAT_RE = re.compile(r"^([A-Z]{1,4})\s*-\s*(.+)$")
_TERM_RE = re.compile(r"^(Spring|Summer|Fall|Winter) \d{4}$")
_TOL = 8.0

DEFAULT_COLS = {"category": 35, "code": 166, "name": 216, "credits": 372, "semester": 411, "grade": 471, "earned": 505}
NOT_COUNTED_GROUP = "Not counted by the SIS audit"
_VALUE_X = 405          # header values ("Fall 2024", the degree name) start right of the colon


# ---------------------------------------------------------------------------
# PDF -> words
# ---------------------------------------------------------------------------

def read_pdf(fileobj):
    """Words of every page: [{"width", "height", "words": [{x0, top, text}]}]."""
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
        raise ValueError("That file couldn't be read as a PDF. Download the degree audit again from SIS and try once more.")
    return pages


# ---------------------------------------------------------------------------
# words -> audit
# ---------------------------------------------------------------------------

def _after_colon(line):
    """Words right of the ':' that follows a header label (e.g. "Degree : Bachelor ...")."""
    for i, w in enumerate(line):
        if w["text"] == ":" and w["x0"] >= _VALUE_X - 20:
            return line[i + 1:]
    return []


def _float(s):
    return float(s) if _NUM_RE.match(s or "") else None


def _in(words, lo, hi):
    return [w for w in words if lo <= w["x0"] < hi]


def _near(words, x):
    for w in words:
        if abs(w["x0"] - x) <= _TOL:
            return w["text"]
    return ""


def _strip_required(name):
    return re.sub(r"\s*\(required\)\s*$", "", name or "", flags=re.I).strip()


def parse_pages(pages):
    """Pages of words -> {"program", "catalog_term", "courses", "summary", "warnings"}.

    courses: [{"code", "name", "credits", "category_code", "category" ("" = shaded),
               "term", "grade", "earned", "status"}] in audit order.
    summary: {"total_required", "total_completed", "categories": [{"label", "required", "completed"}]}.
    """
    cols = dict(DEFAULT_COLS)
    program = catalog_term = None
    rows, warnings = [], []
    summary = {"total_required": None, "total_completed": None, "categories": []}
    in_table = in_summary = False
    cur = None

    for page in pages:
        lines = grade_report._lines(page["words"])
        for li, line in enumerate(lines):
            texts = [w["text"] for w in line]

            # Header: only these two labelled values are read.
            if "Catalog" in texts and "Term" in texts:
                catalog_term = " ".join(w["text"] for w in _after_colon(line)) or catalog_term
            if "Degree" in texts and any(w["x0"] > 300 for w in line if w["text"] == "Degree"):
                val = _after_colon(line)
                if li + 1 < len(lines):
                    nxt = lines[li + 1]
                    more = [w for w in nxt if w["x0"] >= _VALUE_X - 5]       # the address column sits left of this
                    if more and nxt[0]["top"] - line[0]["top"] < 20 and "Category" not in [w["text"] for w in nxt]:
                        val += more
                program = re.sub(r"\s*\(AUPP\)\s*$", "", " ".join(w["text"] for w in val)).strip() or program

            # Table header: take the column positions from it.
            if "Category" in texts and "Semester" in texts and "Grade" in texts:
                pos = {w["text"]: w["x0"] for w in line}
                credit_xs = sorted(w["x0"] for w in line if w["text"] == "Credits")
                cols.update(category=pos["Category"], semester=pos["Semester"], grade=pos["Grade"])
                if "AUPP" in pos:
                    cols["code"] = pos["AUPP"]
                if "Course" in pos:
                    cols["name"] = pos["Course"]
                if credit_xs:
                    cols["credits"] = credit_xs[0]
                if len(credit_xs) > 1:
                    cols["earned"] = credit_xs[-1]
                in_table, in_summary, cur = True, False, None
                continue

            if "Required:" in texts and "Completed:" in texts:
                in_table, in_summary, cur = False, True, None
                continue
            if "Notes!" in texts or texts[0] == "Recommended":
                in_table, cur = False, None
                continue

            if in_summary:
                _read_summary_line(line, summary)
                continue
            if not in_table:
                continue

            subject = next((w for w in line if abs(w["x0"] - cols["code"]) <= _TOL and _SUBJECT_RE.match(w["text"])), None)
            number = next((w for w in line if cols["code"] - _TOL <= w["x0"] < cols["name"] - _TOL
                           and w is not subject and _NUMBER_RE.match(w["text"])), None)
            cat = _in(line, 0, cols["code"] - _TOL)
            name = _in(line, cols["name"] - _TOL, cols["credits"] - _TOL)
            sem = _in(line, cols["semester"] - _TOL, cols["grade"] - _TOL)
            credits = _float(_near(line, cols["credits"]))
            grade = _near(line, cols["grade"])
            earned = _float(_near(line, cols["earned"]))

            if subject is not None:
                cur = {"subject": subject["text"], "number": number["text"] if number else "",
                       "category": " ".join(w["text"] for w in cat), "name": " ".join(w["text"] for w in name),
                       "credits": credits, "term": " ".join(w["text"] for w in sem),
                       "grade": grade, "earned": earned}
                rows.append(cur)
            elif cur is not None:
                if not cur["number"] and number is not None:
                    cur["number"] = number["text"]
                if cat:
                    cur["category"] = (cur["category"] + " " + " ".join(w["text"] for w in cat)).strip()
                if name:
                    cur["name"] = (cur["name"] + " " + " ".join(w["text"] for w in name)).strip()
                if sem:
                    cur["term"] = (cur["term"] + " " + " ".join(w["text"] for w in sem)).strip()
                if grade and not cur["grade"]:
                    cur["grade"] = grade
                if earned is not None and cur["earned"] is None:
                    cur["earned"] = earned
                if credits is not None and cur["credits"] is None:
                    cur["credits"] = credits

    courses, seen = [], set()
    for r in rows:
        if not r["number"]:
            warnings.append(f"A row for {r['subject']} had no course number; skipped it.")
            continue
        code = f"{r['subject']} {r['number']}"
        if code in seen:
            warnings.append(f"{code} appears twice in the audit; kept the first one.")
            continue
        seen.add(code)
        m = _CAT_RE.match(r["category"]) if r["category"] else None
        grade = (r["grade"] or "").upper()
        term = r["term"]
        if term and not _TERM_RE.match(term):
            warnings.append(f"{code}: couldn't read the semester '{term}'.")
        courses.append({
            "code": code, "name": r["name"], "credits": r["credits"] or 0,
            "category_code": m.group(1) if m else "", "category": m.group(2).strip() if m else "",
            "term": term, "grade": grade, "earned": r["earned"] or 0,
            "status": _status(grade, term),
        })
    return {"program": program, "catalog_term": catalog_term, "courses": courses,
            "summary": summary, "warnings": warnings}


def _status(grade, term):
    if not grade and not term:
        return "not_taken"
    if grade == "RG":
        return "in_progress"
    return grade_report.status_of(grade)


def _read_summary_line(line, summary):
    left = [w for w in line if w["x0"] < 300]
    right = [w for w in line if w["x0"] >= 300]
    lnums = [_float(w["text"]) for w in left if _float(w["text"]) is not None]
    rnums = [_float(w["text"]) for w in right if _float(w["text"]) is not None]
    label = " ".join(w["text"] for w in left if _float(w["text"]) is None).strip().rstrip(":").strip()
    if not lnums or not rnums:
        return
    if not label:
        if summary["total_required"] is None:
            summary["total_required"], summary["total_completed"] = lnums[-1], rnums[-1]
        return
    summary["categories"].append({"label": label, "required": lnums[-1], "completed": rnums[-1]})


# ---------------------------------------------------------------------------
# audit -> structure / curriculum
# ---------------------------------------------------------------------------

def _num(x):
    return int(x) if float(x).is_integer() else x


def _summary_for(name, summary):
    """The summary line for a category: its label ends with the category name
    ("in Artificial Intelligence Major" -> Major). The longest match wins so
    "Core/Major" is not mistaken for "Major"."""
    best = None
    for s in summary["categories"]:
        label = _strip_required(s["label"]).lower()
        if label.endswith(name.lower()) and (best is None or len(name) > best[0]):
            best = (len(name), s)
    return best[1] if best else None


def category_names(parsed):
    out = []
    for c in parsed["courses"]:
        name = _strip_required(c["category"])
        if name and name not in out:
            out.append(name)
    return out


def summarize(parsed):
    """Per-category numbers for the preview, plus counts and warnings."""
    warnings = list(parsed["warnings"])
    summary = parsed["summary"]
    cats = []
    for name in category_names(parsed):
        mine = [c for c in parsed["courses"] if _strip_required(c["category"]) == name]
        listed = sum(c["credits"] for c in mine)
        passed = sum(c["earned"] or c["credits"] for c in mine if c["status"] == "completed")
        rep = _summary_for(name, summary)
        target = rep["required"] if rep else listed
        row = {"name": name, "target": _num(target), "listed": _num(listed), "courses": len(mine),
               "passed_credits": _num(passed), "reported_completed": _num(rep["completed"]) if rep else None}
        cats.append(row)
        if listed < target:
            warnings.append(f"{name} needs {_num(target)} credits, but the audit lists courses worth only {_num(listed)}. "
                            "Courses in the shaded '-' group may fill the rest; ask your advisor.")
        if rep and abs(passed - rep["completed"]) > 0.01:
            warnings.append(f"{name}: the audit says {_num(rep['completed'])} credits completed, but I counted {_num(passed)}. "
                            "Check the courses below.")
    shaded = [c for c in parsed["courses"] if not c["category"]]
    counts = {
        "courses": len(parsed["courses"]),
        "passed": sum(1 for c in parsed["courses"] if c["status"] == "completed"),
        "in_progress": sum(1 for c in parsed["courses"] if c["status"] == "in_progress"),
        "not_taken": sum(1 for c in parsed["courses"] if c["status"] == "not_taken"),
        "not_counted": len(shaded),
    }
    total = summary["total_required"]
    return {"program": parsed["program"], "catalog_term": parsed["catalog_term"],
            "total_required": _num(total) if total is not None else None,
            "total_completed": _num(summary["total_completed"]) if summary["total_completed"] is not None else None,
            "categories": cats, "counts": counts, "warnings": warnings,
            "courses": [{k: c[k] for k in ("code", "name", "credits", "category", "term", "grade", "status")}
                        for c in parsed["courses"]]}


def to_structure(parsed):
    """The student's own program structure, in the same shape as
    data/program_structures.json (see structure.py)."""
    summ = summarize(parsed)
    cats = []
    for row in summ["categories"]:
        mine = [c for c in parsed["courses"] if _strip_required(c["category"]) == row["name"]]
        cats.append({"name": row["name"], "credits": row["target"],
                     "courses": [{"code": c["code"], "name": c["name"], "credits": _num(c["credits"])} for c in mine]})
    shaded = [c for c in parsed["courses"] if not c["category"]]
    total = summ["total_required"] if summ["total_required"] is not None else sum(c["credits"] for c in cats)
    st = {"name": parsed["program"] or "My degree audit", "total_credits": total,
          "categories": cats,
          "source": "Your SIS degree audit" + (f" (catalog {parsed['catalog_term']})" if parsed["catalog_term"] else "")}
    if shaded:
        st["not_counted"] = [{"name": NOT_COUNTED_GROUP,
                              "courses": [{"code": c["code"], "name": c["name"], "credits": _num(c["credits"])} for c in shaded]}]
    return st


def move_course(st, code, category):
    """A copy of the student's structure with one course moved to `category`
    (a category name) or to the not-counted group (category empty/None).

    SIS sometimes leaves a course out of a category that the school does count
    (a shaded row on the audit); this lets the student correct that."""
    st = copy.deepcopy(st)
    key = grade_report._norm(code)
    found = None
    holders = [c["courses"] for c in st.get("categories", [])] + [g["courses"] for g in st.get("not_counted", [])]
    for lst in holders:
        for c in lst:
            if grade_report._norm(c["code"]) == key:
                found = dict(c)
                lst.remove(c)
                break
        if found:
            break
    if not found:
        raise ValueError(f"{code} isn't on your degree audit.")
    name = (category or "").strip()
    if name and name.lower() not in ("not counted", NOT_COUNTED_GROUP.lower()):
        target = next((c for c in st.get("categories", []) if c["name"].lower() == name.lower()), None)
        if target is None:
            raise ValueError(f"'{category}' isn't a category on your audit.")
        target["courses"].append(found)
    else:
        group = next((g for g in st.get("not_counted", []) if g["name"] == NOT_COUNTED_GROUP), None)
        if group is None:
            group = {"name": NOT_COUNTED_GROUP, "courses": []}
            st.setdefault("not_counted", []).append(group)
        group["courses"].append(found)
    st["not_counted"] = [g for g in st.get("not_counted", []) if g["courses"]]
    if not st["not_counted"]:
        st.pop("not_counted")
    return st


def apply_moves(st, moves):
    """Re-apply the student's earlier corrections ({code: category}) to a fresh structure."""
    for code, category in (moves or {}).items():
        try:
            st = move_course(st, code, category)
        except ValueError:
            pass            # the course or category is no longer on the audit
    return st


def apply(req, parsed):
    """The student's requirements dict rebuilt from the audit (a copy is returned).

    Catalog = every course on the audit, keeping prerequisites / plan order from
    the existing catalog when the course was already there. Completed = passed
    courses on the audit (with semester and grade); passed courses the audit
    doesn't list are kept. The student's own structure is stored as
    `audit_structure` so progress uses their real categories.
    Returns (new_req, counts).
    """
    old = {grade_report._norm(c["code"]): c for c in req.get("catalog", [])}
    audit_codes = {grade_report._norm(c["code"]) for c in parsed["courses"]}

    catalog = []
    for c in parsed["courses"]:
        base = dict(old.get(grade_report._norm(c["code"])) or {})
        base.update(code=c["code"], name=c["name"] or base.get("name") or c["code"], credits=_num(c["credits"]),
                    category=_strip_required(c["category"]) or "", sub_category="")
        base.setdefault("required", bool(c["category"]) and "elective" not in c["category"].lower())
        base.setdefault("hard_prereqs", [])
        base.setdefault("soft_prereqs", [])
        catalog.append(base)

    passed = [c for c in parsed["courses"] if c["status"] == "completed"]
    completed = [c for c in req.get("completed", []) if grade_report._norm(c) not in audit_codes]
    sems = {k: v for k, v in (req.get("completed_semesters") or {}).items() if grade_report._norm(k) not in audit_codes}
    grades = {k: v for k, v in (req.get("grades") or {}).items() if grade_report._norm(k) not in audit_codes}
    for c in passed:
        completed.append(c["code"])
        if gpa.term_key(c["term"]):
            sems[c["code"]] = c["term"]
        grades[c["code"]] = gpa.normalize_grade(c["grade"]) or c["grade"]

    out = dict(req)
    moves = dict(req.get("audit_moves") or {})
    out.update(catalog=catalog, completed=completed, completed_semesters=sems, grades=grades,
               audit_structure=apply_moves(to_structure(parsed), moves))
    if moves:
        out["audit_moves"] = moves
    if parsed["program"]:
        out["program"] = parsed["program"]
    out["required_remaining"] = [c["code"] for c in catalog if c.get("required") and c["code"] not in set(completed)]
    return out, {"courses": len(catalog), "completed": len(passed),
                 "in_progress": sum(1 for c in parsed["courses"] if c["status"] == "in_progress"),
                 "not_counted": sum(1 for c in parsed["courses"] if not c["category"])}
