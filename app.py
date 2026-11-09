"""
app.py
------
Flask app for the Registration Planner.

Pages:
  GET  /              Dashboard -- degree progress, GPA, graduation estimate, what to take next
  GET  /plan          Plan view -- generated registration plans (weekly calendar)
  GET  /compare       Pinned plans side by side
  GET  /roadmap       Graduation roadmap, semester by semester
  GET  /gpa           Grades, GPA and what-if tools
  GET  /browse         Browse the course catalog, filter it, build your wishlist
  GET  /curriculum      Manage completed / required / prerequisite courses
  GET  /import          Upload a registrar Excel sheet and map its columns

API:
  GET  /api/plans
  GET  /api/courses
  GET  /api/wishlist          POST add {code}      DELETE /api/wishlist/<code>
  GET  /api/curriculum        PUT  replace whole object
  POST /api/grade-report/preview  (multipart PDF) -> courses matched to the curriculum, nothing saved
  POST /api/grade-report/apply    {courses: [...]} -> marks them completed + saves grades
  POST /api/import/upload     (multipart file) -> sheet list, or headers+mapping if only one sheet
  POST /api/import/sheet      {sheet_name} -> headers + guessed mapping for that sheet
  POST /api/import/preview    {mapping, sheet_name} -> parsed rows + errors (no save)
  POST /api/import/commit     {mapping, sheet_name} -> parses again and saves course_offerings.json
"""

import io
import json
import os
import queue
import secrets
import threading
from datetime import datetime, timedelta

from flask import (Flask, Response, copy_current_request_context, g, jsonify, redirect, render_template, request,
                   send_file, session, url_for)

import envfile
envfile.load()  # AI settings from .env (git-ignored), before ai.py reads them

import auth
import compare
import demo
import gpa
import grade_report
import programs as plans
import progress
import roadmap
import sheet
import structure
import ai
from scheduler import (
    load_data, load_wishlist, save_wishlist, enumerate_plans, find_alternates,
    build_slots, prereqs_met, missing_prereqs, public_stats,
)
import excel_importer
from excel_importer import list_sheets, read_headers, guess_mapping, parse_with_mapping, TARGET_FIELDS, _risk_from_seats
from parser import parse_schedule_text, CODE_RE
from curriculum_parser import parse_curriculum_text

app = Flask(__name__)
app.secret_key = auth.get_or_create_secret_key()

OFFERINGS_PATH = "data/course_offerings.json"  # shared: same registrar data for every account


# ---------------------------------------------------------------------------
# Accounts (see auth.py). Anyone can sign up; each account's curriculum,
# completed courses, wishlist and preferences live in its own folder.
# ---------------------------------------------------------------------------

_PUBLIC_ENDPOINTS = {"signup", "login", "setup", "static"}
_ADMIN_WRITE_PATHS = {"/api/import/upload", "/api/import/sheet", "/api/import/preview", "/api/import/commit"}


def _user_file(name):
    return os.path.join(auth.user_dir(g.user["id"]), name)


def requirements_path():
    return _user_file("degree_requirements.json")


def wishlist_path():
    return _user_file("wishlist.json")


def roadmap_path():
    return _user_file("roadmap.json")


def plan_choices_path():
    return _user_file("plan_choices.json")


def pending_import_path():
    return _user_file("_pending_import.xlsx")


def _program_structure(req):
    """The official program structure for the student's program, or None
    (then everything keeps using the sample plan, as before)."""
    return structure.get(req.get("program_id"))


def _load_data():
    """load_data for the logged-in student. When their program has a program
    structure (structure.py), the catalog comes back sorted into its
    categories, so every page counts courses the same way."""
    req, offerings = load_data(requirements_path(), OFFERINGS_PATH)
    st = _program_structure(req)
    if st and req.get("catalog"):
        req = structure.overlay(req, st)
    return req, offerings


@app.before_request
def _require_login():
    if request.endpoint in _PUBLIC_ENDPOINTS or request.endpoint is None:
        return
    user = auth.get_user(session.get("user_id")) if session.get("user_id") else None
    if user is None:
        session.clear()
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not logged in"}), 401
        return redirect(url_for("login" if auth.has_users() else "signup"))
    g.user = user
    # Course offerings are the registrar's data, shared by everyone: only the
    # admin can import or change them.
    if request.path in _ADMIN_WRITE_PATHS or request.path.startswith("/api/offerings/"):
        if not auth.is_admin(user):
            return jsonify({"error": "Only the admin account can change the term's course offerings."}), 403


@app.context_processor
def _inject_user():
    user = getattr(g, "user", None)
    return {"current_username": (user or {}).get("username"), "is_admin": auth.is_admin(user)}


def _start_session(user):
    session.clear()
    session["user_id"] = user["id"]


# ---------------------------------------------------------------------------
# Wishlist demand: how many accounts have each course on their wishlist.
# Only counts are ever exposed -- never who -- so students get a heads-up
# that a course will be popular without seeing anyone's plans.
# ---------------------------------------------------------------------------

_DEMAND_HIGH = 5      # this many wishlists (or more) -> "High demand"
_DEMAND_POPULAR = 3   # this many -> "Popular"


def _wishlist_counts():
    counts = {}
    for u in auth.all_users():
        path = os.path.join(auth.user_dir(u["id"]), "wishlist.json")
        for code in set(load_wishlist(path)):
            counts[code] = counts.get(code, 0) + 1
    return counts


def _my_wishlist():
    return set(load_wishlist(wishlist_path()))


def _demand(code, counts, seat_totals, mine=frozenset()):
    n = counts.get(code, 0)
    seats = seat_totals.get(code)
    if seats:  # real seat numbers known: compare interest to capacity
        level = "high" if n >= 0.5 * seats else "popular" if n >= 0.25 * seats else "some" if n else "none"
    else:
        level = "high" if n >= _DEMAND_HIGH else "popular" if n >= _DEMAND_POPULAR else "some" if n else "none"
    # "count" includes you if you've wishlisted it; "others" never does, so
    # your own wishlist item doesn't read as "1 student wants this".
    return {"count": n, "others": n - (1 if code in mine else 0), "level": level}


def _seat_totals(offerings):
    totals = {}
    for s in offerings:
        if s.get("seats_total"):
            totals[s["code"]] = totals.get(s["code"], 0) + s["seats_total"]
    return totals


@app.route("/signup", methods=["GET", "POST"])
def signup():
    error = None
    form = {"username": ""}
    if request.method == "POST":
        form["username"] = request.form.get("username") or ""
        user, error = auth.create_user(
            form["username"],
            request.form.get("password") or "",
            request.form.get("confirm") or "",
        )
        if user:
            _start_session(user)
            return redirect(url_for("curriculum"))
    return render_template("signup.html", error=error, form=form, username_pattern=auth.USERNAME_PATTERN)


@app.route("/setup")
def setup():
    # Old first-run URL, kept so any bookmark still lands somewhere sensible.
    return redirect(url_for("signup"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not auth.has_users():
        return redirect(url_for("signup"))
    error = None
    username = ""
    if request.method == "POST":
        username = request.form.get("username") or ""
        user = auth.authenticate(username, request.form.get("password") or "")
        if user:
            _start_session(user)
            return redirect(url_for("index"))
        error = "Wrong username or password."
    return render_template("login.html", error=error, username=username)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("dashboard.html", active="dashboard")


@app.route("/plan")
def plan_page():
    return render_template("index.html", active="plan")


@app.route("/browse")
def browse():
    return render_template("browse.html", active="browse")


@app.route("/curriculum")
def curriculum():
    return render_template("curriculum.html", active="curriculum")


@app.route("/roadmap")
def roadmap_page():
    return render_template("roadmap.html", active="roadmap")


@app.route("/advisor-summary")
def advisor_summary_page():
    return render_template("advisor_summary.html", active="dashboard")


@app.route("/registration-sheet")
def registration_sheet_page():
    return render_template("registration_sheet.html", active="plan")


@app.route("/compare")
def compare_page():
    return render_template("compare.html", active="compare")


@app.route("/gpa")
def gpa_page():
    return render_template("gpa.html", active="gpa")


@app.route("/import")
def import_page():
    return render_template("import.html", active="import")


# ---------------------------------------------------------------------------
# Plans API
# ---------------------------------------------------------------------------

@app.route("/api/plans")
def api_plans():
    """Every valid plan for the wishlist (see scheduler.enumerate_plans).
    Sections are sent once in `section_pool`; each plan just lists indices
    into it, which keeps thousands of plans small on the wire."""
    requirements, offerings = _load_data()
    wishlist = load_wishlist(wishlist_path())
    search = {}
    plans, blocked_required, blocked_wishlist, no_sections, total_found, exhausted = enumerate_plans(
        requirements, offerings, wishlist, stats=search
    )

    pool, pool_index = [], {}
    out = []
    for p in plans:
        picks = []
        for sec in p["sections"]:
            key = (sec["code"], sec["section"])
            if key not in pool_index:
                pool_index[key] = len(pool)
                pool.append(sec)
            picks.append(pool_index[key])
        out.append({
            "picks": picks,
            "total_credits": p["total_credits"],
            "meets_min_credits": p["meets_min_credits"],
            "unmet_wishlist": p["unmet_wishlist"],
            "days_on_campus": p["days_on_campus"],
            "earliest_start": p["earliest_start"],
            "gap_minutes": p["gap_minutes"],
        })

    return jsonify({
        "program": requirements.get("program", ""),
        "plans": out,
        "section_pool": pool,
        "total_found": total_found,
        "exhausted": exhausted,
        "blocked_required": blocked_required,
        "blocked_wishlist": blocked_wishlist,
        "no_sections": no_sections,
        "ignore_prereqs": bool(requirements.get("preferences", {}).get("ignore_prereqs")),
        "wishlist_count": len(wishlist),
        "min_credits": requirements.get("target_credits", {}).get("min", 12),
        "max_credits": requirements.get("target_credits", {}).get("max", 17),
        "avoid_before": requirements.get("preferences", {}).get("avoid_before") or "",
        "avoid_days": requirements.get("preferences", {}).get("avoid_days") or [],
        "search": public_stats(search),     # "Why this schedule?" on the Plan page
    })


@app.route("/api/plan/alternates", methods=["POST"])
def api_plan_alternates():
    """Backup sections for one plan, computed on demand for whichever plan
    is on screen (instead of for every possible plan up front)."""
    requirements, offerings = _load_data()
    wanted = {(x.get("code"), x.get("section")) for x in (request.get_json(silent=True) or {}).get("sections", [])}
    sections = [s for s in offerings if (s["code"], s["section"]) in wanted]
    return jsonify({"alternates": find_alternates(sections, offerings, requirements)})


@app.route("/api/plan/export/ics", methods=["POST"])
def api_plan_export_ics():
    body = request.get_json(silent=True) or {}
    try:
        ics_text, info = _build_plan_ics(body, _load_calendar())
    except Exception as e:
        app.logger.exception("ICS export failed")
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500
    label = (body.get("label") or "plan").replace(" ", "_")
    resp = send_file(
        io.BytesIO(ics_text.encode("utf-8")),
        mimetype="text/calendar",
        as_attachment=True,
        download_name=f"registration_plan_{label}.ics",
    )
    # Tell the page what was (and wasn't) exported so it can say so.
    resp.headers["X-Export-Info"] = json.dumps(info, ensure_ascii=True)
    return resp


# ---------------------------------------------------------------------------
# Demo student (admin only): a ready-filled account for showing the app off.
# ---------------------------------------------------------------------------

@app.route("/api/admin/demo-student", methods=["POST"])
def api_demo_student():
    if not auth.is_admin(g.user):
        return jsonify({"error": "Only the admin account can create a demo student."}), 403
    body = request.get_json(silent=True) or {}
    progs = plans.load_programs()
    wanted = body.get("program_id")
    prog = (next((p for p in progs if p["id"] == wanted), None) if wanted else
            next((p for p in progs if p["id"] == "ai"), None) or next((p for p in progs if "artificial" in p["name"].lower()), None))
    if not prog:
        return jsonify({"error": "No Artificial Intelligence sample plan is published yet. Add one in 'Sample course plans' first."}), 400

    username = "demo_student"
    n = 2
    while auth._find_by_username(username):
        username = f"demo_student{n}"
        n += 1
    password = secrets.token_urlsafe(6)
    user, err = auth.create_user(username, password, password)
    if err:
        return jsonify({"error": err}), 400

    req = demo.build_requirements(prog, current_term=_load_calendar().get("term") or "Fall 2026")
    offerings = _load_offerings()
    wishlist, plan_keys = demo.choose_wishlist_and_plans(req, offerings)
    folder = auth.user_dir(user["id"])
    with open(os.path.join(folder, "degree_requirements.json"), "w") as f:
        json.dump(req, f, indent=2)
    save_wishlist(wishlist, os.path.join(folder, "wishlist.json"))
    choices = {"pins": [{"id": secrets.token_hex(4), "name": "AB"[i], "sections": k} for i, k in enumerate(plan_keys)],
               "active": {"sections": plan_keys[0]} if plan_keys else None}
    with open(os.path.join(folder, "plan_choices.json"), "w") as f:
        json.dump(choices, f, indent=2)
    return jsonify({"ok": True, "username": username, "password": password, "program": prog["name"],
                    "summary": demo.summary(req, wishlist, choices["pins"])})


# ---------------------------------------------------------------------------
# Registration-day sheet (see sheet.py): the active plan, printable, with backups.
# ---------------------------------------------------------------------------

@app.route("/api/registration-sheet")
def api_registration_sheet():
    requirements, offerings = _load_data()
    cal = _load_calendar()
    out = {
        "student": g.user["username"], "program": requirements.get("program") or "", "term": cal.get("term") or requirements.get("semester") or "",
        "generated": datetime.now().strftime("%d %B %Y"),
        "countdown": sheet.countdown(cal.get("registration_date"), datetime.now()),
        "has_registration_date": bool(cal.get("registration_date")),
        "plan": None,
    }
    active = _load_choices().get("active")
    if not active:
        return jsonify(out)
    found, missing = _resolve_sections(active.get("sections") or [], offerings)
    if not found:
        out["missing"] = [f"{m['code']}-{m['section']}" for m in missing]
        return jsonify(out)
    alts = find_alternates(found, offerings, requirements)
    out["plan"] = {
        "rows": [sheet.sheet_row(s, alts.get(f"{s['code']}-{s['section']}", [])) for s in found],
        "total_credits": sheet.total_credits(found), "sections": found,
        "missing": [f"{m['code']}-{m['section']}" for m in missing],
    }
    return jsonify(out)


# ---------------------------------------------------------------------------
# Advisor-ready summary: progress + GPA + roadmap + active plan in one printable page.
# Built only from numbers the app already computes elsewhere.
# ---------------------------------------------------------------------------

@app.route("/api/advisor-summary")
def api_advisor_summary():
    req, offerings = _load_data()
    cal = _load_calendar()
    out = {"student": g.user["username"], "program": req.get("program") or "", "term": cal.get("term") or req.get("semester") or "",
           "generated": datetime.now().strftime("%d %B %Y"), "has_curriculum": bool(req.get("catalog"))}
    if not out["has_curriculum"]:
        return jsonify(out)
    entries, unknown, total = _gpa_summary(req)
    out["gpa"] = {
        "value": total["gpa"], "gpa_credits": total["gpa_credits"], "attempted": total["attempted"], "earned": total["earned"],
        "graded": sum(1 for e in entries if e["grade"]), "completed": len(entries),
        "semesters": [{"semester": r["semester"], "gpa": r["gpa"], "cumulative_gpa": r["cumulative_gpa"], "credits": r["gpa_credits"]}
                      for r in gpa.by_semester(entries) if r["gpa_credits"] or r["attempted"]],
        "courses": [{"code": e["code"], "name": e["name"], "credits": e["credits"], "semester": e["semester"], "grade": e["grade"]}
                    for e in sorted(entries, key=lambda e: (roadmap.term_sort_key(e["semester"]) or 0, e["code"]))],
    }
    dash = _dashboard_payload()
    out["progress"] = dash["progress"]
    out["remaining_required"] = dash["remaining_required"]
    out["bottlenecks"] = [{"code": b["code"], "name": b["name"], "unlocks": b["unlocks"]} for b in dash["bottlenecks"][:5]]
    rm = _roadmap_payload()
    road = rm["roadmap"]
    out["roadmap"] = {
        "graduation_term": road["graduation_term"], "real_offerings_term": road["real_offerings_term"], "max_credits": road["max_credits"],
        "risks": [r["text"] for r in road["risks"]],
        "terms": [{"label": t["label"], "credits": t["credits"],
                   "courses": [(c["code"] or "Elective slot") + (f" {c['name']}" if c["code"] else "") for c in t["courses"]]} for t in road["terms"]],
    }
    active = _load_choices().get("active")
    found = _resolve_sections(active.get("sections") or [], offerings)[0] if active else []
    out["plan"] = [sheet.sheet_row(s_, []) for s_ in found] if found else None
    out["plan_credits"] = sheet.total_credits(found) if found else 0
    return jsonify(out)


# ---------------------------------------------------------------------------
# Dashboard (see progress.py): one call so the page loads fast.
# ---------------------------------------------------------------------------

def _dashboard_payload():
    req, offerings = _load_data()
    catalog = req.get("catalog", [])
    completed = req.get("completed", [])
    prereqs = req.get("prereqs", {})
    entries, _unknown, gpa_total = _gpa_summary(req)
    planned, planned_source = _planned_courses()
    wishlist = load_wishlist(wishlist_path())
    out = {
        "username": g.user["username"], "program": req.get("program") or "",
        "has_curriculum": bool(catalog), "completed_count": len(completed),
        "wishlist_count": len(wishlist), "offerings_count": len(offerings),
        "gpa": {"value": gpa_total["gpa"], "graded": sum(1 for e in entries if e["grade"]), "completed": len(entries)},
        "planned": {"credits": sum(float(c["credits"] or 0) for c in planned), "courses": len(planned), "source": planned_source},
        "max_credits": req.get("target_credits", {}).get("max", 17),
    }
    if not catalog:
        return out
    offered = {s["code"] for s in offerings} if offerings else None
    st = _program_structure(req)
    if st:
        out["progress"] = structure.evaluate(st, completed)
        out["structure"] = True
    else:
        out["progress"] = progress.category_progress(catalog, completed, req.get("elective_slots", []))
    out["available"] = progress.available_now(catalog, completed, prereqs, offered)
    out["bottlenecks"] = progress.bottlenecks(catalog, completed, prereqs)
    rm = _roadmap_payload()
    out["graduation"] = {
        "term": rm["roadmap"]["graduation_term"], "terms": len(rm["roadmap"]["terms"]),
        "risks": [r["text"] for r in rm["roadmap"]["risks"]], "real_offerings_term": rm["roadmap"]["real_offerings_term"],
        "remaining_courses": rm["roadmap"]["remaining_courses"],
    }
    out["remaining_required"] = (len(out["progress"]["remaining_required"]) if st
                                 else len(progress.remaining_required(catalog, completed)))
    return out


@app.route("/api/dashboard")
def api_dashboard():
    return jsonify(_dashboard_payload())


# ---------------------------------------------------------------------------
# Graduation roadmap (see roadmap.py). The student's own settings and any
# courses they dragged to a different term live in data/users/<id>/roadmap.json;
# the roadmap itself is recomputed from the curriculum on every request, so it
# can never go stale.
# ---------------------------------------------------------------------------

_ROADMAP_DEFAULTS = {"max_credits": None, "start_term": None, "include_summer": False, "same_season": False, "overrides": {}}


def _load_roadmap_settings():
    try:
        with open(roadmap_path()) as f:
            d = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        d = {}
    out = dict(_ROADMAP_DEFAULTS, **{k: d[k] for k in _ROADMAP_DEFAULTS if k in d})
    out["overrides"] = dict(out["overrides"] or {})
    return out


def _save_roadmap_settings(st):
    with open(roadmap_path(), "w") as f:
        json.dump(st, f, indent=2)


def _roadmap_inputs(st=None):
    """Everything build_roadmap needs, from the student's files + settings."""
    st = st or _load_roadmap_settings()
    req, offerings = _load_data()
    cal = _load_calendar()
    tc = req.get("target_credits", {})
    max_credits = st["max_credits"] or tc.get("max") or 17
    include_summer = bool(st["include_summer"])
    start = (st["start_term"] if roadmap.parse_term(st["start_term"]) else None) \
        or (req.get("semester") if roadmap.parse_term(req.get("semester")) else None) \
        or (cal["term"] if roadmap.parse_term(cal.get("term")) else None) \
        or roadmap.guess_start_term(datetime.now())
    start = roadmap.normalize_start(start, include_summer)
    offered_first = None
    if offerings and roadmap.parse_term(cal.get("term")) and roadmap.normalize_start(cal["term"], True) == start:
        offered_first = {s["code"] for s in offerings}
    return {
        "req": req, "settings": st, "start": start, "max_credits": float(max_credits), "include_summer": include_summer,
        "offered_first": offered_first,
        "kwargs": dict(
            catalog=req.get("catalog", []), completed=set(req.get("completed", [])), prereqs=req.get("prereqs", {}),
            slots=req.get("elective_slots", []), start_term=start, max_credits=float(max_credits),
            include_summer=include_summer, same_season=bool(st["same_season"]),
            overrides=st["overrides"], offered_first=offered_first),
    }


def _roadmap_payload(st=None):
    inp = _roadmap_inputs(st)
    req, kw = inp["req"], inp["kwargs"]
    road = roadmap.build_roadmap(**kw)
    catalog = {c["code"]: c for c in req.get("catalog", [])}
    done_credits = sum(float(catalog[c]["credits"]) for c in kw["completed"] if c in catalog)
    prog = plans.get_program(req.get("program_id")) if req.get("program_id") else None
    total = done_credits + road["remaining_credits"]
    check = {"completed_credits": done_credits, "remaining_credits": road["remaining_credits"], "planned_total": total,
             "program_total": prog.get("credit_total") if prog else None,
             "completed_not_in_curriculum": [c for c in kw["completed"] if c not in catalog]}
    labels = roadmap.term_labels(inp["start"], len(road["terms"]) + 3, inp["include_summer"])
    return {
        "roadmap": road, "has_curriculum": bool(catalog), "credit_check": check,
        "settings": {"max_credits": inp["max_credits"], "start_term": inp["start"], "include_summer": inp["include_summer"],
                     "same_season": bool(inp["settings"]["same_season"]), "overrides": inp["settings"]["overrides"]},
        "term_options": labels, "overridden": len(inp["settings"]["overrides"]),
        "completed_count": len(kw["completed"]),
    }


@app.route("/api/roadmap")
def api_roadmap():
    return jsonify(_roadmap_payload())


@app.route("/api/roadmap/settings", methods=["PUT"])
def api_roadmap_settings():
    body = request.get_json(silent=True) or {}
    st = _load_roadmap_settings()
    if "max_credits" in body:
        try:
            v = float(body["max_credits"]) if body["max_credits"] not in (None, "") else None
        except (TypeError, ValueError):
            return jsonify({"error": "Max credits must be a number."}), 400
        if v is not None and not 1 <= v <= 30:
            return jsonify({"error": "Max credits per term should be between 1 and 30."}), 400
        st["max_credits"] = v
    if "start_term" in body:
        v = str(body["start_term"] or "").strip()
        if v and not roadmap.parse_term(v):
            return jsonify({"error": "Start term should look like 'Fall 2026'."}), 400
        st["start_term"] = v.title() if v else None
    for k in ("include_summer", "same_season"):
        if k in body:
            st[k] = bool(body[k])
    _save_roadmap_settings(st)
    return jsonify(_roadmap_payload(st))


@app.route("/api/roadmap/move", methods=["POST"])
def api_roadmap_move():
    """Pin a course to a term (or, with term null, hand it back to the planner).
    Never refuses for prerequisite or credit reasons: the response carries the
    warnings instead, so the student sees the consequences of the move."""
    body = request.get_json(silent=True) or {}
    cid, term = str(body.get("id") or ""), body.get("term")
    st = _load_roadmap_settings()
    inp = _roadmap_inputs(st)
    items = {c["id"] for t in roadmap.build_roadmap(**dict(inp["kwargs"], overrides={}))["terms"] for c in t["courses"]}
    if cid not in items:
        return jsonify({"error": "That course isn't one of your remaining courses."}), 400
    if term in (None, ""):
        st["overrides"].pop(cid, None)
    else:
        term = str(term).strip().title()
        labels = roadmap.term_labels(inp["start"], roadmap.MAX_TERMS, inp["include_summer"])
        if term not in labels:
            return jsonify({"error": f"Pick a term from {labels[0]} to {labels[-1]}."}), 400
        st["overrides"][cid] = term
    _save_roadmap_settings(st)
    return jsonify(_roadmap_payload(st))


@app.route("/api/roadmap/reset", methods=["POST"])
def api_roadmap_reset():
    st = _load_roadmap_settings()
    st["overrides"] = {}
    _save_roadmap_settings(st)
    return jsonify(_roadmap_payload(st))


# ---------------------------------------------------------------------------
# Pinned plans + the active plan (per student: data/users/<id>/plan_choices.json)
#
# A plan is saved as its list of {code, section} ids, never as a position in
# the planner's ranking (that changes whenever the wishlist does), and is
# re-read from the current offerings every time, so a section that was removed
# from the term shows up as "no longer offered" instead of silently vanishing.
# ---------------------------------------------------------------------------

MAX_PINS = 3


def _load_choices():
    try:
        with open(plan_choices_path()) as f:
            d = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        d = {}
    return {"pins": d.get("pins") or [], "active": d.get("active")}


def _save_choices(d):
    with open(plan_choices_path(), "w") as f:
        json.dump(d, f, indent=2)


def _clean_keys(raw):
    out = []
    for x in raw or []:
        if isinstance(x, dict) and x.get("code") and x.get("section") is not None:
            out.append({"code": str(x["code"]), "section": str(x["section"])})
    return out[:12]


def _resolve_sections(keys, offerings):
    index = {(s["code"], str(s["section"])): s for s in offerings}
    found, missing = [], []
    for k in keys:
        s = index.get((k["code"], str(k["section"])))
        (found if s else missing).append(s or k)
    return found, missing


def _plan_ctx(sections_keys):
    """Resolve a saved plan against today's offerings."""
    _, offerings = _load_data()
    return _resolve_sections(sections_keys, offerings)


@app.route("/api/plan/choices")
def api_plan_choices():
    ch = _load_choices()
    active = ch["active"]
    if active:
        found, missing = _plan_ctx(active["sections"])
        active = {"sections": active["sections"], "key": compare.plan_key(found), "missing": [f"{m['code']}-{m['section']}" for m in missing]}
    return jsonify({
        "pins": [dict(p, key=compare.plan_key(p["sections"])) for p in ch["pins"]],
        "active": active, "max_pins": MAX_PINS,
    })


@app.route("/api/plan/pins", methods=["POST"])
def api_plan_pin():
    keys = _clean_keys((request.get_json(silent=True) or {}).get("sections"))
    found, missing = _plan_ctx(keys)
    if not keys or missing:
        return jsonify({"error": "That plan has sections that aren't offered any more."}), 400
    ch = _load_choices()
    key = compare.plan_key(found)
    if any(compare.plan_key(p["sections"]) == key for p in ch["pins"]):
        return jsonify({"ok": True, "already": True, "pins": ch["pins"]})
    if len(ch["pins"]) >= MAX_PINS:
        return jsonify({"error": f"You can compare up to {MAX_PINS} plans. Remove one first."}), 400
    used = {p.get("name") for p in ch["pins"]}
    name = next(n for n in "ABCDEFGH" if n not in used)
    ch["pins"].append({"id": secrets.token_hex(4), "name": name, "sections": keys})
    _save_choices(ch)
    return jsonify({"ok": True, "pins": ch["pins"]})


@app.route("/api/plan/pins/<pin_id>", methods=["DELETE"])
def api_plan_unpin(pin_id):
    ch = _load_choices()
    ch["pins"] = [p for p in ch["pins"] if p["id"] != pin_id]
    _save_choices(ch)
    return jsonify({"ok": True, "pins": ch["pins"]})


@app.route("/api/plan/active", methods=["POST", "DELETE"])
def api_plan_active():
    ch = _load_choices()
    if request.method == "DELETE":
        ch["active"] = None
    else:
        keys = _clean_keys((request.get_json(silent=True) or {}).get("sections"))
        found, missing = _plan_ctx(keys)
        if not keys or missing:
            return jsonify({"error": "That plan has sections that aren't offered any more."}), 400
        ch["active"] = {"sections": keys}
    _save_choices(ch)
    return jsonify({"ok": True})


@app.route("/api/plan/compare")
def api_plan_compare():
    requirements, offerings = _load_data()
    wishlist = load_wishlist(wishlist_path())
    counts, seats, mine = _wishlist_counts(), _seat_totals(offerings), set(wishlist)
    demand = {c: _demand(c, counts, seats, mine) for c in {s["code"] for s in offerings}}
    tc = requirements.get("target_credits", {})
    ch = _load_choices()
    active_key = compare.plan_key(_resolve_sections(ch["active"]["sections"], offerings)[0]) if ch["active"] else None

    plans_out, all_metrics = [], []
    for p in ch["pins"]:
        found, missing = _resolve_sections(p["sections"], offerings)
        m = compare.plan_metrics(found, wishlist, demand)
        all_metrics.append(m)
        plans_out.append({
            "id": p["id"], "name": p["name"], "sections": found,
            "missing": [f"{x['code']}-{x['section']}" for x in missing],
            "metrics": m, "is_active": active_key is not None and compare.plan_key(found) == active_key,
        })
    best = compare.compare_plans(all_metrics, tc.get("min", 12), tc.get("max", 17)) if len(all_metrics) > 1 else {}
    return jsonify({"plans": plans_out, "best": best, "min_credits": tc.get("min", 12), "max_credits": tc.get("max", 17),
                    "wishlist_count": len(wishlist), "max_pins": MAX_PINS,
                    "verdict": compare.verdict(best, len(plans_out)) if len(plans_out) > 1 else None})


# ---------------------------------------------------------------------------
# Academic calendar (shared, admin-edited) + calendar export
#
# The calendar gives the term's first/last day and any breaks. It is shared by
# everyone: only the admin (the first account created) can change it. Dates
# that come with a section (the Excel's Start Date / End Date columns) take
# priority over it, since the registrar knows best for that section.
# ---------------------------------------------------------------------------

CALENDAR_PATH = "data/academic_calendar.json"
EMPTY_CALENDAR = {"term": "", "start": None, "end": None, "breaks": [], "registration_date": None}


def _load_calendar():
    try:
        with open(CALENDAR_PATH) as f:
            cal = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(EMPTY_CALENDAR, breaks=[])
    return dict(EMPTY_CALENDAR, **{k: cal.get(k) for k in EMPTY_CALENDAR if k in cal})


def _clean_calendar(raw):
    """Validate an admin's calendar submission; raises ValueError for the UI."""
    term = str(raw.get("term") or "").strip()[:60]
    start = _clean_iso_date(raw.get("start"), "First day of classes")
    end = _clean_iso_date(raw.get("end"), "Last day of classes")
    if bool(start) != bool(end):
        raise ValueError("Fill in both the first and last day of classes (or leave both empty).")
    if start and end < start:
        raise ValueError("The last day of classes is before the first day.")

    breaks = []
    for b in (raw.get("breaks") or [])[:40]:
        name = str(b.get("name") or "").strip()[:60] or "Break"
        b_start = _clean_iso_date(b.get("start"), f"'{name}' start")
        b_end = _clean_iso_date(b.get("end"), f"'{name}' end") or b_start
        if not b_start:
            raise ValueError(f"'{name}' needs a start date.")
        if b_end < b_start:
            raise ValueError(f"'{name}' ends before it starts.")
        breaks.append({"name": name, "start": b_start, "end": b_end})
    breaks.sort(key=lambda b: b["start"])
    registration = _clean_iso_date(raw.get("registration_date"), "Registration date")
    return {"term": term, "start": start, "end": end, "breaks": breaks, "registration_date": registration}


def _detected_term_dates(offerings):
    """The most common (start_date, end_date) among the imported sections, so
    the admin can adopt them with one click."""
    counts = {}
    for s in offerings:
        if s.get("start_date") and s.get("end_date"):
            k = (s["start_date"], s["end_date"])
            counts[k] = counts.get(k, 0) + 1
    if not counts:
        return None
    (start, end), n = max(counts.items(), key=lambda kv: kv[1])
    return {"start": start, "end": end, "sections": n}


@app.route("/api/academic-calendar", methods=["GET", "PUT"])
def api_academic_calendar():
    if request.method == "PUT":
        if not auth.is_admin(g.user):
            return jsonify({"error": "Only the admin account can change the academic calendar."}), 403
        try:
            cal = _clean_calendar(request.get_json(silent=True) or {})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        os.makedirs("data", exist_ok=True)
        with open(CALENDAR_PATH, "w") as f:
            json.dump(cal, f, indent=2)
        return jsonify({"ok": True, "calendar": cal})

    return jsonify({
        "calendar": _load_calendar(),
        "can_edit": auth.is_admin(g.user),
        "detected": _detected_term_dates(_load_offerings()),
    })


_ICS_DAY_CODES = {"Mon": "MO", "Tue": "TU", "Wed": "WE", "Thu": "TH", "Fri": "FR", "Sat": "SA", "Sun": "SU"}
_WEEKDAY_INDEX = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
_ICS_TZID = "Asia/Phnom_Penh"
_ICS_TZ_OFFSET = timedelta(hours=7)  # Cambodia: UTC+7, no daylight saving


def _ics_escape(text):
    return (str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _ics_fold(line):
    """RFC 5545: lines are at most 75 octets; continue on a new line starting
    with a space. Folds on character boundaries so UTF-8 isn't split."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > (75 if not out else 74):
            out.append(cur)
            cur, size = "", 0
        cur += ch
        size += n
    out.append(cur)
    return "\r\n ".join(out)


def _parse_hm(t):
    h, m = t.split(":")
    return int(h), int(m)


def _build_plan_ics(plan, calendar=None):
    """One recurring event per section (a weekly series on all its meeting
    days), in Phnom Penh time, with the classroom as the location. Returns
    (ics_text, info).

    Date range for each section, best first:
      1. the section's own start/end date (from the Excel import)
      2. the academic calendar's first/last day
      3. no dates known: start at the next upcoming meeting day and repeat
         for 15 weeks (the user can adjust the end in their calendar app).
    Calendar breaks are skipped with EXDATE when they're known."""
    calendar = calendar or EMPTY_CALENDAR
    now = datetime.now()
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    breaks = []
    for b in calendar.get("breaks") or []:
        d0 = datetime.strptime(b["start"], "%Y-%m-%d").date()
        d1 = datetime.strptime(b["end"], "%Y-%m-%d").date()
        breaks.append((d0, d1))

    term = calendar.get("term") or ""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Registration Planner//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_escape(('Classes - ' + term) if term else 'My classes')}",
        f"X-WR-TIMEZONE:{_ICS_TZID}",
        # Cambodia has no daylight saving, so a single fixed-offset rule is enough.
        "BEGIN:VTIMEZONE",
        f"TZID:{_ICS_TZID}",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        "TZOFFSETFROM:+0700",
        "TZOFFSETTO:+0700",
        "TZNAME:ICT",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]

    skipped_online, sources = [], {"section": 0, "calendar": 0, "none": 0}
    exported = 0

    for s in plan.get("sections", []):
        label = f"{s.get('code', '')} {s.get('section', '')}".strip()
        days = [d for d in (s.get("days") or []) if d in _WEEKDAY_INDEX]
        if s.get("online") or not s.get("start") or not s.get("end") or not days:
            skipped_online.append(label)
            continue

        # --- which dates does this class run between? ---
        range_start = range_end = None
        try:
            if s.get("start_date") and s.get("end_date"):
                range_start = datetime.strptime(s["start_date"], "%Y-%m-%d").date()
                range_end = datetime.strptime(s["end_date"], "%Y-%m-%d").date()
                sources["section"] += 1
            elif calendar.get("start") and calendar.get("end"):
                range_start = datetime.strptime(calendar["start"], "%Y-%m-%d").date()
                range_end = datetime.strptime(calendar["end"], "%Y-%m-%d").date()
                sources["calendar"] += 1
        except ValueError:
            range_start = range_end = None
        if range_start and range_end and range_end < range_start:
            range_start = range_end = None
        if not range_start:
            sources["none"] += 1
            range_start = now.date()

        wanted = {_WEEKDAY_INDEX[d] for d in days}
        first = range_start
        for _ in range(7):
            if first.weekday() in wanted:
                break
            first += timedelta(days=1)
        if range_end and first > range_end:
            skipped_online.append(label + " (no class day within its dates)")
            continue

        sh, sm = _parse_hm(s["start"])
        eh, em = _parse_hm(s["end"])
        dtstart = datetime(first.year, first.month, first.day, sh, sm)
        dtend = datetime(first.year, first.month, first.day, eh, em)

        byday = ",".join(_ICS_DAY_CODES[d] for d in sorted(days, key=_WEEKDAY_INDEX.get))
        if range_end and (s.get("start_date") or calendar.get("end")):
            # UNTIL has to be UTC when DTSTART has a TZID. End of the last day.
            until_local = datetime(range_end.year, range_end.month, range_end.day, 23, 59, 59)
            until = (until_local - _ICS_TZ_OFFSET).strftime("%Y%m%dT%H%M%SZ")
            rrule = f"RRULE:FREQ=WEEKLY;BYDAY={byday};UNTIL={until}"
            last = range_end
        else:
            rrule = f"RRULE:FREQ=WEEKLY;BYDAY={byday};COUNT={15 * len(days)}"
            last = None

        # Skip class days that fall in a break.
        ex = []
        if breaks:
            day = first
            horizon = last or (first + timedelta(weeks=15))
            while day <= horizon:
                if day.weekday() in wanted and any(b0 <= day <= b1 for b0, b1 in breaks):
                    ex.append(datetime(day.year, day.month, day.day, sh, sm).strftime("%Y%m%dT%H%M%S"))
                day += timedelta(days=1)

        desc = [f"Section {s.get('section', '')}"]
        if s.get("instructor"):
            desc.append(f"Instructor: {s['instructor']}")
        if s.get("credits"):
            desc.append(f"{s['credits']:g} credits" if isinstance(s["credits"], (int, float)) else f"{s['credits']} credits")
        if s.get("location"):
            desc.append(f"Room: {s['location']}")

        uid = f"{s.get('code', '')}-{s.get('section', '')}".replace(" ", "") + "@registration-planner"
        ev = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;TZID={_ICS_TZID}:{dtstart.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID={_ICS_TZID}:{dtend.strftime('%Y%m%dT%H%M%S')}",
            rrule,
        ]
        if ex:
            ev.append(f"EXDATE;TZID={_ICS_TZID}:{','.join(ex)}")
        ev.append(f"SUMMARY:{_ics_escape((s.get('code', '') + ' ' + s.get('title', '')).strip())}")
        if s.get("location"):
            ev.append(f"LOCATION:{_ics_escape(s['location'])}")
        ev.append(f"DESCRIPTION:{_ics_escape(chr(10).join(desc))}")
        ev.append("END:VEVENT")
        lines += ev
        exported += 1

    lines.append("END:VCALENDAR")
    ics = "\r\n".join(_ics_fold(l) for l in lines) + "\r\n"
    info = {
        "exported": exported,
        "skipped": skipped_online,
        "dates_from": {k: v for k, v in sources.items() if v},
        "term": term,
        "breaks": len(breaks),
    }
    return ics, info


# ---------------------------------------------------------------------------
# Course catalog + wishlist API
# ---------------------------------------------------------------------------

@app.route("/api/status")
def api_status():
    """Everything the status strip under the header shows, in one request:
    degree progress (program structure when there is one, else the sample
    plan), program, sections loaded this term, required courses left, wishlist size."""
    req, offerings = _load_data()
    catalog, completed = req.get("catalog", []), req.get("completed", [])
    prog = None
    if catalog:
        st = _program_structure(req)
        p = structure.evaluate(st, completed) if st else progress.category_progress(catalog, completed, req.get("elective_slots", []))
        prog = {"done": p["done"], "total": p["total"], "percent": p["percent"]}
    return jsonify({
        "program": req.get("program") or "", "sections": len(offerings),
        "required_left": len(req.get("required_remaining") or []),
        "wishlist": len(load_wishlist(wishlist_path())), "progress": prog,
    })


@app.route("/api/courses")
def api_courses():
    _, offerings = _load_data()
    counts, seats, mine = _wishlist_counts(), _seat_totals(offerings), _my_wishlist()
    courses = [dict(c, demand=_demand(c["code"], counts, seats, mine)) for c in offerings]
    return jsonify({"courses": courses})


@app.route("/api/wishlist", methods=["GET", "POST"])
def api_wishlist():
    requirements, offerings = _load_data()
    wishlist = load_wishlist(wishlist_path())

    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        code = (body.get("code") or "").strip()
        if code and code not in wishlist:
            wishlist.append(code)
            save_wishlist(wishlist, wishlist_path())

    offered_codes = {s["code"] for s in offerings}
    counts, seats, mine = _wishlist_counts(), _seat_totals(offerings), set(wishlist)
    status = []
    for code in wishlist:
        if not prereqs_met(code, requirements):
            status.append({"code": code, "status": "blocked", "missing_prereqs": missing_prereqs(code, requirements)})
        elif code not in offered_codes:
            status.append({"code": code, "status": "not_offered", "missing_prereqs": []})
        else:
            status.append({"code": code, "status": "ok", "missing_prereqs": []})

    for item in status:
        item["demand"] = _demand(item["code"], counts, seats, mine)
    return jsonify({"wishlist": status})


@app.route("/api/wishlist/<code>", methods=["DELETE"])
def api_wishlist_remove(code):
    wishlist = load_wishlist(wishlist_path())
    wishlist = [c for c in wishlist if c != code]
    save_wishlist(wishlist, wishlist_path())
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Curriculum API
# ---------------------------------------------------------------------------

@app.route("/api/curriculum", methods=["GET", "PUT"])
def api_curriculum():
    if request.method == "PUT":
        body = request.get_json(silent=True) or {}
        for key in ("structure_progress",):       # read-only extras sent back by GET
            body.pop(key, None)
        # Safety net: when a full catalog is present, required_remaining is
        # always derived from it (required courses minus completed ones)
        # rather than trusted as a separately-maintained list, so the two
        # can never silently drift apart.
        catalog = body.get("catalog") or []
        if catalog:
            completed = set(body.get("completed", []))
            body["required_remaining"] = [
                c["code"] for c in catalog if c.get("required") and c["code"] not in completed
            ]
        # Grades are edited on the GPA page; the Curriculum page never owns them,
        # so a stale copy of this page can't wipe or overwrite them.
        existing, _ = _load_data()
        done = set(body.get("completed", []))
        grades = {c: g for c, g in (existing.get("grades") or {}).items() if c in done}
        if grades:
            body["grades"] = grades
        else:
            body.pop("grades", None)
        with open(requirements_path(), "w") as f:
            json.dump(body, f, indent=2)
        return jsonify({"ok": True})

    requirements, _ = _load_data()
    st = _program_structure(requirements)
    if st:
        requirements = dict(requirements, structure_progress=structure.evaluate(st, requirements.get("completed", [])))
    return jsonify(requirements)


# ---------------------------------------------------------------------------
# GPA (see gpa.py). Grades live in the student's own requirements file as an
# optional {"grades": {"COSC 111": "A-"}} map; old files without it still work.
# ---------------------------------------------------------------------------

def _gpa_entries(req):
    """One entry per completed course that has a known credit value; the rest
    (completed but not in the catalog) are returned separately."""
    catalog = {c["code"]: c for c in req.get("catalog", [])}
    grades = req.get("grades") or {}
    sems = req.get("completed_semesters") or {}
    entries, unknown = [], []
    for code in req.get("completed", []):
        c = catalog.get(code)
        if not c:
            unknown.append(code)
            continue
        entries.append({
            "code": code, "name": c.get("name") or "", "credits": c.get("credits") or 0,
            "semester": sems.get(code) or "", "grade": gpa.normalize_grade(grades.get(code)),
        })
    return entries, unknown


def _planned_courses():
    """Courses of the student's chosen (active) plan, or of the best-ranked plan
    when none is chosen. Returns (courses, source) with source "active"/"best"/None."""
    requirements, offerings = _load_data()
    active = _load_choices().get("active")
    if active:
        found, _missing = _resolve_sections(active.get("sections") or [], offerings)
        if found:
            return [_course_row(s) for s in found], "active"
    wishlist = load_wishlist(wishlist_path())
    plans_, *_ = enumerate_plans(requirements, offerings, wishlist, limit=1)
    if not plans_:
        return [], None
    return [_course_row(s) for s in plans_[0]["sections"]], "best"


def _course_row(s):
    return {"code": s["code"], "name": s.get("title") or "", "credits": s.get("credits") or 0}


def _gpa_summary(req):
    entries, unknown = _gpa_entries(req)
    return entries, unknown, gpa.totals(entries)


@app.route("/api/gpa")
def api_gpa():
    req, _ = _load_data()
    entries, unknown, total = _gpa_summary(req)
    planned, planned_source = _planned_courses()
    return jsonify({
        "entries": entries,
        "unknown_credits": unknown,
        "summary": total,
        "ungraded": [e["code"] for e in entries if not e["grade"]],
        "semesters": gpa.by_semester(entries),
        "planned": planned,
        "planned_source": planned_source,
        "grade_options": gpa.grade_options(),
        "scale": gpa.GRADE_SCALE,
        "non_gpa": gpa.NON_GPA_GRADES,
        "max_credits": req.get("target_credits", {}).get("max", 17),
        "has_curriculum": bool(req.get("catalog")),
    })


@app.route("/api/grades", methods=["PUT"])
def api_grades():
    """Set (or clear, with "") grades for completed courses. Only the grades
    map is touched; the rest of the curriculum file is left exactly as it is."""
    body = (request.get_json(silent=True) or {}).get("grades")
    if not isinstance(body, dict):
        return jsonify({"error": "Send {\"grades\": {\"COSC 111\": \"A\"}}."}), 400
    req, _ = _load_data()
    done = set(req.get("completed", []))
    grades = dict(req.get("grades") or {})
    for code, raw in body.items():
        if code not in done:
            return jsonify({"error": f"{code} isn't marked completed on the Curriculum page."}), 400
        if str(raw or "").strip() == "":
            grades.pop(code, None)
            continue
        g = gpa.normalize_grade(raw)
        if not g:
            return jsonify({"error": f"'{raw}' isn't a grade I know. Use one of: {', '.join(gpa.grade_options())}."}), 400
        grades[code] = g
    req["grades"] = grades
    with open(requirements_path(), "w") as f:
        json.dump(req, f, indent=2)
    entries, unknown, total = _gpa_summary(req)
    return jsonify({"ok": True, "summary": total, "semesters": gpa.by_semester(entries),
                    "ungraded": [e["code"] for e in entries if not e["grade"]]})


# ---------------------------------------------------------------------------
# Grade report PDF import (see grade_report.py). The PDF is read in memory and
# never written to disk; preview saves nothing, apply saves the picked rows.
# ---------------------------------------------------------------------------

_MAX_PDF_BYTES = 5 * 1024 * 1024


def _report_gpa_check(req, rows, report_gpa):
    """The app's GPA if every completed row were applied, next to the report's."""
    picked = [{"code": r["code"] or r["report_code"], "grade": r["grade"], "term": r["term"],
               "add": None if r["code"] else {"name": r["name"], "credits": r["credits"]}}
              for r in rows if r["status"] == "completed"]
    try:
        after, _ = grade_report.apply(req, picked)
    except ValueError:
        return {"report": report_gpa, "app": None, "differs": False}
    app_gpa = gpa.totals(_gpa_entries(after)[0])["gpa"]
    differs = report_gpa is not None and app_gpa is not None and abs(round(app_gpa, 2) - report_gpa) > 0.005
    return {"report": report_gpa, "app": None if app_gpa is None else round(app_gpa, 2), "differs": differs}


@app.route("/api/grade-report/preview", methods=["POST"])
def api_grade_report_preview():
    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify({"error": "Choose your grade report PDF first."}), 400
    data = f.read(_MAX_PDF_BYTES + 1)
    if len(data) > _MAX_PDF_BYTES:
        return jsonify({"error": "That file is over 5 MB; a grade report is much smaller. Is it the right file?"}), 400
    if not data.startswith(b"%PDF"):
        return jsonify({"error": "That isn't a PDF. In SIS, open Grade Report and save/print it as PDF."}), 400
    try:
        parsed = grade_report.parse_pages(grade_report.read_pdf(io.BytesIO(data)))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        del data
    if not parsed["courses"]:
        return jsonify({"error": "No courses found. This reader only understands AUPP's SIS Grade Report PDF "
                                 "(not a scanned photo)."}), 400
    req, _ = _load_data()
    if not req.get("catalog"):
        return jsonify({"error": "Load your curriculum first (pick your major's sample plan above), then import grades."}), 400
    rows = grade_report.match(parsed, req.get("catalog", []))
    done, grades = set(req.get("completed", [])), req.get("grades") or {}
    for r in rows:
        r["already_completed"] = bool(r["code"] and r["code"] in done)
        r["current_grade"] = grades.get(r["code"]) if r["code"] else None
    return jsonify({"rows": rows, "terms": parsed["terms"], "warnings": parsed["warnings"],
                    "gpa": _report_gpa_check(req, rows, parsed["cum_gpa"])})


@app.route("/api/grade-report/apply", methods=["POST"])
def api_grade_report_apply():
    picked = (request.get_json(silent=True) or {}).get("courses")
    if not isinstance(picked, list) or not picked:
        return jsonify({"error": "Tick at least one course to import."}), 400
    req, _ = _load_data()
    try:
        new_req, counts = grade_report.apply(req, picked)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    st = _program_structure(new_req)
    if st:
        new_req = structure.overlay(new_req, st)
    with open(requirements_path(), "w") as f:
        json.dump(new_req, f, indent=2)
    entries, _unknown, total = _gpa_summary(new_req)
    return jsonify({"ok": True, **counts, "gpa": total["gpa"]})


@app.route("/api/gpa/whatif", methods=["POST"])
def api_gpa_whatif():
    """Nothing is saved: tries grades for the planned term, and/or works out
    what average is needed to hit a target cumulative GPA."""
    body = request.get_json(silent=True) or {}
    req, _ = _load_data()
    entries, _, _ = _gpa_summary(req)
    out = {}
    if isinstance(body.get("grades"), dict):
        credits = {c["code"]: c["credits"] for c in _planned_courses()[0]}
        planned = [{"credits": credits.get(code, 0), "grade": g} for code, g in body["grades"].items() if code in credits]
        out["whatif"] = gpa.what_if(entries, planned)
    if body.get("target") not in (None, ""):
        out["target"] = gpa.required_average(entries, body.get("credits"), body.get("target"))
    return jsonify(out)


# ---------------------------------------------------------------------------
# Program plans (sample course plans per major)
#
# Shared and published by the admin. A student picks one to start their own
# curriculum from, then edits their own copy; only the admin edits the shared
# plans themselves.
# ---------------------------------------------------------------------------

def _admin_only():
    if not auth.is_admin(g.user):
        return jsonify({"error": "Only the admin account can change the shared program plans."}), 403
    return None


@app.route("/api/programs", methods=["GET", "POST"])
def api_programs():
    if request.method == "POST":
        denied = _admin_only()
        if denied:
            return denied
        try:
            prog = plans.clean_program(request.get_json(silent=True) or {})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        existing = plans.load_programs()
        ids = {p["id"] for p in existing}
        base, n = prog["id"], 2
        while prog["id"] in ids:  # never overwrite another program by accident
            prog["id"] = f"{base}-{n}"
            n += 1
        existing.append(prog)
        plans.save_programs(existing)
        return jsonify({"ok": True, "program": prog})

    requirements, _ = _load_data()
    return jsonify({
        "programs": [plans.summary(p) for p in plans.load_programs()],
        "can_edit": auth.is_admin(g.user),
        "current": requirements.get("program_id"),
    })


@app.route("/api/programs/<program_id>", methods=["GET", "PUT", "DELETE"])
def api_program(program_id):
    existing = plans.load_programs()
    idx = next((i for i, p in enumerate(existing) if p["id"] == program_id), None)
    if idx is None:
        return jsonify({"error": "That program plan doesn't exist."}), 404
    if request.method == "GET":
        return jsonify({"program": existing[idx], "can_edit": auth.is_admin(g.user)})

    denied = _admin_only()
    if denied:
        return denied
    if request.method == "DELETE":
        existing.pop(idx)
        plans.save_programs(existing)
        return jsonify({"ok": True})
    try:
        prog = plans.clean_program(request.get_json(silent=True) or {}, program_id=program_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    existing[idx] = prog
    plans.save_programs(existing)
    return jsonify({"ok": True, "program": prog})


@app.route("/api/curriculum/from-program", methods=["POST"])
def api_curriculum_from_program():
    """Start (or restart) the student's own curriculum from a program plan.
    Their completed courses, semesters and preferences are kept."""
    body = request.get_json(silent=True) or {}
    prog = plans.get_program(body.get("program_id"))
    if not prog:
        return jsonify({"error": "Pick a program plan first."}), 400
    requirements, _ = _load_data()
    new_req = plans.apply_program(requirements, prog)
    st = _program_structure(new_req)
    if st:
        new_req = structure.overlay(new_req, st)
    # Fill the Year / Semester boxes only when they're empty: never overwrite what the student already has.
    sug = progress.suggest_profile(new_req["catalog"], new_req.get("completed", []), _load_calendar().get("term"))
    filled = []
    for key in ("year", "semester"):
        if not str(new_req.get(key) or "").strip() and sug[key]:
            new_req[key] = sug[key]
            filled.append(key)
    with open(requirements_path(), "w") as f:
        json.dump(new_req, f, indent=2)
    return jsonify({"ok": True, "courses": len(new_req["catalog"]), "program": new_req["program"], "filled": filled})


@app.route("/api/curriculum/through", methods=["POST"])
def api_curriculum_through():
    """Which saved-curriculum courses sit at or before a sample-plan semester.
    Read-only: the Curriculum page merges the answer into its own unsaved state."""
    body = request.get_json(silent=True) or {}
    requirements, _ = _load_data()
    try:
        codes = progress.courses_through(requirements.get("catalog", []), body.get("year"), body.get("term"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    done = set(requirements.get("completed", []))
    return jsonify({"codes": codes, "new": [c for c in codes if c not in done]})


@app.route("/api/curriculum/parse", methods=["POST"])
def api_curriculum_parse():
    """Paste-in parser for a curriculum table copied from a system with no
    file export (e.g. Rean). Only parses/previews -- the Curriculum page
    merges the result into its editable state, nothing is saved here."""
    body = request.get_json(silent=True) or {}
    text = body.get("text", "")
    result = parse_curriculum_text(text)
    return jsonify(result)


# ---------------------------------------------------------------------------
# AI advisor (Claude API) -- see ai.py. The tools below are the only way the
# model touches data, and they only ever touch the logged-in student's own
# curriculum, wishlist and preferences.
# ---------------------------------------------------------------------------

def _hhmm(minutes):
    return None if minutes is None else f"{int(minutes) // 60:02d}:{int(minutes) % 60:02d}"


def _sec_brief(s, demand=None):
    out = {
        "code": s["code"], "section": s["section"], "title": s.get("title"),
        "days": s.get("days") or [], "start": s.get("start"), "end": s.get("end"),
        "credits": s.get("credits"), "instructor": s.get("instructor") or None,
        "online": bool(s.get("online")),
    }
    if s.get("location"):
        out["room"] = s["location"]
    if s.get("seats_available") is not None and s.get("seats_total") is not None:
        out["seats"] = f"{int(s['seats_available'])}/{int(s['seats_total'])}"
    out["seat_risk"] = s.get("risk") or "unknown"
    if demand:
        out["students_wishlisting"] = demand["count"]
        out["demand"] = demand["level"]
    return out


def _advisor_context():
    requirements, offerings = _load_data()
    wishlist = load_wishlist(wishlist_path())
    cal = _load_calendar()
    catalog = {c["code"]: c for c in requirements.get("catalog", [])}
    completed = requirements.get("completed", [])
    done_credits = sum(float(catalog[c]["credits"]) for c in completed if c in catalog)
    prefs = requirements.get("preferences", {})
    tc = requirements.get("target_credits", {})
    lines = [
        f"Today: {datetime.now().strftime('%A %d %B %Y')}",
        f"Term: {cal.get('term') or 'not set'}" + (f" ({cal['start']} to {cal['end']})" if cal.get("start") else ""),
        f"Program: {requirements.get('program') or 'not chosen yet'}",
        f"Completed: {len(completed)} courses ({done_credits:g} credits in the curriculum)",
        f"Credit limits per term: {tc.get('min', 12)}-{tc.get('max', 17)}",
        f"Preferences: no classes before {prefs.get('avoid_before') or 'none'}; days kept free: {', '.join(prefs.get('avoid_days', [])) or 'none'}; ignore prerequisites: {bool(prefs.get('ignore_prereqs'))}",
        f"Wishlist: {', '.join(wishlist) or 'empty'}",
        f"Offerings loaded: {len(offerings)} sections",
    ]
    return "\n".join(lines)


def _advisor_tools():
    req_path, wl_path = requirements_path(), wishlist_path()

    def load():
        req, off = load_data(req_path, OFFERINGS_PATH)
        st = _program_structure(req)
        if st and req.get("catalog"):            # same categories / required flags as the pages show
            req = structure.overlay(req, st)
        return req, off

    def curriculum_status(_args):
        req, off = load()
        offered = {s["code"] for s in off}
        completed = set(req.get("completed", []))
        catalog = req.get("catalog", [])
        remaining, electives = [], []
        for c in catalog:
            if c["code"] in completed:
                continue
            miss = missing_prereqs(c["code"], req)
            if c.get("required"):
                status = "blocked" if miss else ("not_offered" if c["code"] not in offered else "available")
                item = {"code": c["code"], "name": c.get("name"), "credits": c.get("credits"), "status": status}
                if miss:
                    item["missing_prereqs"] = miss
                if c.get("plan_year") and c.get("plan_term"):
                    item["sample_plan"] = f"Year {c['plan_year']} {c['plan_term']}"
                remaining.append(item)
            elif c["code"] in offered:
                electives.append({"code": c["code"], "name": c.get("name"), "credits": c.get("credits"),
                                  **({"missing_prereqs": miss} if miss else {})})
        order = {"available": 0, "blocked": 1, "not_offered": 2}
        remaining.sort(key=lambda x: (order[x["status"]], x.get("sample_plan", "zz")))
        done_credits = sum(float(c["credits"]) for c in catalog if c["code"] in completed)
        return {
            "program": req.get("program"), "completed_count": len(completed),
            "credits_completed_in_curriculum": done_credits,
            "required_remaining": remaining, "offered_electives": electives[:30],
            "open_elective_slots": len(req.get("elective_slots", [])),
        }

    def search(args):
        req, off = load()
        counts, seats, mine = _wishlist_counts(), _seat_totals(off), set(load_wishlist(wl_path))
        catalog = {c["code"] for c in req.get("catalog", [])}
        only = args.get("only_in_curriculum", True) and bool(catalog)
        q = str(args.get("query") or "").strip().lower()
        code = str(args.get("code") or "").strip().upper()
        avoid = set(args.get("avoid_days") or [])
        after, before = args.get("starts_after") or "", args.get("ends_before") or ""
        out = []
        for s in off:
            if only and s["code"] not in catalog:
                continue
            if code and s["code"].replace(" ", "") != code.replace(" ", ""):
                continue
            if q and q not in f"{s['code']} {s.get('title', '')} {s.get('instructor', '')}".lower():
                continue
            if avoid & set(s.get("days") or []):
                continue
            if not s.get("online") and s.get("start"):
                if after and s["start"] < after:
                    continue
                if before and s["end"] > before:
                    continue
            out.append(_sec_brief(s, _demand(s["code"], counts, seats, mine)))
        limit = max(1, min(int(args.get("limit") or 15), 30))
        return {"matches": len(out), "sections": out[:limit]}

    def wishlist_status(_args):
        req, off = load()
        wl = load_wishlist(wl_path)
        offered = {s["code"] for s in off}
        counts, seats, mine = _wishlist_counts(), _seat_totals(off), set(wl)
        items = []
        for c in wl:
            miss = missing_prereqs(c, req) if not prereqs_met(c, req) else []
            status = "blocked" if miss else ("not_offered" if c not in offered else "ok")
            d = _demand(c, counts, seats, mine)
            items.append({"code": c, "status": status, **({"missing_prereqs": miss} if miss else {}),
                          "other_students_wishlisting": d["others"], "demand": d["level"]})
        return {"wishlist": items}

    def add(args):
        _, off = load()
        offered = {s["code"] for s in off}
        wl = load_wishlist(wl_path)
        added, skipped = [], []
        for raw in args.get("codes") or []:
            m = CODE_RE.fullmatch(str(raw).strip())
            code = f"{m.group(1).upper()} {m.group(2).upper()}" if m else str(raw).strip()
            if code not in offered:
                skipped.append(f"{code} (not offered this term)")
            elif code in wl:
                skipped.append(f"{code} (already on the wishlist)")
            else:
                wl.append(code)
                added.append(code)
        save_wishlist(wl, wl_path)
        res = {"added": added, "skipped": skipped, "wishlist": wl}
        if added:
            res["summary"] = "Added to your wishlist: " + ", ".join(added)
        return res

    def remove(args):
        wl = load_wishlist(wl_path)
        gone = []
        for raw in args.get("codes") or []:
            m = CODE_RE.fullmatch(str(raw).strip())
            code = f"{m.group(1).upper()} {m.group(2).upper()}" if m else str(raw).strip()
            if code in wl:
                wl.remove(code)
                gone.append(code)
        save_wishlist(wl, wl_path)
        res = {"removed": gone, "wishlist": wl}
        if gone:
            res["summary"] = "Removed from your wishlist: " + ", ".join(gone)
        return res

    def set_prefs(args):
        req, _ = load()
        prefs = req.setdefault("preferences", {"avoid_before": "", "avoid_days": [], "priority_courses": [], "ignore_prereqs": False})
        tc = req.setdefault("target_credits", {"min": 12, "max": 17})
        changes = []
        if "avoid_before" in args:
            v = str(args["avoid_before"] or "").strip()
            if v and not _TIME_RE.match(v):
                return {"error": "avoid_before must be HH:MM, e.g. 10:00"}
            v = f"{int(v.split(':')[0]):02d}:{v.split(':')[1]}" if v else ""
            prefs["avoid_before"] = v
            changes.append(f"no classes before {v}" if v else "no earliest-start limit")
        if "avoid_days" in args:
            days = [d for d in _VALID_DAYS if d in (args["avoid_days"] or [])]
            prefs["avoid_days"] = days
            changes.append("keeping " + "/".join(days) + " free" if days else "no days kept free")
        if "ignore_prereqs" in args:
            prefs["ignore_prereqs"] = bool(args["ignore_prereqs"])
            changes.append("ignoring prerequisites" if prefs["ignore_prereqs"] else "prerequisites enforced")
        if "min_credits" in args or "max_credits" in args:
            lo = int(args.get("min_credits", tc.get("min", 12)))
            hi = int(args.get("max_credits", tc.get("max", 17)))
            if not (0 <= lo <= hi <= 30):
                return {"error": "Credit limits need 0 <= min <= max <= 30."}
            tc["min"], tc["max"] = lo, hi
            changes.append(f"credit range {lo}-{hi}")
        with open(req_path, "w") as f:
            json.dump(req, f, indent=2)
        return {"preferences": prefs, "target_credits": tc,
                "summary": "Updated preferences: " + "; ".join(changes) if changes else None}

    def best_plans(args):
        req, off = load()
        wl = load_wishlist(wl_path)
        plans_, blocked_req, blocked_wl, no_sections, total, exhausted = enumerate_plans(req, off, wl, limit=50)
        n = max(1, min(int(args.get("limit") or 3), 5))
        out = []
        for i, p in enumerate(plans_[:n], 1):
            out.append({
                "plan": i, "total_credits": p["total_credits"], "meets_min_credits": p["meets_min_credits"],
                "days_on_campus": p["days_on_campus"], "earliest_start": _hhmm(p["earliest_start"]),
                "waiting_gap_minutes": round(p["gap_minutes"]),
                "wishlist_not_in_plan": p["unmet_wishlist"],
                "sections": [_sec_brief(s) for s in p["sections"]],
            })
        return {
            "wishlist_size": len(wl), "valid_plans_found": total, "search_complete": exhausted,
            "plans": out, "blocked_wishlist": blocked_wl, "wishlist_without_sections": no_sections,
            "note": "Plans are ranked best first: fewest wishlist courses left out, then credit fit, days on campus, waiting time.",
        }


    # ---- read-only tools for the newer features: they compute, they never write ----

    def _grades_arg(args):
        out = {}
        for item in args.get("grades") or []:
            if isinstance(item, dict) and item.get("code"):
                out[str(item["code"]).strip().upper()] = item.get("grade")
        return out

    def get_gpa(_args):
        req, _ = load()
        entries, unknown, total = _gpa_summary(req)
        return {
            "cumulative_gpa": total["gpa"], "gpa_credits": total["gpa_credits"], "quality_points": total["quality_points"],
            "credits_attempted": total["attempted"], "credits_earned": total["earned"],
            "courses_without_a_grade": [e["code"] for e in entries if not e["grade"]],
            "completed_courses_with_unknown_credits": unknown,
            "by_semester": [{"semester": r["semester"], "gpa": r["gpa"], "cumulative_gpa": r["cumulative_gpa"]} for r in gpa.by_semester(entries)],
            "grades": {e["code"]: e["grade"] for e in entries if e["grade"]},
            "scale_note": "Standard 4.0 scale assumed (A=4.0 ... F=0.0); P, NP, W, I, AU are excluded from GPA. Not verified against AUPP's official scale.",
        }

    def gpa_what_if(args):
        req, _ = load()
        entries, _unk, _tot = _gpa_summary(req)
        planned, source = _planned_courses()
        if not planned:
            return {"error": "The student has no planned courses yet (empty wishlist or no valid plan)."}
        default = gpa.normalize_grade(args.get("default_grade"))
        chosen = {}
        for code, g in _grades_arg(args).items():
            ng = gpa.normalize_grade(g)
            if not ng:
                return {"error": f"'{g}' isn't a grade. Use one of: {', '.join(gpa.grade_options())}."}
            chosen[code] = ng
        rows = []
        for c in planned:
            g = chosen.get(c["code"].upper()) or default
            if g:
                rows.append({"credits": c["credits"], "grade": g})
        if not rows:
            return {"error": "Give grades for some planned courses (or a default_grade).",
                    "planned_courses": [{"code": c["code"], "credits": c["credits"]} for c in planned]}
        res = gpa.what_if(entries, rows)
        res["planned_courses_used"] = [{"code": c["code"], "credits": c["credits"], "grade": chosen.get(c["code"].upper()) or default or None} for c in planned]
        res["plan_source"] = "student's active plan" if source == "active" else "best-ranked plan"
        return res

    def gpa_target(args):
        req, _ = load()
        entries, _unk, _tot = _gpa_summary(req)
        credits = args.get("credits")
        if credits in (None, ""):
            planned, _src = _planned_courses()
            credits = sum(float(c["credits"] or 0) for c in planned) or 15
        return gpa.required_average(entries, credits, args.get("target_gpa"))

    def get_roadmap(args):
        st = _load_roadmap_settings()
        for k in ("max_credits", "include_summer", "same_season"):
            if args.get(k) is not None:
                st[k] = args[k]
        if args.get("start_term"):
            if not roadmap.parse_term(args["start_term"]):
                return {"error": "start_term should look like 'Fall 2026'."}
            st["start_term"] = str(args["start_term"]).title()
        try:
            st["max_credits"] = float(st["max_credits"]) if st["max_credits"] else None
        except (TypeError, ValueError):
            return {"error": "max_credits must be a number."}
        pay = _roadmap_payload(st)
        if not pay["has_curriculum"]:
            return {"error": "The student has no curriculum yet, so there is nothing to plan."}
        road = pay["roadmap"]
        out = {
            "graduation_term": road["graduation_term"], "terms_remaining": len(road["terms"]), "start_term": road["start_term"],
            "remaining_credits": road["remaining_credits"], "max_credits_per_term": road["max_credits"],
            "terms": [{"term": t["label"], "credits": t["credits"], "warnings": t["warnings"],
                       "courses": [(c["code"] or "Elective slot") + ("" if not c["warnings"] else " (" + "; ".join(c["warnings"]) + ")") for c in t["courses"]]}
                      for t in road["terms"]],
            "risks": [r["text"] for r in road["risks"]],
            "not_placed": [u["code"] or u["name"] for u in road["unplaced"]],
            "accuracy_note": (f"{road['real_offerings_term']} is checked against real offerings; later terms are projections from the sample plan and prerequisites, not from published offerings."
                              if road["real_offerings_term"] else "Every term is a projection from the sample plan and prerequisites; no real offerings were used."),
            "student_hand_placed_courses": len(st["overrides"]),
        }
        target = args.get("graduate_by")
        if target:
            tk = roadmap.term_sort_key(target)
            if tk is None:
                return {"error": "graduate_by should look like 'Spring 2028'."}
            grad = road["graduation_term"]
            ok = grad is not None and roadmap.term_sort_key(grad) <= tk
            out["graduate_by"] = {"target": str(target).title(), "feasible_as_planned": ok, "projected_graduation": grad}
            if not ok and not st["include_summer"] and grad is not None:
                alt = _roadmap_payload(dict(st, include_summer=True))["roadmap"]["graduation_term"]
                out["graduate_by"]["with_summer_terms"] = {"graduation_term": alt,
                                                          "feasible": alt is not None and roadmap.term_sort_key(alt) <= tk}
        return out

    def get_progress(_args):
        d = _dashboard_payload()
        if not d["has_curriculum"]:
            return {"error": "The student has no curriculum yet."}
        p = d["progress"]
        return {
            "credits_done": p["done"], "credits_total": p["total"], "credits_remaining": p["remaining"], "percent_done": p["percent"],
            "by_category": [{"category": r["category"], "done": r["done"], "total": r["total"]} for r in p["rows"]],
            "required_courses_remaining": d["remaining_required"],
            "can_take_now": [{"code": c["code"], "name": c["name"], "credits": c["credits"], "offered_this_term": c["offered"]} for c in d["available"][:12]],
            "bottlenecks": [{"code": b["code"], "unlocks_courses": b["unlocks"], "can_take_now": b["available_now"]} for b in d["bottlenecks"][:6]],
            "estimated_graduation_term": d["graduation"]["term"], "graduation_risks": d["graduation"]["risks"],
            "gpa": d["gpa"]["value"], "planned_credits_this_term": d["planned"]["credits"],
        }

    return {
        "get_curriculum_status": curriculum_status, "search_offerings": search,
        "get_wishlist": wishlist_status, "add_to_wishlist": add, "remove_from_wishlist": remove,
        "set_preferences": set_prefs, "get_best_plans": best_plans,
        "get_gpa": get_gpa, "gpa_what_if": gpa_what_if, "gpa_target": gpa_target,
        "get_roadmap": get_roadmap, "get_progress": get_progress,
    }


@app.route("/api/ai/status")
def api_ai_status():
    return jsonify(ai.status())


@app.route("/api/ai/chat", methods=["POST"])
def api_ai_chat():
    st = ai.status()
    if not st["available"]:
        return jsonify({"error": "The AI advisor isn't set up yet.", "reason": st["reason"]}), 503
    try:
        messages = ai.clean_messages((request.get_json(silent=True) or {}).get("messages"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    wait = ai.rate_limited(g.user["id"])
    if wait:
        return jsonify({"error": f"That's a lot of questions for one hour. Try again in about {max(1, wait // 60)} minute(s)."}), 429
    if request.args.get("stream") == "1":
        return _ai_chat_stream(messages)
    try:
        result = ai.run_chat(messages, _advisor_context(), _advisor_tools())
    except Exception as e:
        return jsonify({"error": _ai_error_text(e)}), 502
    return jsonify(result)


def _ai_error_text(e):
    """Plain-language cause + how to fix it (same wording as `python3 ai_check.py`); never includes a key."""
    if isinstance(e, (ai.AIAuthenticationError, ai.AIRateLimitError, ai.AIConnectionError, ai.AIError)):
        what, fix = ai.explain_error(e)
        return f"{what} {fix}"
    app.logger.exception("AI chat failed")   # never echo secrets
    return "Something went wrong talking to the AI service. Run `python3 ai_check.py` in the terminal to find out why."


def _ai_chat_stream(messages):
    """Same as the JSON chat, but sent as one JSON object per line while it
    works, so the chat can show each step live ("Checking your GPA…"):
    step events from ai.run_chat, then {"type": "done", reply, actions, steps}
    or {"type": "error", "error"}. The AI runs in a worker thread that keeps
    this request's context (the tools need the logged-in student)."""
    events = queue.Queue()
    context_text, tools = _advisor_context(), _advisor_tools()
    user = g.user

    @copy_current_request_context
    def work():
        g.user = user      # `g` belongs to the app context, which the copied request context doesn't carry over
        try:
            result = ai.run_chat(messages, context_text, tools, on_event=events.put)
            events.put({"type": "done", **result})
        except Exception as e:
            events.put({"type": "error", "error": _ai_error_text(e)})
        finally:
            events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def generate():
        while True:
            ev = events.get()
            if ev is None:
                return
            yield json.dumps(ev, ensure_ascii=False, default=str) + "\n"

    return Response(generate(), mimetype="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Excel import API
# ---------------------------------------------------------------------------

@app.route("/api/import/upload", methods=["POST"])
def api_import_upload():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file uploaded"}), 400

    os.makedirs("data", exist_ok=True)
    file.save(pending_import_path())

    try:
        sheets = list_sheets(pending_import_path())
    except Exception as e:
        return jsonify({"error": f"Couldn't read that file as Excel: {e}"}), 400

    # Single-sheet workbooks skip straight to the column mapping; multi-sheet
    # ones (very common -- registrars often keep old terms/options in the
    # same file) need the student to pick the right sheet first.
    if len(sheets) == 1:
        return _sheet_response(sheets[0], sheets)
    return jsonify({"sheets": sheets, "needs_sheet_choice": True})


@app.route("/api/import/sheet", methods=["POST"])
def api_import_sheet():
    body = request.get_json(silent=True) or {}
    sheet_name = body.get("sheet_name")
    if not os.path.exists(pending_import_path()):
        return jsonify({"error": "No uploaded file. Upload one first."}), 400
    if not sheet_name:
        return jsonify({"error": "No sheet chosen."}), 400
    try:
        sheets = list_sheets(pending_import_path())
        return _sheet_response(sheet_name, sheets)
    except Exception as e:
        return jsonify({"error": f"Couldn't read that sheet: {e}"}), 400


def _sheet_response(sheet_name, sheets):
    headers = read_headers(pending_import_path(), sheet_name=sheet_name)
    mapping = guess_mapping(headers)
    return jsonify({
        "sheets": sheets,
        "chosen_sheet": sheet_name,
        "headers": headers,
        "guessed_mapping": mapping,
        "fields": TARGET_FIELDS,
    })


@app.route("/api/import/preview", methods=["POST"])
def api_import_preview():
    body = request.get_json(silent=True) or {}
    mapping = body.get("mapping", {})
    sheet_name = body.get("sheet_name", 0)
    if not os.path.exists(pending_import_path()):
        return jsonify({"error": "No uploaded file to preview. Upload one first."}), 400
    try:
        rows, errors = parse_with_mapping(pending_import_path(), mapping, sheet_name=sheet_name)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"rows": rows[:25], "total_rows": len(rows), "errors": errors[:25], "total_errors": len(errors)})


@app.route("/api/import/commit", methods=["POST"])
def api_import_commit():
    body = request.get_json(silent=True) or {}
    mapping = body.get("mapping", {})
    sheet_name = body.get("sheet_name", 0)
    if not os.path.exists(pending_import_path()):
        return jsonify({"error": "No uploaded file to import. Upload one first."}), 400
    try:
        rows, errors = parse_with_mapping(pending_import_path(), mapping, sheet_name=sheet_name)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    stats = _apply_offerings(rows, body.get("mode", "merge"))
    return jsonify({"ok": True, "imported": len(rows), "errors": len(errors), **stats})


@app.route("/api/import/parse-text", methods=["POST"])
def api_import_parse_text():
    """Fallback for when no Excel export is available -- paste schedule text instead."""
    body = request.get_json(silent=True) or {}
    text = body.get("text", "")
    parsed, unparsed = parse_schedule_text(text)
    return jsonify({"parsed": parsed, "unparsed": unparsed})


# ---------------------------------------------------------------------------
# Course offerings: update / manual entry
#
# Offerings are the registrar's data for the term, so they're shared by every
# account (unlike curriculum and wishlist, which are per-student). A section
# is identified by (course code, section number).
# ---------------------------------------------------------------------------

_VALID_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_TIME_RE = __import__("re").compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _load_offerings():
    try:
        with open(OFFERINGS_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def _save_offerings(rows):
    os.makedirs("data", exist_ok=True)
    with open(OFFERINGS_PATH, "w") as f:
        json.dump(rows, f, indent=2)


def _section_key(row):
    return (row["code"], str(row["section"]))


def _apply_offerings(incoming, mode):
    """mode "merge": add new sections, update ones whose details changed, and
    keep everything else. mode "replace": the incoming list becomes the whole
    set of offerings. Returns counts so the UI can say what happened."""
    existing = _load_offerings()
    if mode == "replace":
        old = {_section_key(r): r for r in existing}
        new = {_section_key(r): r for r in incoming}
        stats = {
            "added": len([k for k in new if k not in old]),
            "updated": len([k for k in new if k in old and old[k] != new[k]]),
            "removed": len([k for k in old if k not in new]),
        }
        _save_offerings(list(new.values()))
        stats["total"] = len(new)
        return stats

    merged = {_section_key(r): r for r in existing}
    added = updated = 0
    for row in incoming:
        k = _section_key(row)
        old = merged.get(k)
        if old is None:
            added += 1
        else:
            # An update that doesn't mention faculty / seat numbers (pasted
            # text never has them) shouldn't wipe what an earlier import knew.
            row = dict(row)
            for field in ("department", "seats_total", "seats_available",
                          "location", "start_date", "end_date", "prerequisites"):
                if row.get(field) in (None, ""):
                    row[field] = old.get(field)
            if row.get("risk") == "unknown" and not row.get("online"):
                row["risk"] = _risk_from_seats(row.get("seats_total"), row.get("seats_available"))
            if old != row:
                updated += 1
        merged[k] = row
    _save_offerings(list(merged.values()))
    return {"added": added, "updated": updated, "removed": 0, "total": len(merged)}


def _clean_section(raw):
    """Validate/normalize one hand-entered section into the same shape the
    Excel importer produces. Raises ValueError with a message for the user."""
    code_raw = str(raw.get("code") or "").strip()
    m = CODE_RE.fullmatch(code_raw)
    if not m:
        raise ValueError("Course code should look like 'COSC 121'.")
    code = f"{m.group(1).upper()} {m.group(2).upper()}"

    section = str(raw.get("section") or "").strip()
    if not section or len(section) > 8:
        raise ValueError("Section is required (e.g. 001 or A).")
    title = str(raw.get("title") or "").strip()
    if not title:
        raise ValueError("Title is required.")

    try:
        credits = float(raw.get("credits") if raw.get("credits") not in (None, "") else 3)
    except (TypeError, ValueError):
        raise ValueError("Credits must be a number.")
    if not 0 < credits <= 12:
        raise ValueError("Credits must be between 0 and 12.")

    online = bool(raw.get("online"))
    days = [d for d in _VALID_DAYS if d in (raw.get("days") or [])]
    start = str(raw.get("start") or "").strip()
    end = str(raw.get("end") or "").strip()
    if online:
        days, start, end = [], "", ""
    else:
        if not days:
            raise ValueError("Pick at least one meeting day, or tick Online / no fixed time.")
        if not (_TIME_RE.match(start) and _TIME_RE.match(end)):
            raise ValueError("Start and end times are required (e.g. 15:30).")
        pad = lambda t: f"{int(t.split(':')[0]):02d}:{t.split(':')[1]}"
        start, end = pad(start), pad(end)
        if start >= end:
            raise ValueError("End time must be after the start time.")

    def seat(v, label):
        if v in (None, ""):
            return None
        try:
            n = int(float(v))
        except (TypeError, ValueError):
            raise ValueError(f"{label} must be a whole number.")
        if n < 0:
            raise ValueError(f"{label} can't be negative.")
        return n

    seats_total = seat(raw.get("seats_total"), "Total seats")
    seats_available = seat(raw.get("seats_available"), "Seats available")
    if seats_total is not None and seats_available is not None and seats_available > seats_total:
        raise ValueError("Seats available can't be more than total seats.")

    start_date = _clean_iso_date(raw.get("start_date"), "Start date")
    end_date = _clean_iso_date(raw.get("end_date"), "End date")
    if start_date and end_date and end_date < start_date:
        raise ValueError("The end date can't be before the start date.")

    location = str(raw.get("location") or "").strip()[:80]
    if location.upper() in ("TBD", "TBA", "N/A", "NA", "-", "—"):
        location = ""

    return {
        "code": code,
        "section": section,
        "title": title,
        "days": days,
        "start": start or None,
        "end": end or None,
        "credits": credits,
        "instructor": str(raw.get("instructor") or "").strip(),
        "seats_total": seats_total,
        "seats_available": seats_available,
        "risk": "unknown" if online else _risk_from_seats(seats_total, seats_available),
        "online": online,
        "department": (str(raw.get("department") or "").strip().upper() or None),
        "location": location or None,
        "start_date": start_date,
        "end_date": end_date,
        "prerequisites": _clean_prereq_list(raw.get("prerequisites")),
    }


def _clean_prereq_list(v):
    """A list (or comma text) of prerequisite codes/notes -> a tidy list of short strings."""
    if isinstance(v, str):
        v = excel_importer.parse_prerequisites(v)
    return [str(p).strip()[:40] for p in (v or []) if str(p).strip()][:12]


def _clean_iso_date(v, label="Date"):
    """'' / None -> None; a valid YYYY-MM-DD -> itself; anything else raises."""
    if v in (None, ""):
        return None
    try:
        return datetime.strptime(str(v).strip()[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise ValueError(f"{label} must look like 2026-08-17.")


@app.route("/api/offerings/apply", methods=["POST"])
def api_offerings_apply():
    """Save already-parsed rows (e.g. from the paste importer)."""
    body = request.get_json(silent=True) or {}
    rows = []
    for raw in body.get("rows", []):
        try:
            rows.append(_clean_section(raw))
        except ValueError:
            continue  # pasted rows the parser couldn't fully read are skipped
    if not rows:
        return jsonify({"error": "No usable rows to save."}), 400
    return jsonify({"ok": True, **_apply_offerings(rows, body.get("mode", "merge"))})


@app.route("/api/offerings/section", methods=["POST"])
def api_offerings_section():
    """Add a section by hand, or edit one. `original` ({code, section}) is the
    section being edited, so changing its code/section number renames it
    instead of leaving a stale copy behind."""
    body = request.get_json(silent=True) or {}
    try:
        row = _clean_section(body.get("section") or {})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    rows = _load_offerings()
    orig = body.get("original") or {}
    orig_key = (orig.get("code"), str(orig.get("section"))) if orig.get("code") else None
    new_key = _section_key(row)
    if new_key != orig_key and any(_section_key(r) == new_key for r in rows):
        return jsonify({"error": f"{row['code']} section {row['section']} already exists — edit that one instead."}), 400

    replaced = False
    for i, r in enumerate(rows):
        if _section_key(r) == (orig_key or new_key):
            rows[i] = row
            replaced = True
            break
    if not replaced:
        rows.append(row)
    _save_offerings(rows)
    return jsonify({"ok": True, "section": row, "updated": replaced})


@app.route("/api/offerings/delete", methods=["POST"])
def api_offerings_delete():
    body = request.get_json(silent=True) or {}
    key = (body.get("code"), str(body.get("section")))
    rows = _load_offerings()
    kept = [r for r in rows if _section_key(r) != key]
    if len(kept) == len(rows):
        return jsonify({"error": "That section wasn't found."}), 404
    _save_offerings(kept)
    return jsonify({"ok": True})


if __name__ == "__main__":
    # Port 5000 collides with macOS's AirPlay Receiver (Monterey+), which
    # answers on it and returns a 403 -- 5050 avoids that entirely.
    # Debug mode (auto-reload + the in-browser debugger) is OFF unless you ask
    # for it:  FLASK_DEBUG=1 python3 app.py
    debug = os.environ.get("FLASK_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")
    app.run(debug=debug, port=int(os.environ.get("PORT", "5050")))
