"""
scheduler.py
------------
Core planning engine for the Registration Planner.

This treats "build me a registration plan" as a constraint-satisfaction
problem: every course you still need is a *slot* that must be filled by
exactly one non-conflicting section, subject to prerequisites and a
credit limit. There are two kinds of slots:

  - REQUIRED: courses your curriculum says you still need. The planner
    always tries to fit every one of these.
  - WISHLIST: courses YOU chose while browsing the catalog (electives,
    "nice to have" courses, whatever you're curious about). The planner
    fits in as many of these as it can without breaking the schedule.

We search for several DIFFERENT valid solutions (Plan A / B / C / ...)
instead of just one, so if a section fills up on the real registration
system, you already have a fallback. For each course we also flag a
backup section/plan in case the one you wanted fills up.

Nothing here talks to any registration system directly -- it works off
JSON files in data/, which you fill in via the app's Curriculum and
Import pages (or by editing them directly if you prefer).
"""

import bisect
import json


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

DEFAULT_REQUIREMENTS = {
    "program": "",
    "year": "",
    "semester": "",
    "completed": [],
    "completed_semesters": {},
    "required_remaining": [],
    "catalog": [],
    "prereqs": {},
    "target_credits": {"min": 12, "max": 17},
    "preferences": {"avoid_before": "", "avoid_days": [], "priority_courses": [], "ignore_prereqs": False},
}


def load_data(requirements_path="data/degree_requirements.json",
              offerings_path="data/course_offerings.json"):
    """Tolerant of either file not existing yet -- a brand-new setup (new
    university, or before the first Excel import / curriculum entry)
    should show an empty state, not crash."""
    try:
        with open(requirements_path) as f:
            requirements = json.load(f)
    except FileNotFoundError:
        requirements = dict(DEFAULT_REQUIREMENTS)

    try:
        with open(offerings_path) as f:
            offerings = json.load(f)
    except FileNotFoundError:
        offerings = []

    return requirements, offerings


def load_wishlist(path="data/wishlist.json"):
    try:
        with open(path) as f:
            return json.load(f).get("courses", [])
    except FileNotFoundError:
        return []


def save_wishlist(courses, path="data/wishlist.json"):
    with open(path, "w") as f:
        json.dump({"courses": courses}, f, indent=2)


# ---------------------------------------------------------------------------
# Prereqs + slot construction
# ---------------------------------------------------------------------------

def prereqs_met(code, requirements):
    """A course is registerable this term if every prereq is already completed.
    Bypassed entirely when the "ignore prerequisites" planning preference is
    on -- useful for sketching out a future term ahead of actually taking
    the prereq courses."""
    if requirements.get("preferences", {}).get("ignore_prereqs"):
        return True
    completed = set(requirements.get("completed", []))
    needed = requirements.get("prereqs", {}).get(code, [])
    return all(p in completed for p in needed)


def missing_prereqs(code, requirements):
    completed = set(requirements.get("completed", []))
    return [p for p in requirements.get("prereqs", {}).get(code, []) if p not in completed]


def build_slots(requirements, wishlist, offerings):
    """
    Turns the student's wishlist into solver 'slots' -- the plan is built
    from the wishlist and nothing else (required courses are NOT added
    automatically; if you want one in your plan, wishlist it). Each slot
    needs exactly one course; a slot is skipped if it can't be scheduled.

    Returns (slots, blocked_required, blocked_wishlist, no_sections):
      - blocked_required: always [] now (kept so callers needn't change)
      - blocked_wishlist: wishlist courses missing a prereq
      - no_sections: wishlist courses with met prereqs but zero sections
        offered this term (nothing in course_offerings.json for that code)
    """
    offered_codes = {s["code"] for s in offerings}
    slots = []
    blocked_wishlist = []
    no_sections = []

    for code in wishlist:
        if not prereqs_met(code, requirements):
            blocked_wishlist.append({"code": code, "missing_prereqs": missing_prereqs(code, requirements)})
        elif code not in offered_codes:
            no_sections.append(code)
        else:
            slots.append({"type": "wishlist", "label": code, "options": [code]})

    return slots, [], blocked_wishlist, no_sections


# ---------------------------------------------------------------------------
# Time conflict checking
# ---------------------------------------------------------------------------

def _to_minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def sections_conflict(a, b):
    shared_days = set(a["days"]) & set(b["days"])
    if not shared_days:
        return False
    a_start, a_end = _to_minutes(a["start"]), _to_minutes(a["end"])
    b_start, b_end = _to_minutes(b["start"]), _to_minutes(b["end"])
    return a_start < b_end and b_start < a_end


def violates_preferences(section, requirements):
    if not section.get("start") or not section.get("days"):
        return False  # online/async section -- no fixed time to prefer around
    prefs = requirements.get("preferences", {})
    avoid_before = prefs.get("avoid_before")
    if avoid_before and _to_minutes(section["start"]) < _to_minutes(avoid_before):
        return True
    avoid_days = set(prefs.get("avoid_days", []))
    if avoid_days & set(section["days"]):
        return True
    return False


def sections_for(code, offerings):
    return [s for s in offerings if s["code"] == code]


# ---------------------------------------------------------------------------
# Exhaustive plan enumeration
# ---------------------------------------------------------------------------

class _Stop(Exception):
    pass


def _day_metrics(sections):
    """Days on campus, earliest start, and total idle gap between classes --
    what students actually compare when picking between valid schedules."""
    by_day = {}
    for sec in sections:
        if not sec.get("start") or not sec.get("days"):
            continue
        for d in sec["days"]:
            by_day.setdefault(d, []).append((_to_minutes(sec["start"]), _to_minutes(sec["end"])))
    gap = 0
    for meetings in by_day.values():
        meetings.sort()
        for (_, prev_end), (next_start, _) in zip(meetings, meetings[1:]):
            gap += max(0, next_start - prev_end)
    starts = [m[0] for ms in by_day.values() for m in ms]
    return {
        "days_on_campus": len(by_day),
        "earliest_start": min(starts) if starts else None,
        "gap_minutes": gap,
    }


def enumerate_plans(requirements, offerings, wishlist, limit=5000, node_budget=2_000_000):
    """
    Every valid plan for this wishlist, not a random sample.

    A plan is one section per scheduled course, with no time conflicts and
    total credits within the max. If the whole wishlist can't fit (time
    conflicts, or more credits than allowed), plans cover as many wishlist
    courses as possible -- every combination of WHICH courses to drop and
    which sections to take is listed, so you can see what each trade-off
    costs.

    Returns (plans, blocked_required, blocked_wishlist, no_sections, total_found,
    exhausted) where each plan has "sections" (dicts), "unmet_wishlist",
    "total_credits", "meets_min_credits" and the day metrics. Only the best
    `limit` plans are kept (ranked by fewest dropped courses, credit load,
    days on campus, then gaps); `total_found` is how many valid plans exist,
    and `exhausted` is False only if the `node_budget` safety valve stopped
    the search before every possibility was checked.
    """
    slots, blocked_required, blocked_wishlist, no_sections = build_slots(requirements, wishlist, offerings)
    max_credits = requirements.get("target_credits", {}).get("max", 17)
    min_credits = requirements.get("target_credits", {}).get("min", 12)

    # Candidate sections per slot, minus ones the student ruled out or that
    # are already full. A slot with none left simply can't be scheduled.
    cands = []
    for slot in slots:
        cands.append([
            sec for sec in sections_for(slot["options"][0], offerings)
            if not violates_preferences(sec, requirements) and sec.get("risk") != "full"
        ])
    n = len(slots)

    conflict_memo = {}

    def conflicts(a, b):
        key = (id(a), id(b))
        if key not in conflict_memo:
            conflict_memo[key] = conflict_memo[(id(b), id(a))] = sections_conflict(a, b)
        return conflict_memo[key]

    def fits(sec, chosen, credits):
        if credits + sec["credits"] > max_credits:
            return False
        return not any(conflicts(sec, c) for c in chosen)

    nodes = 0
    exhausted = True

    # Pass 1: the most wishlist courses any valid plan can include.
    best = 0

    def find(i, chosen, credits, count):
        nonlocal best, nodes
        nodes += 1
        if nodes > node_budget:
            raise _Stop
        if count + (n - i) <= best:
            return
        if i == n:
            best = count
            return
        for sec in cands[i]:
            if fits(sec, chosen, credits):
                chosen.append(sec)
                find(i + 1, chosen, credits + sec["credits"], count + 1)
                chosen.pop()
        find(i + 1, chosen, credits, count)

    try:
        find(0, [], 0, 0)
    except _Stop:
        exhausted = False

    if best == 0:
        return [], blocked_required, blocked_wishlist, no_sections, 0, exhausted

    # Pass 2: walk every plan that reaches that maximum, keeping only the
    # best `limit` of them (a sorted list, so the cap never favours whatever
    # the search happened to hit first).
    all_labels = {s["label"] for s in slots}
    kept_keys, kept = [], []
    total_found = 0
    nodes = 0

    def leaf(chosen, used):
        nonlocal total_found
        total_found += 1
        total = sum(sec["credits"] for sec in chosen)
        metrics = _day_metrics(chosen)
        key = (
            len(all_labels) - len(used),
            0 if total >= min_credits else 1,
            abs(max_credits - total),
            metrics["days_on_campus"],
            metrics["gap_minutes"],
            sorted((sec["code"], sec["section"]) for sec in chosen),
        )
        if len(kept_keys) >= limit and key >= kept_keys[-1]:
            return
        pos = bisect.bisect_left(kept_keys, key)
        kept_keys.insert(pos, key)
        kept.insert(pos, (list(chosen), set(used), total, metrics))
        if len(kept_keys) > limit:
            kept_keys.pop()
            kept.pop()

    def enum(i, chosen, credits, count, used):
        nonlocal nodes
        nodes += 1
        if nodes > node_budget:
            raise _Stop
        if count + (n - i) < best:
            return
        if i == n:
            leaf(chosen, used)
            return
        for sec in cands[i]:
            if fits(sec, chosen, credits):
                chosen.append(sec)
                used.append(slots[i]["label"])
                enum(i + 1, chosen, credits + sec["credits"], count + 1, used)
                used.pop()
                chosen.pop()
        if count + (n - i - 1) >= best:
            enum(i + 1, chosen, credits, count, used)

    try:
        enum(0, [], 0, 0, [])
    except _Stop:
        exhausted = False

    plans = []
    for sections, used, total, metrics in kept:
        plan = {
            "sections": sections,
            "unmet_required": [],
            "unmet_wishlist": sorted(all_labels - used),
            "total_credits": total,
            "meets_min_credits": total >= min_credits,
        }
        plan.update(metrics)
        plans.append(plan)
    return plans, blocked_required, blocked_wishlist, no_sections, total_found, exhausted


def find_alternates(sections, offerings, requirements):
    """
    For each scheduled course, suggest another SECTION of that same course
    (different time) that would still fit the rest of the plan -- the
    "if this fills up on registration day, try this instead" list.
    Only meaningful when a course has more than one section offered.
    """
    alternates = {}

    for chosen in sections:
        others = [s for s in sections if s is not chosen]
        backups = []
        for sec in sections_for(chosen["code"], offerings):
            if (sec["code"], sec["section"]) == (chosen["code"], chosen["section"]):
                continue
            if sec.get("risk") == "full":
                continue
            if any(sections_conflict(sec, o) for o in others):
                continue
            if violates_preferences(sec, requirements):
                continue
            backups.append(sec)

        if backups or chosen.get("risk") in ("medium", "fills fast"):
            alternates[f"{chosen['code']}-{chosen['section']}"] = backups[:2]

    return alternates


if __name__ == "__main__":
    reqs, offerings = load_data()
    wishlist = load_wishlist()
    plans, _, blocked_wishlist, no_sections, total, exhausted = enumerate_plans(reqs, offerings, wishlist)

    print(f"Program: {reqs['program']}")
    if blocked_wishlist:
        print("\nWishlist courses blocked by missing prereqs:")
        for b in blocked_wishlist:
            print(f"  - {b['code']}: needs {b['missing_prereqs']}")
    if no_sections:
        print(f"\nNot offered this term (no sections found): {no_sections}")

    print(f"\n{total}{'' if exhausted else '+'} possible plan(s); showing {len(plans)}")
    for i, plan in enumerate(plans[:5], 1):
        print(f"\n=== Plan {i} ({plan['total_credits']} credits, {plan['days_on_campus']} days) ===")
        for sec in plan["sections"]:
            days = "/".join(sec["days"])
            print(f"  {sec['code']}-{sec['section']}  {sec['title']:<28} {days:<7} {sec['start']}-{sec['end']}")
        if plan["unmet_wishlist"]:
            print(f"  (wishlist not scheduled: {plan['unmet_wishlist']})")
