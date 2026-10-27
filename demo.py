"""
demo.py
-------
Builds a realistic demo student (for showing the app to a lecturer without any
set-up): two years of completed courses with grades, a wishlist for the coming
term and two pinned schedules. Pure logic: the route in app.py does the file
writing. Everything here is deterministic, so a demo looks the same every time.
"""

import copy
import hashlib

import compare
import gpa
import programs
import progress
from scheduler import DEFAULT_REQUIREMENTS, enumerate_plans, prereqs_met

# Grades are picked from this list by hashing the course code: mostly A-/B+/B,
# a few A and C+, so the GPA lands around 3.3 and looks like a real student.
_GRADE_MIX = ["A", "A", "A-", "A-", "A-", "B+", "B+", "B+", "B+", "B", "B", "B", "B-", "B-", "C+", "A", "A-", "B+", "B", "C"]


def demo_grade(code):
    h = int(hashlib.sha1(code.encode("utf-8")).hexdigest()[:8], 16)
    return _GRADE_MIX[h % len(_GRADE_MIX)]


def demo_semester(year, term, admitted_year=2024):
    """Sample-plan semester -> calendar label, for a student admitted in Fall <admitted_year>:
    Year 1 Fall = Fall 2024, Year 1 Spring = Spring 2025, Year 2 Fall = Fall 2025 ..."""
    y = admitted_year + int(year) - 1
    return f"Fall {y}" if term == "Fall" else f"{term} {y + 1}"


def build_requirements(program, last_year=2, last_term="Spring", current_term="Fall 2026"):
    """A student's degree_requirements dict with everything through (last_year, last_term) completed."""
    req = programs.apply_program(copy.deepcopy(DEFAULT_REQUIREMENTS), program)
    catalog = req["catalog"]
    codes = progress.courses_through(catalog, last_year, last_term)
    by_code = {c["code"]: c for c in catalog}
    req["completed"] = codes
    req["completed_semesters"] = {c: demo_semester(by_code[c]["plan_year"], by_code[c]["plan_term"]) for c in codes}
    req["grades"] = {c: demo_grade(c) for c in codes}
    req["required_remaining"] = [c["code"] for c in catalog if c.get("required") and c["code"] not in set(codes)]
    req["semester"] = current_term
    req["year"] = f"Year {last_year + 1}"
    req["not_in_plan"] = []
    return req


def choose_wishlist_and_plans(req, offerings, want=5):
    """Wishlist = the next required courses the student can actually take this
    term (prerequisites done, sections offered). Returns (wishlist, [two best
    plans as lists of {code, section}]); plans may be fewer than two."""
    offered = {s["code"] for s in offerings}
    completed = set(req["completed"])
    cands = [c for c in progress.available_now(req["catalog"], completed, req.get("prereqs", {}), offered)
             if c["offered"] and prereqs_met(c["code"], req)]
    codes = [c["code"] for c in cands]
    for n in range(min(want, len(codes)), 0, -1):          # shrink the wishlist until 2+ valid schedules exist
        wishlist = codes[:n]
        plans, *_ = enumerate_plans(req, offerings, wishlist, limit=50)
        if len(plans) >= 2 or n == 1:
            # Second plan = the first one that differs from the best in some compared row, so the
            # Compare page has something to highlight (falls back to the 2nd plan if none does).
            chosen = plans[:1]
            if len(plans) > 1:
                m0 = compare.plan_metrics(plans[0]["sections"], wishlist)
                pick = next((p for p in plans[1:] if compare.compare_plans([m0, compare.plan_metrics(p["sections"], wishlist)])), plans[1])
                chosen.append(pick)
            keys = [[{"code": s["code"], "section": s["section"]} for s in p["sections"]] for p in chosen]
            return wishlist, keys
    return [], []


def summary(req, wishlist, pins):
    entries = [{"credits": c["credits"], "grade": req["grades"].get(c["code"], "")} for c in req["catalog"] if c["code"] in set(req["completed"])]
    t = gpa.totals(entries)
    return {"completed": len(req["completed"]), "credits": t["attempted"], "gpa": t["gpa"], "wishlist": wishlist, "pins": len(pins)}
