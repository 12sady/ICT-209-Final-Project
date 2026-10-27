# AUPP Registration Planner — project notes for Claude Code

Solo class project by Bunleng (BSAI student at AUPP). **No budget**: keep everything free
(no paid services; AI uses Ollama or Gemini free tier, Claude API optional).

## Stack and layout
- Flask + Jinja, plain JS (no build step). Run: `python3 app.py`.
- `app.py` — routes, calendar/ICS export, AI glue. `scheduler.py` — constraint-based planner.
  `programs.py` — sample course plans (load/clean/apply). `ai.py` — AI advisor (provider adapters).
  `auth.py` — accounts. `excel_importer.py`, `parser.py`, `curriculum_parser.py` — imports.
- Per-user data: `data/users/<id>/` (`degree_requirements.json`, `wishlist.json`).
  Shared data: `data/course_offerings.json`, `data/academic_calendar.json`,
  `data/program_plans.json`, `data/users.json`. Admin = first account (or `is_admin` flag);
  only admin may write offerings/calendar/plans (403 JSON otherwise).
- Frontend: `templates/*.html`, `static/*.js` (curriculum, browse, plan, compare, roadmap, gpa, dashboard,
  import, advisor, programs_admin, common), `static/style.css`.
- New logic modules (pure, unit-tested): `gpa.py`, `compare.py`, `roadmap.py`, `progress.py`.

## What exists
- Curriculum page with admin-published sample plans for 16 majors; each student gets an editable copy.
- Browse + wishlist + planner (finds valid schedules; ranks by fewest left-out courses, credits, days, gaps).
- Plan page exports ICS: one recurring weekly VEVENT per class with location, Asia/Phnom_Penh,
  breaks as EXDATE, dates from section → academic calendar → fallback.
- AI advisor ("Ask AI" drawer): tool-use loop whose tools only touch the logged-in student's data;
  25 msgs/hour/account. Providers via env vars only (never put keys in code or data files):
  `AI_BASE_URL` + `AI_MODEL` (+ `AI_API_KEY`) for Ollama/Gemini
  (`https://generativelanguage.googleapis.com/v1beta/openai`, model `gemini-3.8-flash`),
  or `ANTHROPIC_API_KEY` for Claude. The Gemini path has been tested with a fake server only,
  not yet against real Gemini.

## Built since (all five planned features + AI tools are done)
- GPA (`gpa.py`, `/gpa`): grades in the student's requirements file as optional `grades` map;
  grade scale is an ASSUMPTION (standard 4.0) in `GRADE_SCALE`; P/NP/W/I/AU excluded.
  `PUT /api/curriculum` always re-reads grades from disk so a stale Curriculum page can't wipe them.
- Compare (`compare.py`, `/compare`): per-student `plan_choices.json` = up to 3 pins + one active plan,
  stored as {code, section} ids and re-resolved against current offerings. Seat risk is only compared
  when every plan has seat data (the real sheet has none).
- Roadmap (`roadmap.py`, `/roadmap`): per-student `roadmap.json` (settings + hand-placed courses).
  Prereqs strictly earlier term, credit limit, sample-plan order, then longest chain. Moves are never
  refused, only warned. Only the first term is checked against real offerings; later terms are projections.
  Completed electives use up elective slots (`progress.open_slots`).
- Dashboard (`progress.py`, `/` is now the dashboard; the old Plan page moved to `/plan`).
- Design pass: nav with mobile Menu, contrast-checked colour tokens (course colours >= 4.5:1 with white),
  shared timetable renderer in `static/common.js` (`timetableHtml`) used by Plan and Compare, tables scroll
  inside `.table-wrap`, print CSS for the Plan page. Curriculum page: collapsible sample-plan/completed cards, search + status filter, sticky Save bar, cards instead of a table on phones; category groups collapse like the SIS degree audit. Import page: secondary cards are collapsed `<details>`. No dark mode (skipped on purpose).
- AI tools added (read-only): get_gpa, gpa_what_if, gpa_target, get_roadmap, get_progress. No tool writes grades.
  Tested with fake models only.
- Tests: `python3 -m unittest` (pure logic + Flask test-client API tests in a temp dir; API tests skip if
  Flask is missing). Flask lives under /usr/local/bin/python3 (3.13) on this machine, not the default python3.

- Curriculum "mark everything up to here" (`progress.courses_through`, `POST /api/curriculum/through`) and the admin
  demo student (`demo.py`, `POST /api/admin/demo-student`, button on the Import page).
- Registration-day sheet (`sheet.py`, `/registration-sheet`, `GET /api/registration-sheet`); academic calendar gained an
  optional `registration_date`.

## Ideas not done yet
- Retakes in GPA; real future-term offerings; seat data from the registrar; dark mode; admin-editable grade scale.

## Known data caveats
- Plans were parsed from PDFs automatically; Political Science (Dual) shows 128 credits vs 125 in source;
  three source PDFs repeat course codes (curriculum keeps the first); lighter-blue shade assumed = Major.

## Working notes
- Playwright is NOT installed here: test in the built-in browser pane against a scratch copy of the project
  (copy code, NOT `data/.flask_secret`; make test accounts) plus the unit/API tests. Never run against real `data/`.
- Git repo exists (commit after each fix; never push). `.gitignore` also excludes data/users.json and data/auth.json (password hashes).
- Run the scratch copy with `PORT=5051` so it never collides with the real app on 5050. Debug is off unless `FLASK_DEBUG=1`.
- Don't read or print `data/.flask_secret` or any API keys.
- `static/script.js.old-unused` and `.idea/` are not part of the app.
