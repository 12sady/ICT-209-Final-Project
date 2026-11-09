"""
gpa.py
------
Pure GPA maths (no Flask, no files) so it can be unit-tested.

Grade scale: AUPP's, read off a real AUPP grade report (its term GPAs only
come out right with A- = 3.67, B+ = 3.33, B- = 2.67). C+/C-/D+ follow the
same thirds pattern; confirm them with the registrar if they ever matter.

Rules used:
  - A letter grade in GRADE_SCALE counts toward GPA (quality points = points x credits).
  - NON_GPA_GRADES (pass/fail, withdrawn, incomplete, audit) never count toward GPA.
  - "Attempted" credits = credits of every course with a graded or pass/fail
    result (withdrawn, incomplete and audit are not attempted).
  - "Earned" credits = credits of passed courses (a D or better, or P).
  - Retakes are not handled: every completed course counts once.
"""

GRADE_SCALE = {
    "A": 4.0, "A-": 3.67,
    "B+": 3.33, "B": 3.0, "B-": 2.67,
    "C+": 2.33, "C": 2.0, "C-": 1.67,
    "D+": 1.33, "D": 1.0,
    "F": 0.0,
}

# Grades that are recorded but kept out of the GPA.
NON_GPA_GRADES = {
    "P": "Pass",
    "NP": "No pass",
    "W": "Withdrawn",
    "I": "Incomplete",
    "AU": "Audit",
}
_PASSING_NON_GPA = {"P"}
_NOT_ATTEMPTED = {"W", "I", "AU"}
_TERM_ORDER = {"spring": 1, "summer": 2, "fall": 3}


def article(letter):
    """'a' or 'an' for a grade letter, by how it is SAID: an A, an F, but a B, a C."""
    return "an" if str(letter or "")[:1].upper() in "AEFHILMNORSX" else "a"


def normalize_grade(raw):
    """'a-' -> 'A-'; '' / None -> ''. Returns '' for anything unrecognised."""
    g = str(raw or "").strip().upper().replace(" ", "")
    return g if g in GRADE_SCALE or g in NON_GPA_GRADES else ""


def grade_options():
    return list(GRADE_SCALE) + list(NON_GPA_GRADES)


def term_key(label):
    """'Fall 2026' -> sortable number (year*10 + term); None if not a term label."""
    parts = str(label or "").strip().split()
    if len(parts) == 2 and parts[0].lower() in _TERM_ORDER and parts[1].isdigit():
        return int(parts[1]) * 10 + _TERM_ORDER[parts[0].lower()]
    return None


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def totals(entries):
    """entries: [{"credits": n, "grade": "A-"}]. Ungraded entries are ignored.
    Returns quality_points, gpa_credits, gpa (None when nothing counts),
    attempted, earned."""
    qp = gpa_credits = attempted = earned = 0.0
    for e in entries:
        g = normalize_grade(e.get("grade"))
        cr = _num(e.get("credits"))
        if not g or cr <= 0:
            continue
        if g in GRADE_SCALE:
            qp += GRADE_SCALE[g] * cr
            gpa_credits += cr
            attempted += cr
            if GRADE_SCALE[g] > 0:
                earned += cr
        elif g not in _NOT_ATTEMPTED:
            attempted += cr
            if g in _PASSING_NON_GPA:
                earned += cr
    return {
        "quality_points": round(qp, 4),
        "gpa_credits": gpa_credits,
        "gpa": round(qp / gpa_credits, 4) if gpa_credits else None,
        "attempted": attempted,
        "earned": earned,
    }


def by_semester(entries):
    """Per-semester GPA plus the cumulative GPA after each semester, oldest first.
    Entries with no semester go in a trailing "No semester" group (kept out of
    the running cumulative so the order stays meaningful)."""
    groups = {}
    for e in entries:
        groups.setdefault(e.get("semester") or "", []).append(e)
    order = sorted(
        (s for s in groups if s),
        key=lambda s: (term_key(s) is None, term_key(s) or 0, s),
    )
    out, running = [], []
    for sem in order + ([""] if "" in groups else []):
        row = {"semester": sem or "No semester picked", **totals(groups[sem])}
        if sem:
            running += groups[sem]
            row["cumulative_gpa"] = totals(running)["gpa"]
        else:
            row["cumulative_gpa"] = None
        out.append(row)
    return out


def what_if(entries, planned):
    """GPA after adding a hypothetical term. planned: [{"credits", "grade"}].
    Returns current/new GPA and the arithmetic so the UI can show it."""
    cur = totals(entries)
    added = totals(planned)
    qp = cur["quality_points"] + added["quality_points"]
    cr = cur["gpa_credits"] + added["gpa_credits"]
    new = round(qp / cr, 4) if cr else None
    return {
        "current_gpa": cur["gpa"],
        "current_quality_points": cur["quality_points"],
        "current_credits": cur["gpa_credits"],
        "added_quality_points": added["quality_points"],
        "added_credits": added["gpa_credits"],
        "new_quality_points": round(qp, 4),
        "new_credits": cr,
        "new_gpa": new,
        "change": None if new is None or cur["gpa"] is None else round(new - cur["gpa"], 4),
    }


def required_average(entries, term_credits, target):
    """What average GPA over `term_credits` new credits reaches `target`
    cumulative? Returns dict with needed (float or None), feasible, message,
    and the closest letter grade that would do it."""
    cur = totals(entries)
    term_credits = _num(term_credits)
    target = _num(target)
    top = max(GRADE_SCALE.values())
    if term_credits <= 0:
        return {"needed": None, "feasible": False, "message": "Enter how many credits you plan to take (more than 0)."}
    if not 0 <= target <= top:
        return {"needed": None, "feasible": False, "message": f"A target GPA has to be between 0 and {top:g}."}
    total_cr = cur["gpa_credits"] + term_credits
    needed = (target * total_cr - cur["quality_points"]) / term_credits
    result = {
        "target": target, "term_credits": term_credits,
        "current_gpa": cur["gpa"], "current_quality_points": cur["quality_points"],
        "current_credits": cur["gpa_credits"], "total_credits": total_cr,
        "target_quality_points": round(target * total_cr, 4),
        "needed_quality_points": round(target * total_cr - cur["quality_points"], 4),
        "best_possible_gpa": round((cur["quality_points"] + top * term_credits) / total_cr, 4),
    }
    if needed > top + 1e-9:
        # Credits of straight top grades that would get there (target < top, else never).
        more = (target * cur["gpa_credits"] - cur["quality_points"]) / (top - target) if target < top else None
        result.update(
            needed=round(needed, 4), feasible=False, letter=None,
            credits_at_top=None if more is None else round(more, 1),
            message=(f"A {target:g} isn't reachable in one term of {term_credits:g} credits: even straight "
                     f"{top:g}s would only get you to {result['best_possible_gpa']:.2f}."
                     + (f" It would take about {more:.0f} more credits of straight {top:g}s to get there." if more is not None else "")))
    else:
        already = needed <= 0
        needed = max(needed, 0.0)
        letter = next((g for g, p in sorted(GRADE_SCALE.items(), key=lambda kv: kv[1]) if p + 1e-9 >= needed), None)
        result.update(
            needed=round(needed, 4), feasible=True, letter=letter,
            message=(f"You already stay at {target:g} or above whatever you score this term." if already
                     else f"Average {needed:.2f} (about {article(letter)} {letter}) across {term_credits:g} credits."))
    return result
