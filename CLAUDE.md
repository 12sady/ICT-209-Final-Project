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
- New logic modules (pure, unit-tested): `gpa.py`, `compare.py`, `roadmap.py`, `progress.py`, `grade_report.py`, `structure.py`.

## What exists
- Curriculum page with admin-published sample plans for 16 majors; each student gets an editable copy.
- Browse + wishlist + planner (finds valid schedules; ranks by fewest left-out courses, credits, days, gaps).
- Plan page exports ICS: one recurring weekly VEVENT per class with location, Asia/Phnom_Penh,
  breaks as EXDATE, dates from section → academic calendar → fallback.
- AI advisor ("Ask AI" drawer): tool-use loop whose tools only touch the logged-in student's data;
  25 msgs/hour/account. Providers via env vars only (never put keys in code or data files):
  `AI_BASE_URL` + `AI_MODEL` (+ `AI_API_KEY`) for Ollama/Gemini
  (`https://generativelanguage.googleapis.com/v1beta/openai`, recommended model `gemini-3.6-flash`;
  `gemini-3.8-flash` timed out for the user and may be slow),
  or `ANTHROPIC_API_KEY` for Claude. Gemini 3 needs its tool-call "thought signature" (`extra_content`)
  echoed back unchanged or it returns HTTP 400: `OpenAICompatProvider.step` stores and re-sends it
  (`GeminiThoughtSignatureTest`). Not yet confirmed end to end with a full real conversation.
  `ai-key.sh` and `.env` are git-ignored for local keys: never commit or print them. `envfile.py` loads `.env`
  (next to app.py) at startup in app.py and ai_check.py, without overriding variables already set; works on Windows
  (the user is on Windows PowerShell, where ai-key.sh's `export` doesn't work). `.env.example` is the shareable template.
  User now runs Groq (`https://api.groq.com/openai/v1`, model `openai/gpt-oss-120b`; llama-3.3-70b isn't available to
  their key). Groq's Cloudflare blocks Python's default User-Agent (403 "error code: 1010"), so `ai.USER_AGENT` is sent;
  403 1010 -> AIConnectionError, 401 -> AIAuthenticationError. Free tier ~8k tokens/min, and one question with a few
  tool rounds can exceed it: on 429 `_post` waits per Retry-After / x-ratelimit-reset-tokens (`retry_wait`, max 40 s
  total); TOOL_RESULT_LIMIT 4000 chars, MAX_MESSAGES 8; optional `AI_REASONING_EFFORT=low`. AI tools' `load()` applies
  the program-structure overlay too.

## Built since (all five planned features + AI tools are done)
- GPA (`gpa.py`, `/gpa`): grades in the student's requirements file as optional `grades` map;
  `GRADE_SCALE` is AUPP's (A- 3.67, B+ 3.33, B- 2.67...), confirmed against a real grade report: every term GPA
  and the 411.03 total grade points match. C+/C-/D+ (2.33/1.67/1.33) follow the pattern but weren't on that report.
  P/NP/W/I/AU excluded.
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

- "Why this schedule?" (Plan page side card, `renderWhy` in static/plan.js): `scheduler.enumerate_plans(..., stats={})`
  fills an account of the CSP/backtracking search without changing results (`test_search_stats.py`): sections removed
  before search by reason (too_early / day_off / full, via `preference_reason`), search-tree steps, choices refused for
  time clash / over credits (counted in pass 2 only), up to 5 example clashing pairs, valid plans, most courses that fit.
  `/api/plans` returns it as `search` (+ max_credits, avoid_before, avoid_days). The card also explains the ranking
  rules and which rule puts the shown plan above/below its neighbour in best-fit order.
- Ask AI live steps: `ai.run_chat(..., on_event=)` emits thinking / tool / tool_done / wait events and returns `steps`
  (name, label from `TOOL_LABELS`, input, ok, preview) for the "How I got this" list. `POST /api/ai/chat?stream=1`
  streams NDJSON from a worker thread (`copy_current_request_context`; `g.user` must be set again inside the thread);
  without `stream=1` it's the old JSON reply. Provider `on_wait` reports rate-limit pauses.
- Header refresh (base.html + common.js + style.css end-of-file overrides): gradient 🎓 logo, page links (no icons) with
  active pill + gradient underline, avatar user button with dropdown (Signed in as / Student|Admin / Log out); on phones
  ☰/✕ toggle, 2-column link tiles and a user card. Below 1100px the name hides (avatar only). Status strip = chips from
  `GET /api/status` (progress from program structure or sample plan, program, sections, required left, wishlist).
- Ask AI look: gradient header with online dot (from /api/ai/status), welcome + 4 idea cards, avatar bubbles, animated
  steps, tool chips (`TOOL_CHIPS` in advisor.js), rounded auto-growing input.
- Program structure vs sample plan (`structure.py`, `data/program_structures.json`): the structure = graduation rules
  (credits per category + which courses count), the sample plan (`program_plans.json`) = suggested semester order only.
  Only `software-development` has a structure so far (courses from the user's SIS degree audit, 2023 cohort; targets
  GE 31 / Major 44 / Core/Major 27 / Electives 18 = 120 from aupp.edu.kh). Other programs are unchanged.
  `app._load_data()` overlays it on every read (`structure.overlay`): catalog categories/GE sub-groups from the
  structure, missing structure courses added, `required` = all-required category (list credits == target), or the
  plan's flag while a choice category is unfinished, else False. `structure.evaluate` caps each category at its
  target (extra not counted); Enrichment / uncategorised audit rows / courses not in the structure never count.
  Dashboard ring + Curriculum "Program structure" card + group headers use it; Roadmap still uses plan order.
- Grade report import (`grade_report.py`, card on the Curriculum page, `static/grade_import.js`):
  `POST /api/grade-report/preview` (multipart PDF, read in memory, never saved) -> rows matched to the catalog;
  `POST /api/grade-report/apply` marks picked passed courses completed + sets semester and grade. Reads pdfplumber
  word positions (plain text merges "B-" into the next line). Left column flows over all pages before the right one.
  RG = in progress (skipped), P = completed but not in GPA, "*" = repeat (latest attempt kept), codes can wrap
  ("ENGL 101" + "(ENR)"); unmatched courses get added to the catalog under "From grade report". Preview compares the
  report's Cumulative GPA with the app's. Real reports go in `private/` (git-ignored); tests use made-up positions.
- Curriculum "mark everything up to here" (`progress.courses_through`, `POST /api/curriculum/through`) and the admin
  demo student (`demo.py`, `POST /api/admin/demo-student`, button on the Import page).
- Registration-day sheet (`sheet.py`, `/registration-sheet`, `GET /api/registration-sheet`); academic calendar gained an
  optional `registration_date`.
- Advisor summary (`/advisor-summary`, `GET /api/advisor-summary`): composed from existing payloads (progress, GPA, roadmap, active plan).
- Print layouts (registration sheet, advisor summary, plan page) were checked as CSS + on-screen only, not in a real print preview.
- `python3 ai_check.py`: AI connection self-check (ping + one real read-only tool round trip on a temp empty student);
  `ai.explain_error` / `ai.scrub` give plain-language fixes and hide key-like text (used by the chat endpoint too).
  The user ran it against real Gemini (gemini-3.6-flash, AQ.-style key over the OpenAI route with a single Bearer header): ping and the
  get_progress tool round trip both passed. A full multi-turn chat in the app is still unconfirmed. Claude never runs it (it would need the key).

- Offerings now carry optional `prerequisites` (list; imported from a "Pre-requisite" column via `excel_importer.parse_prerequisites`,
  shown in Browse and editable in the manual section form). Display only: the scheduler still checks the student's own curriculum prereqs.
- Demo data is **Spring 2027** (IT undergraduate sheet, 224 sections, classes 11 Jan - 30 Apr 2027, breaks from the AUPP calendar PDF);
  Fall 2026 was removed on purpose. No rooms or seats yet (registrar gives rooms near enrolment day): Browse's demand badge
  (from wishlists) is the stand-in for seat pressure. Registration-opens date still unset.

- Course codes: computer science is `COSC` (never `CSCI`). The registrar sheet cross-lists some as "COSC 111/CSCI 111"; `excel_importer.normalize_code_prefix` maps CSCI -> COSC and keeps one row. HIST 131 is "World History from 1500 CE" (11 sample plans had a wrongly parsed title "Behavioral and Social Sciences", fixed). Students who already copied a plan keep their old titles until they press "Use this plan" again.

- The Import page has an optional, collapsed "Add prerequisites from Rean" card (paste a Rean curriculum table; `/api/curriculum/parse`, `curriculum_parser.py`). It is for prerequisites the degree audit lacks; courses it adds that are not on the audit show under "Not in program structure". Decision (Nov 2026): keep the grade-report import too (its cumulative GPA is the cross-check) alongside the degree-audit import and sample plans.

- Degree audit import (`degree_audit.py`, card on the Curriculum page, `static/audit_import.js`, `POST /api/degree-audit/preview|apply`):
  reads AUPP's SIS "Official Degree Audit" PDF by word positions (like the grade report; name/ID/date of birth never read). Columns
  Category | code | name | credits | semester | grade | earned; cells wrap (number on next line, year on next line, "(Required)").
  Category "M - Major" / "ME - Major Electives" / "GER - General Education (Required)" / "CM - Core/Major"; a BLANK category is a shaded
  row = not counted in the credit totals. Last page summary gives credits needed per category and a cross-check. Apply (re-reads the
  same upload, trusts nothing from the browser) rebuilds the curriculum from the audit, marks passed courses with semester + grade
  (RG = in progress, skipped), and stores the student's own structure as `audit_structure` in their requirements file. `_program_structure`
  prefers it over the program's official structure; PUT /api/curriculum carries it over; choosing a sample plan again drops it.
  SIS can leave out a course the school counts (shaded "-" row): `POST /api/degree-audit/move` + the panel in the Program structure card
  (`degree_audit.move_course`) move one course into a category; kept as `audit_moves` and re-applied on a new upload. PUT /api/curriculum
  always keeps the disk's `audit_structure`/`audit_moves` (a stale page can't undo them).
  The audit preview suggests where each shaded course counts (`degree_audit.suggest`, from the student's sample plan: General Education ->
  General Education, "(Compulsory)" elective -> Core/Major, other electives -> Major Electives, Major only if not full; the student's earlier
  choice wins); the user confirms with dropdowns and the choices are posted as `moves` on apply. A re-upload keeps courses added by hand.
  `structure.categories`: a category that lists fewer credits than it needs counts as all-required. Tested with made-up pages only
  (`tests/test_degree_audit.py`); checked once against the user's real audit in a scratch folder (totals matched: 120 / 25, GE 25 of 31).

- Never use `window.confirm()` in the frontend: the Claude desktop app's browser pane blocks pop-up dialogs, so it silently returns false and the button looks dead. Use `await askConfirm(message, okLabel)` from `static/common.js` (in-page dialog, Esc/backdrop cancel).

- Ask AI speed/errors (Nov 2026): snapshot in `_advisor_context` now holds progress, courses left, can-take-now, graduation estimate and GPA so most questions need no tool round; MAX_TOOL_ROUNDS 4; reasoning_effort defaults to "low" for Google/Groq hosts (AI_REASONING_EFFORT=off disables; a 400 about it is retried without); REQUEST_TIMEOUT 90 s (AITimeoutError); daily 429 quota is not retried (AIRateLimitError.daily); 503/529 = AIOverloadedError. `ai.HOWTO_GUIDE` (step-by-step "how do I upload / edit a course") is only added to the prompt when `wants_howto(messages)`; keep it in sync with the real page and button names. The chat itself cannot upload files or edit courses.

- In-progress courses (Nov 2026): `in_progress` list in the requirements file (audit RG rows, grade-report RG rows, or the Curriculum status "In progress"). They count as DONE for prerequisites (`scheduler._done_for_planning`), the roadmap, the dashboard "available / bottlenecks / remaining required" and the AI snapshot, but NOT for credits/GPA/progress ring. `_load_data` drops codes that are completed. `/api/courses` adds `mine` per section via `_course_statuses` (completed / in_progress / blocked / not_needed / available / not_in_curriculum + recommended, rank 0 roadmap next term, 1 required, 2 elective); the Courses page shows chips, hides completed + in-progress + not-needed by default and has a "Recommended" filter.

- Courses outside the degree audit (e.g. ICT 340) can still be taken as electives: `/api/courses` marks them `outside_ok` / `outside_blocked` using the registrar sheet's prerequisites (`_sheet_prereqs`, `_sheet_missing`; in-progress counts as done), and the wishlist status uses the same check. The sheet's prerequisites are otherwise display-only.

- Calendar export: one repeating weekly VEVENT per class (RRULE, EXDATE for breaks, stable UIDs so re-importing updates instead of duplicating) plus the academic calendar's `events` (holiday / deadline / exam / term / other, edited in the Import page calendar card, seeded from the Spring 2027 PDF) as all-day free-time events; deadlines get two VALARM reminders. POST body flags: `include_calendar` (default true), `dates_only`. No direct Google/Outlook add (would need OAuth); the Plan page has import instructions.

- Retakes (Nov 2026): a completed / in-progress course can still be wishlisted (the planner schedules it). Browse shows it with an "In progress now" / "Completed" chip, the button says "+ Add (retake)", the wishlist panel says "retake: taking it now / already completed", and the AI warns. Browse has a Status select (recommended / can take / in progress / completed / blocked / not needed) that overrides the hide checkboxes. Grade report import also remembers RG courses that are not in the curriculum yet (`grade_report.add_in_progress`, added under "From grade report").

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
