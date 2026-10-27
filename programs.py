"""
programs.py
-----------
Sample course plans ("program plans") for each major, published by the admin.

A program plan is a semester-by-semester roadmap: terms -> courses, plus a list
of approved electives. Every student can pick one to start their own
curriculum from, then edit their copy freely; only the admin edits the shared
plans themselves.
"""

import json
import os
import re

PROGRAMS_PATH = "data/program_plans.json"

TERM_NAMES = ("Fall", "Spring", "Summer")
CATEGORIES = ("General Education", "Major", "Elective", "Dual Degree")
_CODE_RE = re.compile(r"^([A-Za-z]{2,5})\s?(\d{3}[A-Za-z]?)$")


def load_programs():
    try:
        with open(PROGRAMS_PATH) as f:
            return json.load(f).get("programs", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_programs(programs):
    os.makedirs(os.path.dirname(PROGRAMS_PATH), exist_ok=True)
    with open(PROGRAMS_PATH, "w") as f:
        json.dump({"programs": programs}, f, indent=1, ensure_ascii=False)


def get_program(program_id):
    return next((p for p in load_programs() if p["id"] == program_id), None)


def summary(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "degree": p.get("degree", ""),
        "credit_total": p.get("credit_total"),
        "planned_credits": sum(c["credits"] for t in p["terms"] for c in t["courses"]),
        "terms": len(p["terms"]),
    }


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:50] or "program"


def _code(raw):
    raw = str(raw or "").strip()
    if not raw:
        return None
    m = _CODE_RE.match(raw)
    if not m:
        raise ValueError(f"'{raw}' isn't a course code like COSC 121 (leave the code empty for an elective slot).")
    return f"{m.group(1).upper()} {m.group(2).upper()}"


def _codes(raw):
    if isinstance(raw, str):
        raw = re.split(r"[,;/]|\band\b", raw)
    out = []
    for c in raw or []:
        c = str(c).strip()
        if c:
            out.append(_code(c))
    return out


def clean_program(raw, program_id=None):
    """Validate/normalise a program submitted by the admin editor.
    Raises ValueError with a message meant for the user."""
    name = str(raw.get("name") or "").strip()[:100]
    if not name:
        raise ValueError("The program needs a name.")
    degree = str(raw.get("degree") or "").strip().title()
    if degree not in ("Single", "Dual", ""):
        degree = ""
    try:
        total = int(raw.get("credit_total")) if raw.get("credit_total") not in (None, "") else None
    except (TypeError, ValueError):
        raise ValueError("Total credits must be a whole number.")

    terms = []
    for ti, t in enumerate(raw.get("terms") or []):
        term = str(t.get("term") or "").strip().title()
        if term not in TERM_NAMES:
            raise ValueError(f"Term {ti + 1} needs to be Fall, Spring or Summer.")
        try:
            year = int(t.get("year"))
        except (TypeError, ValueError):
            raise ValueError(f"Term {ti + 1} needs a year number (1-6).")
        if not 1 <= year <= 8:
            raise ValueError("Year must be between 1 and 8.")
        courses = []
        for c in t.get("courses") or []:
            code = _code(c.get("code"))
            title = re.sub(r"\s+", " ", str(c.get("title") or "")).strip()[:140]
            if not code and not title:
                continue  # a blank row
            if not title and code:
                title = ""
            try:
                credits = float(c.get("credits") if c.get("credits") not in (None, "") else 3)
            except (TypeError, ValueError):
                raise ValueError(f"Credits for {code or title} must be a number.")
            if not 0 <= credits <= 12:
                raise ValueError(f"Credits for {code or title} should be between 0 and 12.")
            credits = int(credits) if credits == int(credits) else credits
            cat = str(c.get("category") or "").strip()
            if cat not in CATEGORIES:
                cat = "Elective" if not code else "Major"
            entry = {
                "code": code, "title": title, "credits": credits,
                "prereqs": _codes(c.get("prereqs")), "category": cat,
            }
            if c.get("taught_by"):
                entry["taught_by"] = str(c["taught_by"]).strip()[:12]
            if not code:
                entry["slot"] = True
            courses.append(entry)
        terms.append({"year": year, "term": term, "label": f"Year {year} · {term}", "courses": courses})

    electives, seen = [], set()
    for e in raw.get("electives") or []:
        code = _code(e.get("code"))
        if not code or code in seen:
            continue
        seen.add(code)
        electives.append({
            "code": code,
            "title": re.sub(r"\s+", " ", str(e.get("title") or "")).strip()[:140],
            "prereqs": _codes(e.get("prereqs")),
        })

    out = {
        "id": program_id or slugify(raw.get("id") or name + " " + degree),
        "name": name, "degree": degree, "credit_total": total,
        "terms": terms, "electives": electives,
    }
    if raw.get("note"):
        out["note"] = str(raw["note"])[:300]
    return out


# ---------------------------------------------------------------------------
# Turning a program plan into a student's own curriculum
# ---------------------------------------------------------------------------

def _plan_category(course, compulsory):
    cat = course.get("category")
    if cat == "General Education":
        return "General Education (Required)", True
    if cat == "Elective":
        return "Electives", compulsory
    return "Major", True  # Major and Dual Degree courses


def build_catalog(program):
    """Catalog entries (the shape the Curriculum page already uses) for every
    coded course in the plan, plus the approved electives. Open elective slots
    (no course code) aren't catalog entries; they're counted separately."""
    catalog, seen, slots = [], set(), []
    for t in program["terms"]:
        for c in t["courses"]:
            if not c.get("code"):
                slots.append({"title": c.get("title") or "Elective", "credits": c["credits"],
                              "year": t["year"], "term": t["term"]})
                continue
            if c["code"] in seen:
                continue
            seen.add(c["code"])
            compulsory = "compulsory" in (c.get("title") or "").lower()
            category, required = _plan_category(c, compulsory)
            title = re.sub(r"\s*\(Compulsory\)\s*$", "", c.get("title") or "", flags=re.I).strip()
            catalog.append({
                "code": c["code"], "name": title or c["code"], "category": category,
                "sub_category": "", "credits": c["credits"], "required": required,
                "hard_prereqs": list(c.get("prereqs") or []), "soft_prereqs": [],
                "plan_year": t["year"], "plan_term": t["term"],
            })
    for e in program.get("electives", []):
        if e["code"] in seen:
            continue
        seen.add(e["code"])
        catalog.append({
            "code": e["code"], "name": e.get("title") or e["code"], "category": "Major Electives",
            "sub_category": "", "credits": 3, "required": False,
            "hard_prereqs": list(e.get("prereqs") or []), "soft_prereqs": [],
        })
    return catalog, slots


def apply_program(requirements, program):
    """Replace the catalog of a student's requirements with the program's,
    keeping everything personal (completed courses + their semesters,
    preferences, credit limits). Returns the new requirements dict."""
    catalog, slots = build_catalog(program)
    codes = {c["code"] for c in catalog}
    completed = list(requirements.get("completed", []))
    out = dict(requirements)
    out["program"] = f"{program['name']} ({program['degree']} Degree)" if program.get("degree") else program["name"]
    out["program_id"] = program["id"]
    out["catalog"] = catalog
    out["elective_slots"] = slots
    out["prereqs"] = {c["code"]: c["hard_prereqs"] for c in catalog if c["hard_prereqs"]}
    out["required_remaining"] = [c["code"] for c in catalog if c["required"] and c["code"] not in completed]
    out["completed"] = completed
    out["completed_semesters"] = dict(requirements.get("completed_semesters", {}))
    # Completed courses that aren't in the new plan stay in the list so nothing
    # a student already finished is lost; they just won't show a catalog row.
    out["not_in_plan"] = [c for c in completed if c not in codes]
    return out
