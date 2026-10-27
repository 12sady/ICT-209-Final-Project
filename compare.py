"""
compare.py
----------
Pure maths for comparing candidate schedules side by side (no Flask, no files).

A "plan" here is just a list of section dicts (as in course_offerings.json).
`plan_metrics` describes one; `compare_plans` says which plan is best at each
metric and why, in plain words. Ties don't get a winner, and a metric nobody
has data for (e.g. seat counts that were never imported) is left unmarked
instead of guessing.
"""

DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Worst-to-best order of the seat risk labels the importer produces. "unknown"
# is not a risk level: it means no seat numbers were imported.
RISK_RANK = {"low": 0, "medium": 1, "fills fast": 2, "full": 3}


def to_minutes(hhmm):
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def fmt_minutes(m):
    return None if m is None else f"{int(m) // 60:02d}:{int(m) % 60:02d}"


def plan_key(sections):
    """Stable identity of a plan: its sorted 'CODE-SECTION' ids."""
    return "|".join(sorted(f"{s['code']}-{s['section']}" for s in sections))


def plan_metrics(sections, wishlist=(), demand_by_code=None):
    """Everything a student compares between schedules."""
    demand_by_code = demand_by_code or {}
    by_day, online = {}, []
    for s in sections:
        if s.get("online") or not s.get("start") or not s.get("end") or not s.get("days"):
            online.append(f"{s['code']}-{s['section']}")
            continue
        for d in s["days"]:
            by_day.setdefault(d, []).append((to_minutes(s["start"]), to_minutes(s["end"])))

    gaps = []
    for meetings in by_day.values():
        meetings.sort()
        for (_, prev_end), (next_start, _) in zip(meetings, meetings[1:]):
            gaps.append(max(0, next_start - prev_end))
    starts = [m[0] for ms in by_day.values() for m in ms]
    ends = [m[1] for ms in by_day.values() for m in ms]

    seats, worst_rank, risky = [], None, 0
    for s in sections:
        risk = s.get("risk") or "unknown"
        row = {
            "code": s["code"], "section": s["section"], "risk": risk,
            "seats": (f"{int(s['seats_available'])}/{int(s['seats_total'])}"
                      if s.get("seats_available") is not None and s.get("seats_total") is not None else None),
            "demand": (demand_by_code.get(s["code"]) or {}).get("level"),
        }
        seats.append(row)
        if risk in RISK_RANK:
            worst_rank = RISK_RANK[risk] if worst_rank is None else max(worst_rank, RISK_RANK[risk])
            if RISK_RANK[risk] >= 1:
                risky += 1

    codes = {s["code"] for s in sections}
    credits = sum(float(s.get("credits") or 0) for s in sections)
    return {
        "total_credits": credits,
        "courses": len(sections),
        "days": [d for d in DAY_ORDER if d in by_day],
        "days_on_campus": len(by_day),
        "earliest_start": min(starts) if starts else None,
        "latest_end": max(ends) if ends else None,
        "longest_gap": max(gaps) if gaps else 0,
        "total_wait": sum(gaps),
        "left_out": sorted(c for c in wishlist if c not in codes),
        "online": online,
        "seat_risk": seats,
        "worst_risk": next((k for k, v in RISK_RANK.items() if v == worst_rank), None),
        "risky_sections": risky,
        "has_seat_data": worst_rank is not None,
    }


def _winners(values, better):
    """Indices holding the best value ('min' or 'max'); [] when everyone ties
    or there are no comparable values."""
    known = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(known) < 2:
        return []
    target = (min if better == "min" else max)(v for _, v in known)
    win = [i for i, v in known if v == target]
    return [] if len(win) == len(known) else win


def compare_plans(metrics, min_credits=12, max_credits=17):
    """metrics: list of plan_metrics dicts. Returns {row: {"winners": [i...],
    "reason": str}} for every row that has a clear best."""
    out = {}

    def put(row, winners, reason):
        if winners:
            out[row] = {"winners": winners, "reason": reason}

    # Credits: inside the allowed range and as close to the max as possible
    # (the same idea the planner uses to rank schedules).
    credit_key = [(0 if m["total_credits"] >= min_credits else 1, abs(max_credits - m["total_credits"])) for m in metrics]
    put("total_credits", _winners(credit_key, "min"), f"closest to your {max_credits:g}-credit limit without going over")
    put("days_on_campus", _winners([m["days_on_campus"] for m in metrics], "min"), "fewest days on campus")
    put("earliest_start", _winners([m["earliest_start"] for m in metrics], "max"), "latest first class")
    put("latest_end", _winners([m["latest_end"] for m in metrics], "min"), "finishes earliest")
    put("longest_gap", _winners([m["longest_gap"] for m in metrics], "min"), "shortest wait between two classes")
    put("total_wait", _winners([m["total_wait"] for m in metrics], "min"), "least time waiting between classes")
    put("left_out", _winners([len(m["left_out"]) for m in metrics], "min"), "fewest wishlist courses left out")
    # Same count but different courses is NOT "no difference": flag it so the page can say so.
    if "left_out" not in out and len({tuple(m["left_out"]) for m in metrics}) > 1:
        out["left_out"] = {"winners": [], "reason": "Different courses left out", "different": True}

    # Seat risk only when seat data exists for every plan being compared.
    if all(m["has_seat_data"] for m in metrics):
        put("worst_risk", _winners([(RISK_RANK[m["worst_risk"]], m["risky_sections"]) for m in metrics], "min"),
            "safest seats (fewest sections likely to fill)")
    return out
