# Registration Planner

A registration-planning tool for university students: instead of finding
out a course is full or a prerequisite is missing *during* registration,
this generates several complete, non-conflicting registration plans ahead
of time from (1) the courses you still need and (2) a wishlist of courses
you're interested in — plus backup sections for anything likely to fill
up.

It's built to work for **any university**, not just one school's system:
course data comes in through a flexible Excel importer (you map the
columns yourself, so any registrar sheet's layout works) and a manual
curriculum entry page, rather than anything hardcoded to one system's
format. It does not log in to or scrape any registration system directly.

## Quick start

```bash
pip install -r requirements.txt     # flask, pandas, openpyxl, anthropic
python3 app.py
```

Open http://127.0.0.1:5050. There's sample data pre-loaded so the app
isn't empty on first run — replace it with your real courses via the
**Import Courses** and **Curriculum** pages.

(Port 5050, not the more usual 5000 — on macOS Monterey and later, 5000 is
taken by AirPlay Receiver and you'll get a confusing "403 access denied"
from your browser instead of a real error. If you'd rather use 5000, turn
off AirPlay Receiver in System Settings > General > AirDrop & Handoff, or
just change the port back in `app.py`'s last line.)

To see the planner's reasoning in your terminal instead of the browser:

```bash
python3 scheduler.py
```

## Pages

- **Dashboard** (`/`): degree progress ring (credits done / left), progress by category,
  current GPA, this term's planned credits, estimated graduation term (from the
  roadmap), the required courses you can take now, and a **bottleneck** list (courses
  that the most other required courses are waiting on). A new account sees a short
  set-up checklist instead.
- **Plan** (`/plan`): the ranked schedules for your wishlist. **Pin to compare** keeps
  up to 3 candidates; **Make this my active plan** marks the one you chose (the Plan page
  opens on it and the GPA what-if uses it). The calendar (.ics) and PDF exports work on
  whichever plan is on screen.
- **Compare** (`/compare`): pinned plans in columns: credits, days on campus, earliest
  start, latest end, longest gap, total waiting, wishlist left out, seat risk, a mini
  weekly timetable. The best value in each row is starred with the reason. Rows where
  every plan ties get no star, and seat risk is only compared when seat numbers were
  imported (the current sheet has none, so it says so instead of guessing).
- **Roadmap** (`/roadmap`): every remaining required course and open elective slot placed
  in a semester until graduation. Prerequisites always come in an earlier term, terms stay
  under your credit limit, and the sample plan's order is preferred. Drag a course to
  another term (or use its **Move to** menu): moves are never blocked, they show warnings
  (prerequisite order, over the credit limit, no sections this term). Only the first term
  can be checked against real offerings; **later terms are projections**. Settings: first
  term, max credits per term, include Summer terms, keep courses in their sample-plan season.
  Your settings and hand-placed courses are saved in `data/users/<id>/roadmap.json`.
- **GPA** (`/gpa`): enter a grade for each completed course (saved in your own
  `degree_requirements.json` as an optional `grades` map; old files without it
  still load). Shows cumulative GPA, GPA by semester, credits attempted vs
  earned, a "what if I get these grades this term" calculator for your current
  plan, and "what average do I need for a target GPA". The 4.0 scale is an
  **assumption** (A 4.0 ... F 0.0, no A+) kept in one place, `GRADE_SCALE` in
  `gpa.py`; check it against AUPP's real scale. P, NP, W, I and AU are kept out
  of the GPA. Retakes aren't handled (every completed course counts once).

Where the logic lives (all pure Python, unit-tested): `gpa.py`, `compare.py`,
`roadmap.py`, `progress.py`. `app.py` only wires them to routes.

Per-student files in `data/users/<id>/`: `degree_requirements.json` (curriculum, completed,
grades), `wishlist.json`, `plan_choices.json` (pinned + active plan), `roadmap.json`.

## Tests

```bash
python3 -m unittest
```

Runs everything in `tests/` with the standard library only: GPA maths, plan-comparison
metrics, roadmap/prerequisite ordering, progress/bottlenecks, and end-to-end API checks
(permissions, grades, pins, roadmap moves, AI tools with a fake model). The API tests use a
throw-away temp folder, never your `data/`, and are skipped automatically if Flask isn't
installed for the Python you run them with (run them with the same Python you start the app with).

## AI advisor (optional, can be free)

The **Ask AI** button (bottom-right on every page) opens a chat that knows
your curriculum, completed courses and this term's offerings. It can answer
"what should I take next?", turn "no classes before 10, keep Fridays free, I
want ITM 360" into real wishlist/preference changes, and explain why a plan
ranks first. It needs an AI model, chosen with environment variables in the
terminal that runs the app (nothing is stored in code or data files):

**1. Free and private: Ollama on your own computer**

```bash
# install Ollama from https://ollama.com, then:
ollama pull llama3.1
export AI_BASE_URL="http://localhost:11434/v1"
export AI_MODEL="llama3.1"
python3 app.py
```

**2. Free online tier: any OpenAI-compatible service (e.g. Google Gemini)**

```bash
export AI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai"
export AI_API_KEY="key from aistudio.google.com"
export AI_MODEL="gemini-3.8-flash"
python3 app.py
```

**3. Claude API (paid, best answers)**

```bash
pip install anthropic
export ANTHROPIC_API_KEY="your-key"
python3 app.py
```

The advisor can also answer from your real numbers (read-only tools: `get_gpa`,
`gpa_what_if`, `gpa_target`, `get_roadmap`, `get_progress`), e.g. "what do I need this
term to reach a 3.8?" or "can I graduate by Spring 2028?". It cannot enter or change
grades. These tools are covered by tests with a *fake* model; they haven't been tried
against a real Gemini/Ollama/Claude model yet.

Notes: small free models are weaker at looking things up and may make
mistakes, so check anything important on the Plan page. With an online
service, your curriculum and course questions are sent to that provider.
Each account is limited to 25 messages per hour. Without a model configured
the rest of the app works exactly the same and the chat panel shows these
setup steps.

## How it works

This is a constraint-satisfaction problem. Every course you still need is
a "slot" that must be filled by exactly one *section* (a specific time
slot) such that no two chosen sections overlap in time, you're within
your credit limit, and every prerequisite is already completed.

There are two kinds of slots:
- **Required** — from your Curriculum page. The planner always tries to
  schedule every one of these.
- **Wishlist** — courses YOU chose while browsing the catalog. The
  planner fits in as many of these as it can without breaking the
  required courses or your credit limit.

`scheduler.py` solves this with backtracking search: required slots are
tried before wishlist slots, and within each group both the slot order
and each slot's candidate sections are shuffled, so running the search
several times surfaces genuinely different valid schedules — that's how
the app produces Plan A / B / C / ... instead of just one answer. If
committing to a section makes a later required course unschedulable, the
search backtracks and tries a different section rather than just taking
the first thing that fits.

For every scheduled course, the planner also checks whether another
section of that same course would *still* fit the rest of the plan
without a conflict — that's the "if this fills up, try this instead"
backup list. Sections already flagged as full (zero seats available) are
excluded from scheduling entirely and instead show up as an "unmet
required course" warning, which is the signal that you need to watch
that course closely or contact your advisor.

## The older pages in more detail

**Plan** — the generated weekly-timetable plans, with a summary and
backup-section list per plan. Switch between **Week** (days as columns,
coloured blocks with code, time and room) and **List** views; the page and
the PDF export print cleanly.

**Courses (Browse & Wishlist)** — every imported course section in a filterable
table (search, day, time of day, instructor, seat status). Add anything
you're interested in to your wishlist from here.

**Curriculum** — manage completed courses, required remaining courses,
prerequisites, your credit load range, and scheduling preferences (e.g.
"no classes before 8am"). This replaces hand-editing a JSON file, since
most registration systems don't let you export your curriculum/degree
audit as a file.

At the top of the page there's a **paste-from-curriculum-view** box: copy
the table straight out of your school's on-screen curriculum view (e.g.
Rean) — tab-separated rows of Code / Name / Category / Sub-Category /
Credits / Requisites — paste it in, and click Parse. It recognizes
`Major` and `Core/Major` (or anything literally marked `(Required)`) as
required courses, treats `Electives`/`Major Electives`/bare `General
Education` as optional (not auto-added — add those via Browse & Wishlist
instead if you want them), and reads `h: X, Y` / `s: X, Y` prefixes as
hard (blocking) vs. soft prerequisites. This only previews — nothing is
added until you uncheck anything you don't want and click Apply, and
nothing is saved to disk until you click **Save curriculum** at the
bottom of the page. Multiple pasted tables (e.g. a core block and an
electives block copied separately) are handled fine in one paste.

**Import Courses** — upload the term's course offerings as an Excel file.
Works with *any* column layout: it reads the header row, guesses which
column is which (course code, section, days, times or a combined
"meeting time" column, credits, instructor, seats), and lets you fix the
guess before anything is saved. If the workbook has more than one sheet
(common when a registrar keeps past terms in the same file), you're asked
to pick the right one first. It understands common day formats (`MWF`,
`TR`/`TTh`, `Mon/Wed/Fri`, full names), both 12-hour and 24-hour times,
combined day+time cells like `(E) 3:30PM-5:00PM MW`, cross-listed course
codes joined with `/` (e.g. `COSC 111/CSCI 111`, which becomes two linked
rows), and marks online/async sections (no fixed meeting time) so the
planner and calendar handle them separately instead of crashing on them.
If there's no Excel export available, there's a "paste schedule text"
fallback at the bottom of the page — copy the on-screen schedule and
paste it in; it's best-effort and you should double check what it
parsed.

## Adapting this to a real term

1. **Import Courses**: upload your registrar's actual Excel sheet. Check
   the column mapping (it auto-guesses, but verify), preview the parsed
   rows, and confirm the import. If a row shows up as an error, that's
   usually a day or time format the importer hasn't seen yet — worth
   showing in your presentation as a real "adapting to an unfamiliar data
   format" example.
2. **Curriculum**: enter your completed courses, remaining required
   courses, and prerequisites (from whatever your school's system shows
   on screen, since most don't export this). Set your credit range and
   any scheduling preferences.
3. **Courses**: filter for electives or courses you're
   interested in and add them to your wishlist.
4. **Plan**: see your generated options, pin a few to **Compare**, and
   choose an active plan. Check **Roadmap** and **Dashboard** for the bigger picture.

## Project structure

```
app.py                       Flask routes (pages + JSON API) and the AI tool implementations
scheduler.py                 Constraint-satisfaction plan generator
gpa.py                       GPA maths and the grade scale (GRADE_SCALE: an assumption, edit it)
compare.py                   Plan comparison metrics + "best in row" logic
roadmap.py                   Graduation roadmap (prerequisite-aware, credit-limited)
progress.py                  Degree progress, courses available now, bottlenecks
programs.py                  Sample course plans per major
ai.py                        AI advisor (providers, tool schemas, chat loop)
auth.py                      Accounts
excel_importer.py            Flexible Excel -> normalized course data
parser.py, curriculum_parser.py   Paste-text fallbacks
data/                        Shared data (offerings, calendar, program plans, users.json)
data/users/<id>/             One student's files (curriculum+grades, wishlist, plan_choices, roadmap)
templates/                   base layout + one template per page
static/style.css             All styling (design tokens at the top)
static/common.js             Shared helpers: escapeHtml, weekly timetable renderer, .ics download, nav menu
static/*.js                  One script per page
tests/                       python3 -m unittest
```

## Ideas for extending it further

- Real offerings for future terms (the roadmap can only project them today).
- A "lock this section in" toggle so the solver treats one choice as
  fixed and only searches for the rest around it.
- Per-user accounts, so this could actually serve a whole class or
  department instead of just one student's local copy — good material
  for the "usefulness to others" part of the idea/business criterion.
- OCR support for pasted screenshots (currently text-paste only).
