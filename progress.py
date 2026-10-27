"""
progress.py
-----------
Degree-progress maths for the dashboard (pure: no Flask, no files).

Vocabulary:
  required course  = catalog entry with required=True
  elective slot    = an open place in the sample plan with no course code yet
  A completed course that is NOT required is an elective; each one uses up one
  open elective slot (first slot first). Extra electives beyond the slots are
  reported but don't count toward the plan's total.
"""

from collections import defaultdict


def open_slots(catalog, completed, slots):
    """Split the sample plan's elective slots into (filled, still_open) using
    the student's completed non-required courses."""
    electives = sum(1 for c in catalog if not c.get("required") and c["code"] in set(completed))
    slots = list(slots or [])
    return slots[:electives], slots[electives:]


def _cr(c):
    try:
        return float(c.get("credits") or 0)
    except (TypeError, ValueError):
        return 0.0


def category_progress(catalog, completed, slots):
    """Rows of {category, done, total} plus the overall numbers."""
    completed = set(completed)
    cats = defaultdict(lambda: {"done": 0.0, "total": 0.0, "courses_done": 0, "courses": 0})
    for c in catalog:
        if not c.get("required"):
            continue
        label = (c.get("category") or "").strip() or "Uncategorized"
        row = cats[label]
        row["total"] += _cr(c)
        row["courses"] += 1
        if c["code"] in completed:
            row["done"] += _cr(c)
            row["courses_done"] += 1
    rows = [dict(category=k, **v) for k, v in cats.items()]

    filled, still_open = open_slots(catalog, completed, slots)
    slot_total = sum(float(s.get("credits") or 0) for s in (slots or []))
    if slot_total:
        rows.append({"category": "Open electives", "done": sum(float(s.get("credits") or 0) for s in filled),
                     "total": slot_total, "courses_done": len(filled), "courses": len(slots)})
    extra = max(0, sum(1 for c in catalog if not c.get("required") and c["code"] in completed) - len(slots or []))
    total = sum(r["total"] for r in rows)
    done = sum(r["done"] for r in rows)
    return {
        "rows": rows, "done": done, "total": total, "remaining": max(0.0, total - done),
        "percent": round(100 * done / total, 1) if total else 0.0,
        "extra_electives": extra,
    }


def remaining_required(catalog, completed):
    completed = set(completed)
    return [c for c in catalog if c.get("required") and c["code"] not in completed]


def _prereqs(c, prereqs):
    return list(prereqs.get(c["code"]) or c.get("hard_prereqs") or [])


def available_now(catalog, completed, prereqs, offered=None):
    """Remaining required courses whose prerequisites are all completed,
    in sample-plan order. `offered` (set of codes) marks whether each has
    sections this term; None means unknown."""
    completed = set(completed)
    out = []
    for c in remaining_required(catalog, completed):
        if all(p in completed for p in _prereqs(c, prereqs)):
            out.append({
                "code": c["code"], "name": c.get("name") or "", "credits": _cr(c),
                "plan": f"Year {c['plan_year']} · {c['plan_term']}" if c.get("plan_year") and c.get("plan_term") else None,
                "offered": None if offered is None else c["code"] in offered,
                "_rank": (int(c["plan_year"]) * 10 if c.get("plan_year") else 999),
            })
    out.sort(key=lambda x: (x["_rank"], x["code"]))
    for x in out:
        x.pop("_rank")
    return out


def bottlenecks(catalog, completed, prereqs, top=8):
    """Remaining required courses ranked by how many other remaining required
    courses (directly or through a chain) are waiting on them."""
    completed = set(completed)
    rem = {c["code"]: c for c in remaining_required(catalog, completed)}
    children = defaultdict(set)
    for code, c in rem.items():
        for p in _prereqs(c, prereqs):
            if p in rem:
                children[p].add(code)

    def descendants(code):
        seen, stack = set(), list(children[code])
        while stack:
            d = stack.pop()
            if d not in seen and d != code:
                seen.add(d)
                stack.extend(children[d])
        return seen

    rows = []
    for code, c in rem.items():
        d = descendants(code)
        if d:
            ready = all(p in completed or p not in rem for p in _prereqs(c, prereqs))
            rows.append({"code": code, "name": c.get("name") or "", "unlocks": len(d),
                         "direct": len(children[code]), "available_now": ready,
                         "examples": sorted(d)[:4]})
    rows.sort(key=lambda r: (-r["unlocks"], not r["available_now"], r["code"]))
    return rows[:top]


# ---------------------------------------------------------------------------
# "Mark everything up to here as completed"
# ---------------------------------------------------------------------------

PLAN_TERM_RANK = {"Fall": 0, "Spring": 1, "Summer": 2}   # order inside a sample-plan year


def plan_position(year, term):
    """Sortable position of a sample-plan semester; None if it isn't one."""
    try:
        year = int(year)
    except (TypeError, ValueError):
        return None
    term = str(term or "").strip().capitalize()
    if year < 1 or term not in PLAN_TERM_RANK:
        return None
    return year * 10 + PLAN_TERM_RANK[term]


def plan_semesters(catalog):
    """Distinct sample-plan semesters in the catalog, in order: [(year, term), ...]."""
    seen = {(int(c["plan_year"]), c["plan_term"]) for c in catalog if plan_position(c.get("plan_year"), c.get("plan_term")) is not None}
    return sorted(seen, key=lambda yt: plan_position(*yt))


def courses_through(catalog, year, term):
    """Codes of every catalog course whose sample-plan semester is at or before
    (year, term). Courses with no sample-plan position are never included."""
    limit = plan_position(year, term)
    if limit is None:
        raise ValueError("Pick a sample-plan semester like Year 2 · Fall.")
    return [c["code"] for c in catalog
            if (plan_position(c.get("plan_year"), c.get("plan_term")) or 10**9) <= limit]
