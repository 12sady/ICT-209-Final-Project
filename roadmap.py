"""
roadmap.py
----------
Graduation roadmap: lays out every remaining semester until the degree is
done. Pure logic (no Flask, no files) so it can be unit-tested.

What it knows and what it doesn't:
  - It knows the student's curriculum (required courses, open elective slots,
    prerequisites, the sample plan's order) and what they've completed.
  - It does NOT know which courses will be offered in future terms: the
    registrar's data covers one term. Only the first roadmap term can be checked
    against real offerings (when `offered_first` is given); every later term is
    a projection from the plan, and the UI says so.

Rules enforced when placing courses automatically:
  - a course goes in a term strictly AFTER all of its prerequisites;
  - no term goes over the credit limit (a single course bigger than the limit
    still gets a term of its own);
  - sample-plan order is preferred, then courses that unlock the longest chain.
Manual placements ("overrides") are never refused: they're kept and any
problem they cause is reported as a warning.
"""

from collections import defaultdict

# A term at or above this many credits is flagged as heavy even when the
# student's own limit is higher. One named number so it's easy to change.
HEAVY_TERM_CREDITS = 18
# A run of this many courses that each need the previous one is flagged.
LONG_CHAIN = 4
MAX_TERMS = 16  # safety stop: ~8 years of Fall + Spring terms

_SEASON_RANK = {"Spring": 1, "Summer": 2, "Fall": 3}
_PLAN_TERM_RANK = {"Fall": 0, "Spring": 1, "Summer": 2}


# ---------------------------------------------------------------------------
# Term labels ("Fall 2026")
# ---------------------------------------------------------------------------

def parse_term(label):
    """'Fall 2026' -> ('Fall', 2026); None if it isn't a term label."""
    parts = str(label or "").strip().split()
    if len(parts) == 2 and parts[0].capitalize() in _SEASON_RANK and parts[1].isdigit():
        return parts[0].capitalize(), int(parts[1])
    return None


def term_sort_key(label):
    p = parse_term(label)
    return None if p is None else p[1] * 10 + _SEASON_RANK[p[0]]


def next_term(label, include_summer=False):
    season, year = parse_term(label)
    order = ["Spring", "Summer", "Fall"] if include_summer else ["Spring", "Fall"]
    if season not in order:  # Summer while summers are off: jump to Fall
        return f"Fall {year}"
    i = order.index(season)
    return f"{order[i + 1]} {year}" if i + 1 < len(order) else f"{order[0]} {year + 1}"


def term_labels(start, count, include_summer=False):
    start = normalize_start(start, include_summer)
    labels = [start]
    while len(labels) < count:
        labels.append(next_term(labels[-1], include_summer))
    return labels


def normalize_start(label, include_summer=False):
    p = parse_term(label)
    if p is None:
        raise ValueError("Start term should look like 'Fall 2026'.")
    if p[0] == "Summer" and not include_summer:
        return f"Fall {p[1]}"
    return f"{p[0]} {p[1]}"


def guess_start_term(today):
    """The term a student is most likely registering for, from a date:
    Jan-May -> Spring, Jun-Jul -> Summer, Aug-Dec -> Fall of that year."""
    if today.month <= 5:
        return f"Spring {today.year}"
    if today.month <= 7:
        return f"Summer {today.year}"
    return f"Fall {today.year}"


# ---------------------------------------------------------------------------
# Building the roadmap
# ---------------------------------------------------------------------------

def _items(catalog, completed, prereqs, slots, slot_offset=0):
    items = {}
    for c in catalog:
        if not c.get("required") or c["code"] in completed:
            continue
        plan_rank = None
        if c.get("plan_year") and c.get("plan_term") in _PLAN_TERM_RANK:
            plan_rank = int(c["plan_year"]) * 10 + _PLAN_TERM_RANK[c["plan_term"]]
        items[c["code"]] = {
            "id": c["code"], "code": c["code"], "name": c.get("name") or "",
            "credits": float(c.get("credits") or 0), "slot": False,
            "prereqs": list(prereqs.get(c["code"]) or c.get("hard_prereqs") or []),
            "rank": plan_rank if plan_rank is not None else 99,
            "season": c.get("plan_term"),
            "plan": f"Year {c['plan_year']} · {c['plan_term']}" if plan_rank is not None else None,
        }
    for n, s in enumerate(slots or [], slot_offset + 1):  # numbering stays stable as slots get used up
        rank = int(s["year"]) * 10 + _PLAN_TERM_RANK.get(s.get("term"), 5) if s.get("year") else 99
        items[f"slot-{n}"] = {
            "id": f"slot-{n}", "code": "", "name": s.get("title") or "Elective", "credits": float(s.get("credits") or 3),
            "slot": True, "prereqs": [], "rank": rank, "season": None,
            "plan": f"Year {s['year']} · {s['term']}" if s.get("year") and s.get("term") else None,
        }
    return items


def _downstream(items):
    """Longest chain of remaining courses that starts at each course (itself
    counts as 1), plus the chain itself. Prerequisite loops are cut."""
    dependents = defaultdict(list)
    for it in items.values():
        for p in it["prereqs"]:
            if p in items:
                dependents[p].append(it["id"])
    memo, in_loop = {}, set()

    def walk(i, stack):
        if i in memo:
            return memo[i]
        if i in stack:
            in_loop.add(i)
            return (0, [])
        best = (0, [])
        for d in dependents[i]:
            cand = walk(d, stack | {i})
            if cand[0] > best[0]:
                best = cand
        memo[i] = (best[0] + 1, [i] + best[1])
        return memo[i]

    for i in items:
        walk(i, frozenset())
    return memo, in_loop


def build_roadmap(catalog, completed, prereqs, slots, start_term, max_credits=17, include_summer=False,
                  same_season=False, overrides=None, offered_first=None, max_terms=MAX_TERMS):
    """Returns a dict:
      terms: [{label, credits, courses: [{id, code, name, credits, slot, fixed, plan, prereqs, warnings}], warnings}]
      graduation_term, remaining_credits, unplaced, risks, real_offerings_term
    `overrides` maps item id -> term label for courses the student placed by hand.
    `offered_first`: set of course codes offered in the first term (None = unknown)."""
    completed = set(completed or [])
    start = normalize_start(start_term, include_summer)
    # A completed elective uses up one of the sample plan's open slots.
    electives_done = sum(1 for c in catalog if not c.get("required") and c["code"] in completed)
    items = _items(catalog, completed, prereqs or {}, list(slots or [])[electives_done:], electives_done)
    down, in_loop = _downstream(items)
    labels = term_labels(start, max_terms, include_summer)
    label_idx = {l: i for i, l in enumerate(labels)}

    placed, load, fixed = {}, defaultdict(float), set()
    for iid, lab in (overrides or {}).items():
        if iid in items and lab in label_idx:
            placed[iid] = label_idx[lab]
            load[label_idx[lab]] += items[iid]["credits"]
            fixed.add(iid)
        elif iid in items and parse_term(lab) and term_sort_key(lab) > term_sort_key(labels[-1]):
            pass  # beyond the horizon: ignored (the API refuses these up front)

    def ready(it, t):
        for p in it["prereqs"]:
            if p in completed or p not in items:
                continue  # done already, or not something the roadmap tracks
            if p not in placed or placed[p] >= t:
                return False
        return True

    free = {i for i in items if i not in fixed}
    last_fixed = max((placed[i] for i in fixed), default=-1)
    for t in range(max_terms):
        if not free and t > last_fixed:
            break
        cands = []
        for iid in free:
            it = items[iid]
            if not ready(it, t):
                continue
            if same_season and it["season"] and it["season"] != parse_term(labels[t])[0]:
                continue
            if t == 0 and offered_first is not None and not it["slot"] and it["code"] not in offered_first:
                continue
            cands.append(it)
        cands.sort(key=lambda it: (it["rank"], -down[it["id"]][0], it["code"], it["id"]))
        for it in cands:
            if load[t] == 0 or load[t] + it["credits"] <= max_credits:
                placed[it["id"]] = t
                load[t] += it["credits"]
                free.discard(it["id"])

    unplaced = sorted(free)
    used = max(placed.values(), default=-1)
    terms = []
    for t in range(used + 1):
        terms.append({"label": labels[t], "credits": load[t], "courses": [], "warnings": []})
    for iid, t in placed.items():
        it = items[iid]
        warn = []
        for p in it["prereqs"]:
            if p in completed:
                continue
            if p not in items:
                warn.append(f"needs {p}, which isn't in your curriculum list")
            elif p in unplaced:
                warn.append(f"needs {p}, which couldn't be scheduled")
            elif placed[p] > t:
                warn.append(f"needs {p} first, but {p} is planned later ({labels[placed[p]]})")
            elif placed[p] == t:
                warn.append(f"needs {p} first, but {p} is in the same term")
        if t == 0 and offered_first is not None and not it["slot"] and it["code"] not in offered_first:
            warn.append("has no sections this term")
        if iid in fixed and same_season and it["season"] and it["season"] != parse_term(labels[t])[0]:
            warn.append(f"is a {it['season']} course in the sample plan")
        terms[t]["courses"].append({
            "id": it["id"], "code": it["code"], "name": it["name"], "credits": it["credits"], "slot": it["slot"],
            "fixed": iid in fixed, "plan": it["plan"], "prereqs": it["prereqs"], "warnings": warn,
        })
    for t, term in enumerate(terms):
        term["courses"].sort(key=lambda c: (c["slot"], c["code"], c["id"]))
        if term["credits"] > max_credits:
            term["warnings"].append(f"{term['credits']:g} credits is over your {max_credits:g}-credit limit")
        elif term["credits"] >= HEAVY_TERM_CREDITS:
            term["warnings"].append(f"{term['credits']:g} credits is a heavy term")

    risks = []
    if unplaced:
        loops = sorted(i for i in unplaced if i in in_loop)
        risks.append({"kind": "unplaced", "text": (
            f"{len(unplaced)} course(s) couldn't be placed within {max_terms} terms: "
            f"{', '.join(items[i]['code'] or items[i]['name'] for i in unplaced)}."
            + (" Their prerequisites loop back on each other, so check them on the Curriculum page." if loops else ""))})
    if items:
        depth, chain = max((down[i] for i in items), key=lambda x: x[0])
        if depth >= LONG_CHAIN:
            names = [items[i]["code"] for i in chain]
            sets_date = used + 1 == depth  # the chain alone needs every term the roadmap uses
            risks.append({"kind": "chain", "length": depth, "courses": names, "text": (
                f"A chain of {depth} courses must be taken one after another: {' → '.join(names)}. "
                + ("This chain is what sets your graduation term, so one missed term pushes it back."
                   if sets_date else "Missing any one of them delays everything after it.")),
            })
    heavy = [t["label"] for t in terms if t["credits"] >= HEAVY_TERM_CREDITS or t["credits"] > max_credits]
    if heavy:
        risks.append({"kind": "heavy", "text": f"Heavy term(s): {', '.join(heavy)}. Consider moving a course or using a Summer term."})

    return {
        "terms": terms,
        "start_term": start,
        "graduation_term": terms[-1]["label"] if terms and not unplaced else None,
        "remaining_credits": sum(it["credits"] for it in items.values()),
        "remaining_courses": len(items),
        "unplaced": [{"id": i, "code": items[i]["code"], "name": items[i]["name"]} for i in unplaced],
        "risks": risks,
        "real_offerings_term": start if offered_first is not None else None,
        "max_credits": max_credits,
    }
