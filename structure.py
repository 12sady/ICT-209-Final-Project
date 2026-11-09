"""
structure.py
------------
Program structure = the rules to graduate: how many credits each category
needs, and which courses count toward it. Kept apart from the sample course
plan (programs.py / program_plans.json), which is only a suggested semester
order used by the Roadmap.

Data: data/program_structures.json, keyed by program_id. A program with no
entry there keeps the old behaviour (progress from the sample plan).

Pure logic except `load` (reads the JSON file).

Counting rules:
  - A completed course counts toward the category whose list it's in.
  - A category counts at most its required credits; anything above that is
    "extra" and doesn't count toward the 120 (or whatever the total is).
  - If a category's listed courses add up to its required credits or less
    (e.g. Major: 14 courses = 44 credits), every course in it is required.
    Otherwise the student chooses (e.g. Electives: 18 of 51 listed credits).
  - Courses in "not_counted" groups (Enrichment, uncategorised audit rows)
    and completed courses that aren't in the structure at all never count.
"""

import json
import os
import re

STRUCTURES_PATH = os.path.join("data", "program_structures.json")
NOT_IN_STRUCTURE = "Not in program structure"


def load(path=STRUCTURES_PATH):
    try:
        with open(path) as f:
            return (json.load(f) or {}).get("programs", {})
    except FileNotFoundError:
        return {}


def get(program_id, path=STRUCTURES_PATH):
    return load(path).get(program_id or "") if program_id else None


def _norm(code):
    return re.sub(r"\s+", "", str(code or "")).upper()


def _cr(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _num(x):
    return int(x) if float(x).is_integer() else x


def categories(st):
    """[{name, credits, all_required, courses:[{code, name, credits, group}]}]."""
    out = []
    for cat in st.get("categories", []):
        groups = cat.get("groups") or [{"name": "", "courses": cat.get("courses", [])}]
        courses = [dict(c, group=g.get("name") or "") for g in groups for c in g.get("courses", [])]
        listed = sum(_cr(c.get("credits")) for c in courses)
        out.append({"name": cat["name"], "credits": _cr(cat.get("credits")), "courses": courses,
                    "all_required": listed <= _cr(cat.get("credits")) + 1e-9})
    return out


def not_counted_label(name):
    return f"{name} (not counted)"


def course_index(st):
    """normalised code -> (category label, group, course dict, counts: bool)."""
    idx = {}
    for cat in categories(st):
        for c in cat["courses"]:
            idx.setdefault(_norm(c["code"]), (cat["name"], c["group"], c, True))
    for grp in st.get("not_counted", []):
        for c in grp.get("courses", []):
            idx.setdefault(_norm(c["code"]), (not_counted_label(grp["name"]), "", c, False))
    return idx


def evaluate(st, completed):
    """Progress against the structure.

    Returns the same overall shape as progress.category_progress (rows / done /
    total / remaining / percent / extra_electives) so the Dashboard can show
    either, plus: per-row `extra`, `all_required`, `left` (courses not done),
    `not_counted` groups and `remaining_required` codes.
    """
    done = {_norm(c) for c in completed}
    rows, remaining_required = [], []
    for cat in categories(st):
        got = [c for c in cat["courses"] if _norm(c["code"]) in done]
        earned = sum(_cr(c["credits"]) for c in got)
        left = [c for c in cat["courses"] if _norm(c["code"]) not in done]
        counted = min(earned, cat["credits"])
        if cat["all_required"]:
            remaining_required += [c["code"] for c in left]
        rows.append({
            "category": cat["name"], "done": counted, "total": cat["credits"],
            "earned": earned, "extra": max(0.0, earned - cat["credits"]),
            "courses_done": len(got), "courses": len(cat["courses"]),
            "all_required": cat["all_required"], "complete": counted >= cat["credits"],
            "left": [{"code": c["code"], "name": c.get("name") or "", "credits": c["credits"]} for c in left],
        })

    idx = course_index(st)
    not_counted = {}
    for code in completed:
        hit = idx.get(_norm(code))
        if hit and hit[3]:
            continue
        label = hit[0] if hit else NOT_IN_STRUCTURE
        not_counted.setdefault(label, []).append(code)

    total = _cr(st.get("total_credits")) or sum(r["total"] for r in rows)
    counted = sum(r["done"] for r in rows)
    return {
        "rows": rows, "done": counted, "total": total, "remaining": max(0.0, total - counted),
        "percent": round(100 * counted / total, 1) if total else 0.0,
        "extra_electives": 0,
        "extra_credits": sum(r["extra"] for r in rows),
        "not_counted": [{"group": k, "courses": v} for k, v in not_counted.items()],
        "remaining_required": remaining_required,
        "source": st.get("source", ""),
    }


def overlay(req, st):
    """The student's requirements with the catalog sorted into the structure:
    category (and GE sub-group) from the structure, structure courses missing
    from the catalog added, and `required` set by the structure's rules:

      - all-required category: required
      - choice category already complete: nothing left in it is required
      - choice category not complete yet: keep the sample plan's flag
      - not counted / not in the structure: not required

    A copy is returned; `req` is not changed. Sample-plan fields (plan_year,
    plan_term, prereqs) are kept so the Roadmap still uses the plan's order.
    """
    out = dict(req)
    completed = list(req.get("completed", []))
    progress = {r["category"]: r for r in evaluate(st, completed)["rows"]}
    allreq = {c["name"]: c["all_required"] for c in categories(st)}
    idx = course_index(st)

    catalog, seen = [], set()
    for c in req.get("catalog", []):
        c = dict(c)
        hit = idx.get(_norm(c["code"]))
        seen.add(_norm(c["code"]))
        if hit is None:
            c["category"], c["sub_category"], c["required"] = NOT_IN_STRUCTURE, "", False
        else:
            label, group, _course, counts = hit
            c["category"], c["sub_category"] = label, group
            if not counts:
                c["required"] = False
            elif allreq[label]:
                c["required"] = True
            elif progress[label]["complete"]:
                c["required"] = False
            else:
                c["required"] = bool(c.get("required"))
        catalog.append(c)

    for norm, (label, group, course, counts) in idx.items():
        if norm in seen:
            continue
        catalog.append({
            "code": course["code"], "name": course.get("name") or course["code"], "category": label,
            "sub_category": group, "credits": _num(_cr(course["credits"])),
            "required": bool(counts and allreq.get(label)),
            "hard_prereqs": [], "soft_prereqs": [],
        })

    done = set(completed)
    out["catalog"] = catalog
    out["required_remaining"] = [c["code"] for c in catalog if c.get("required") and c["code"] not in done]
    return out
