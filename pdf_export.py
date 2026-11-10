"""
pdf_export.py
-------------
Builds a real PDF file of a registration plan (weekly timetable + course table), so "Export as PDF" is a
download that works in any browser. The old way opened a pop-up window and used the browser's print
dialog, which embedded browsers (like the Claude app's) block.

Uses fpdf2 (pure Python, free). Core PDF fonts only know Latin-1, so text is cleaned first.
"""

from datetime import datetime

from fpdf import FPDF

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
# Same order of colours as the web timetable, darker so white text stays readable on paper.
PALETTE = [(79, 70, 229), (13, 148, 136), (190, 70, 30), (126, 34, 206), (37, 99, 235), (180, 83, 9), (190, 24, 93), (21, 128, 61)]

_REPLACE = {"–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "·": "-", "•": "-", "…": "...", " ": " "}


def _t(value):
    """Text safe for the built-in PDF fonts."""
    s = "" if value is None else str(value)
    for a, b in _REPLACE.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def _minutes(hhmm):
    try:
        h, m = str(hhmm).split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _hm(minutes):
    return f"{minutes // 60}:{minutes % 60:02d}"


def _timetable(pdf, timed, colour, total_w=277.0, max_h=92.0):
    """Draw a Mon-Fri(+) timetable at the current position and move below it."""
    used_days = [d for d in DAYS if any(d in s["days"] for s in timed)]
    cols = [d for d in DAYS[:5]] + [d for d in DAYS[5:] if d in used_days]
    t0 = min(_minutes(s["start"]) for s in timed) // 60 * 60
    t1 = -(-max(_minutes(s["end"]) for s in timed) // 60) * 60
    hours = max(1, (t1 - t0) // 60)
    x0, y0 = pdf.l_margin, pdf.get_y()
    time_w = 14
    col_w = (total_w - time_w) / len(cols)
    head_h = 6
    row_h = min(11.0, max_h / hours)

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(240, 240, 245)
    pdf.set_draw_color(205, 205, 215)
    pdf.set_xy(x0, y0)
    pdf.cell(time_w, head_h, "", border=1, fill=True)
    for d in cols:
        pdf.cell(col_w, head_h, d, border=1, align="C", fill=True)
    gy = y0 + head_h
    pdf.set_font("Helvetica", "", 8)
    for i in range(hours):
        y = gy + i * row_h
        pdf.set_xy(x0, y)
        pdf.cell(time_w, row_h, _hm(t0 + i * 60), border=1, align="R")
        for j in range(len(cols)):
            pdf.set_xy(x0 + time_w + j * col_w, y)
            pdf.cell(col_w, row_h, "", border=1)
    for s in timed:
        a, b = _minutes(s["start"]), _minutes(s["end"])
        r, g, bl = colour[s.get("code")]
        for d in s["days"]:
            if d not in cols:
                continue
            x = x0 + time_w + cols.index(d) * col_w + 0.6
            y = gy + (a - t0) / 60 * row_h + 0.3
            h = max(4.0, (b - a) / 60 * row_h - 0.6)
            pdf.set_fill_color(r, g, bl)
            pdf.rect(x, y, col_w - 1.2, h, style="F")
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_xy(x + 1, y + 0.6)
            pdf.cell(col_w - 2.4, 3.6, _t(f"{s.get('code', '')}-{s.get('section', '')}"))
            pdf.set_font("Helvetica", "", 7)
            pdf.set_xy(x + 1, y + 4.1)
            pdf.cell(col_w - 2.4, 3.2, _t(f"{s['start']}-{s['end']}" + (f"  {s['location']}" if s.get("location") else "")))
    pdf.set_text_color(0, 0, 0)
    pdf.set_y(gy + hours * row_h + 4)


def _split_timed(sections):
    timed, untimed = [], []
    for s in sections:
        a, b = _minutes(s.get("start")), _minutes(s.get("end"))
        days = [d for d in (s.get("days") or []) if d in DAYS]
        (timed if (not s.get("online") and a is not None and b is not None and days) else untimed).append(s)
    return timed, untimed


def _fit(pdf, text, width):
    """Cut text with '...' so it fits the cell width (current font)."""
    text = _t(text)
    if pdf.get_string_width(text) <= width - 1.5:
        return text
    while text and pdf.get_string_width(text + "...") > width - 1.5:
        text = text[:-1]
    return text.rstrip() + "..."


def plan_pdf(sections, program="", term="", label="", unmet=None, generated=None):
    """Bytes of a one-or-two page A4 landscape PDF for the given plan sections (full section dicts)."""
    unmet = unmet or []
    timed, untimed = _split_timed(sections)

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(10, 10, 10)
    pdf.add_page()

    colour = {}
    for s in sections:
        colour.setdefault(s.get("code"), PALETTE[len(colour) % len(PALETTE)])

    # ---- heading ----
    credits = sum(float(s.get("credits") or 0) for s in sections)
    codes = len({s.get("code") for s in sections})
    pdf.set_font("Helvetica", "B", 17)
    pdf.cell(0, 8, _t(f"Registration plan {label}".strip() + (f" - {term}" if term else "")), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 5, _t(f"{program}   |   {codes} courses, {credits:g} credits"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    # ---- weekly timetable ----
    if timed:
        _timetable(pdf, timed, colour, total_w=277, max_h=92.0)

    # ---- course table ----
    widths = [22, 12, 78, 22, 32, 12, 24, 75]
    heads = ["Code", "Sec", "Title", "Days", "Time", "Cr", "Room", "Instructor"]
    if pdf.get_y() + 8 + 7 * min(len(sections), 3) > 196:
        pdf.add_page()
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(240, 240, 245)
    for w, h in zip(widths, heads):
        pdf.cell(w, 6, h, border=1, fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 9)
    for s in sections:
        online = s in untimed
        cells = [s.get("code", ""), s.get("section", ""), s.get("title", ""), "".join(d[:2] for d in s.get("days") or []),
                 "Online / TBA" if online else f"{s.get('start')} - {s.get('end')}", s.get("credits", ""),
                 s.get("location") or "", s.get("instructor") or ""]
        r, g, bl = colour[s.get("code")]
        for k, (w, c) in enumerate(zip(widths, cells)):
            if k == 0:
                pdf.set_text_color(r, g, bl)
                pdf.set_font("Helvetica", "B", 9)
            pdf.cell(w, 6.5, _fit(pdf, c, w), border=1)
            if k == 0:
                pdf.set_text_color(0, 0, 0)
                pdf.set_font("Helvetica", "", 9)
        pdf.ln()

    pdf.ln(3)
    pdf.set_font("Helvetica", "", 9)
    if unmet:
        pdf.multi_cell(0, 5, _t("Wishlist courses not in this plan: " + ", ".join(unmet)), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(110, 110, 110)
    stamp = (generated or datetime.now()).strftime("%d %b %Y")
    pdf.multi_cell(0, 4.5, _t(f"Made with AUPP Registration Planner on {stamp}. The planner only plans: register for these sections in AUPP's own "
                              "system and confirm with your advisor or the registrar."), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def _new_portrait():
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(12, 12, 12)
    pdf.add_page()
    return pdf


def _h2(pdf, text):
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(40, 40, 90)
    pdf.cell(0, 6, _t(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)


def _footer(pdf, generated):
    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(0, 4.5, _t(f"Made with AUPP Registration Planner{(' on ' + generated) if generated else ''}. The planner only plans: register in AUPP's own "
                              "system and confirm requirements with your advisor or the registrar."), new_x="LMARGIN", new_y="NEXT")


def sheet_pdf(d):
    """The registration-day sheet (payload of /api/registration-sheet): tick boxes, sections, backups, timetable."""
    pdf = _new_portrait()
    pdf.set_font("Helvetica", "B", 17)
    pdf.cell(0, 8, "Registration-day sheet", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 5, _t("  |  ".join(x for x in [d.get("student"), d.get("program"), d.get("term"), "printed " + str(d.get("generated") or "")] if x)),
             new_x="LMARGIN", new_y="NEXT")
    if d.get("countdown"):
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(79, 70, 229)
        pdf.cell(0, 6, _t(d["countdown"]["label"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    plan = d.get("plan")
    if not plan:
        pdf.ln(4)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6, "No active plan yet. On the Plan page, press 'Make this my active plan', then export this sheet again.")
        return bytes(pdf.output())
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, _t(f"{plan['total_credits']:g} credits, {len(plan['rows'])} courses"), new_x="LMARGIN", new_y="NEXT")

    widths = [9, 54, 12, 38, 18, 34, 10, 11]
    heads = ["", "Course", "Sec", "When", "Room", "Instructor", "Cr", "Seats"]
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_fill_color(240, 240, 245)
    pdf.set_draw_color(205, 205, 215)
    for w, h in zip(widths, heads):
        pdf.cell(w, 6, h, border=1, fill=True)
    pdf.ln()
    risk = {"low": "Plenty", "medium": "Medium", "fills fast": "Fills fast", "full": "Full", "unknown": "-"}
    for r in plan["rows"]:
        y = pdf.get_y()
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(widths[0], 9, "", border=1)
        pdf.rect(pdf.l_margin + 2.2, y + 2.2, 4.6, 4.6)                     # tick box
        pdf.cell(widths[1], 9, "", border=1)
        pdf.set_xy(pdf.l_margin + widths[0] + 1, y + 0.8)
        pdf.cell(widths[1] - 2, 4, _fit(pdf, r["code"], widths[1] - 2))
        pdf.set_font("Helvetica", "", 7.5)
        pdf.set_xy(pdf.l_margin + widths[0] + 1, y + 4.6)
        pdf.cell(widths[1] - 2, 3.6, _fit(pdf, r.get("title") or "", widths[1] - 2))
        pdf.set_xy(pdf.l_margin + widths[0] + widths[1], y)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(widths[2], 9, _t(r["section"]), border=1)
        pdf.set_font("Helvetica", "", 8.5)
        for w, v in zip(widths[3:], [r["when"], r.get("room") or "-", r.get("instructor") or "-", r.get("credits", ""), risk.get(r.get("risk"), "-")]):
            pdf.cell(w, 9, _fit(pdf, v, w), border=1)
        pdf.ln()
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(90, 90, 90)
        if r["backups"]:
            text = "Backup if full: " + "; ".join(f"section {b['section']} ({b['when']}{', ' + b['room'] if b['room'] else ''})" for b in r["backups"])
        else:
            text = "No other section fits around the rest of this plan."
        pdf.cell(sum(widths), 5.5, _fit(pdf, text, sum(widths)), border="LRB")
        pdf.ln()
        pdf.set_text_color(0, 0, 0)
    if plan.get("missing"):
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, _t("No longer offered, left off this sheet: " + ", ".join(plan["missing"])), new_x="LMARGIN", new_y="NEXT")

    timed, _untimed = _split_timed(plan.get("sections") or [])
    if timed:
        colour = {}
        for s in plan["sections"]:
            colour.setdefault(s.get("code"), PALETTE[len(colour) % len(PALETTE)])
        _h2(pdf, "Your week")
        if pdf.get_y() + 85 > 283:
            pdf.add_page()
        _timetable(pdf, timed, colour, total_w=185.0, max_h=70.0)
    _footer(pdf, d.get("generated"))
    return bytes(pdf.output())


def advisor_pdf(d):
    """The advisor summary (payload of /api/advisor-summary): progress, GPA by semester, roadmap, active plan."""
    pdf = _new_portrait()
    pdf.set_font("Helvetica", "B", 17)
    pdf.cell(0, 8, "Advisor summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 5, _t("  |  ".join(x for x in [d.get("student"), d.get("program"), d.get("term"), "prepared " + str(d.get("generated") or "")] if x)),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    if not d.get("has_curriculum"):
        pdf.ln(4)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6, "No curriculum loaded yet. Load a sample plan or import your degree audit on the Curriculum page first.")
        return bytes(pdf.output())
    p, road, gpa = d["progress"], d["roadmap"], d["gpa"]

    # key figures
    pdf.ln(2)
    figs = [("Credits completed", f"{p['done']:g} / {p['total']:g}", f"{p['percent']}% | {p['remaining']:g} left"),
            ("Cumulative GPA", "-" if gpa.get("value") is None else f"{gpa['value']:.2f}", f"{gpa['graded']} of {gpa['completed']} graded"),
            ("Required courses left", str(d["remaining_required"]), ""),
            ("Est. graduation", road.get("graduation_term") or "-", "")]
    w = (186 - 3 * 4) / 4
    y0, x0 = pdf.get_y(), pdf.l_margin
    for i, (label, value, sub) in enumerate(figs):
        x = x0 + i * (w + 4)
        pdf.set_draw_color(205, 205, 215)
        pdf.rect(x, y0, w, 22)
        pdf.set_xy(x + 2, y0 + 1.5); pdf.set_font("Helvetica", "", 7.5); pdf.set_text_color(100, 100, 100); pdf.cell(w - 4, 4, _t(label))
        pdf.set_xy(x + 2, y0 + 6.5); pdf.set_font("Helvetica", "B", 13); pdf.set_text_color(0, 0, 0); pdf.cell(w - 4, 7, _fit(pdf, value, w - 4))
        pdf.set_xy(x + 2, y0 + 15); pdf.set_font("Helvetica", "", 7); pdf.set_text_color(100, 100, 100); pdf.cell(w - 4, 4, _fit(pdf, sub, w - 4))
    pdf.set_text_color(0, 0, 0)
    pdf.set_y(y0 + 25)

    _h2(pdf, "Progress by category")
    for r in p["rows"]:
        y = pdf.get_y()
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(60, 5.5, _fit(pdf, r["category"], 60))
        bx = pdf.l_margin + 62
        pdf.set_fill_color(230, 230, 238); pdf.rect(bx, y + 1.2, 90, 3.2, style="F")
        frac = min(1.0, (r["done"] / r["total"]) if r["total"] else 0)
        pdf.set_fill_color(79, 70, 229); pdf.rect(bx, y + 1.2, 90 * frac, 3.2, style="F")
        pdf.set_x(bx + 93)
        pdf.cell(30, 5.5, _t(f"{r['done']:g} / {r['total']:g} cr"))
        pdf.ln(6)

    if gpa.get("semesters"):
        _h2(pdf, "GPA by semester")
        pdf.set_font("Helvetica", "B", 8.5); pdf.set_fill_color(240, 240, 245); pdf.set_draw_color(205, 205, 215)
        for ww, h in zip([60, 30, 30, 30], ["Semester", "Credits", "GPA", "Cumulative"]):
            pdf.cell(ww, 5.5, h, border=1, fill=True)
        pdf.ln()
        pdf.set_font("Helvetica", "", 8.5)
        for r in gpa["semesters"]:
            for ww, v in zip([60, 30, 30, 30], [r["semester"], f"{r['credits']:g}", "-" if r["gpa"] is None else f"{r['gpa']:.2f}",
                                                  "-" if r["cumulative_gpa"] is None else f"{r['cumulative_gpa']:.2f}"]):
                pdf.cell(ww, 5.5, _t(v), border=1)
            pdf.ln()

    _h2(pdf, "Graduation roadmap")
    pdf.set_font("Helvetica", "", 8.5)
    for r in road.get("risks") or []:
        pdf.multi_cell(0, 4.5, _t("- " + r), new_x="LMARGIN", new_y="NEXT")
    if road.get("terms"):
        pdf.set_font("Helvetica", "B", 8.5); pdf.set_fill_color(240, 240, 245)
        for ww, h in zip([30, 16, 140], ["Term", "Credits", "Planned courses"]):
            pdf.cell(ww, 5.5, h, border=1, fill=True)
        pdf.ln()
        pdf.set_font("Helvetica", "", 8.5)
        for t in road["terms"]:
            y = pdf.get_y()
            text = "; ".join(t["courses"])
            lines = pdf.multi_cell(140, 4.6, _t(text), split_only=True) or [""]
            h = max(5.5, 4.6 * len(lines) + 1)
            if y + h > 280:
                pdf.add_page(); y = pdf.get_y()
            pdf.set_xy(pdf.l_margin, y); pdf.cell(30, h, _t(t["label"]), border=1)
            pdf.cell(16, h, _t(f"{t['credits']:g}"), border=1)
            pdf.rect(pdf.l_margin + 46, y, 140, h)
            pdf.set_xy(pdf.l_margin + 46, y + 0.6); pdf.multi_cell(140, 4.6, _t(text), new_x="LMARGIN", new_y="NEXT")
            pdf.set_y(y + h)
    else:
        pdf.cell(0, 5.5, "All required courses are completed.", new_x="LMARGIN", new_y="NEXT")
    note = (f"{road['real_offerings_term']} is checked against real offerings; later terms are projections." if road.get("real_offerings_term")
            else "Every term is a projection from the sample plan and prerequisites.")
    pdf.set_font("Helvetica", "I", 8); pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 4.5, _t(note + f" Credit limit {road.get('max_credits'):g} per term." if road.get("max_credits") else note), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)

    _h2(pdf, "This term's plan" + (f" ({d['plan_credits']:g} credits)" if d.get("plan") else ""))
    pdf.set_font("Helvetica", "", 8.5)
    if d.get("plan"):
        pdf.set_font("Helvetica", "B", 8.5); pdf.set_fill_color(240, 240, 245)
        for ww, h in zip([84, 12, 46, 30, 14], ["Course", "Sec", "When", "Room", "Cr"]):
            pdf.cell(ww, 5.5, h, border=1, fill=True)
        pdf.ln()
        pdf.set_font("Helvetica", "", 8.5)
        for r in d["plan"]:
            for ww, v in zip([84, 12, 46, 30, 14], [f"{r['code']} {r.get('title') or ''}", r["section"], r["when"], r.get("room") or "-", r.get("credits", "")]):
                pdf.cell(ww, 5.5, _fit(pdf, v, ww), border=1)
            pdf.ln()
    else:
        pdf.cell(0, 5.5, "No active plan chosen yet (choose one on the Plan page).", new_x="LMARGIN", new_y="NEXT")
    _footer(pdf, d.get("generated"))
    return bytes(pdf.output())
