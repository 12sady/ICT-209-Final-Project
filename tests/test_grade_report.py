"""grade_report.py on made-up word positions shaped like a real AUPP grade report
(no real student's data is kept in the repo)."""
import unittest

import grade_report as gr

# Column x positions on the real report: left column / right column.
L = {"code": 34, "num": 54, "name": 81, "UA": 242, "UE": 256, "UC": 271, "GR": 286}
R = {k: v + 284 for k, v in L.items()}


def w(x, top, text):
    return {"x0": float(x), "top": float(top), "text": text}


def header(col, top, term, year):
    return [w(col["code"], top, term), w(col["code"] + 27, top, year)] + \
        [w(col[k], top, k) for k in ("UA", "UE", "UC", "GR")]


def course(col, top, subj, num, name, ua, ue, uc, grade):
    out = [w(col["code"], top, subj), w(col["num"], top, num), w(col["name"], top, name)]
    for k, v in (("UA", ua), ("UE", ue), ("UC", uc), ("GR", grade)):
        if v != "":
            out.append(w(col[k], top, v))
    return out


def totals(col, top, term_gpa, cum_gpa):
    return [w(col["code"], top, "Units-"), w(col["code"] + 23, top, "Attempted:"),
            w(col["UA"] - 20, top, "Term"), w(col["UA"], top, "GPA:"), w(col["UA"] + 20, top, term_gpa),
            w(col["code"], top + 10, "Academic"), w(col["code"] + 50, top + 10, "Standing:"),
            w(col["UA"], top + 10, "Cum"), w(col["UA"] + 15, top + 10, "GPA:"), w(col["UA"] + 35, top + 10, cum_gpa)]


PAGE1 = (
    [w(168, 28, "American"), w(357, 35, "Student"), w(429, 35, "1234567"), w(486, 35, "TEST,"), w(429, 49, "01-Jan-2000")]
    + header(L, 124, "Spring", "2023")
    + course(L, 137, "ENGL", "101", "English", "3", "3", "3", "B-")
    + [w(L["code"], 149, "ENGL"), w(L["num"], 149, "101")]                       # code wraps:
    + course(L, 155, "", "", "Enrichment", "3", "3", "3", "A-")[2:]               # data line in between
    + [w(L["code"], 160, "(ENR)")]
    + course(L, 172, "ENVS", "131C", "Environmental", "3", "3", "3", "B")
    + course(L, 184, "SMNR", "101", "Seminar", "1", "1", "0", "P")
    + totals(L, 196, "3.11", "3.11")
    + header(L, 700, "Summer", "2025")                                            # box breaks to page 2
    + header(R, 124, "Fall", "2026")
    + course(R, 137, "ICT", "209", "AI", "3", "", "", "RG")
    + course(R, 149, "MATH", "234A", "Calculus", "5", "", "", "RG")
    + [w(R["code"], 300, "SUMMARY"), w(R["code"], 312, "Cumulative"), w(R["code"] + 50, 312, "GPA:"), w(R["code"] + 75, 312, "3.40")]
)
PAGE2 = (
    course(L, 40, "CLD", "374", "Cloud", "3", "3", "3", "B+")
    + course(L, 52, "COSC", "121*", "CS A", "3", "3", "3", "A")
    + totals(L, 64, "3.67", "3.40")
)
PAGES = [{"width": 612, "height": 792, "words": PAGE1}, {"width": 612, "height": 792, "words": PAGE2}]


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.p = gr.parse_pages(PAGES)
        self.by = {c["code"]: c for c in self.p["courses"]}

    def test_minus_grades_and_wrapped_codes(self):
        self.assertEqual(self.by["ENGL 101"]["grade"], "B-")
        self.assertEqual(self.by["ENGL 101 (ENR)"]["grade"], "A-")
        self.assertEqual(self.by["ENVS 131C"]["term"], "Spring 2023")

    def test_left_column_continues_on_next_page(self):
        self.assertEqual(self.by["CLD 374"]["term"], "Summer 2025")

    def test_right_column_read_after_left(self):
        self.assertEqual(self.by["ICT 209"]["term"], "Fall 2026")
        self.assertEqual(self.by["MATH 234A"]["attempted"], 5)

    def test_repeat_and_summary(self):
        self.assertTrue(self.by["COSC 121"]["repeated"])
        self.assertEqual(self.p["cum_gpa"], 3.40)
        self.assertEqual(self.p["terms"][0], {"term": "Spring 2023", "term_gpa": 3.11, "cum_gpa": 3.11})

    def test_personal_details_not_read(self):
        text = repr(self.p)
        for secret in ("1234567", "TEST", "01-Jan-2000"):
            self.assertNotIn(secret, text)


CATALOG = [
    {"code": "ENGL 101", "name": "English", "credits": 3, "required": True},
    {"code": "ENVS 131C", "name": "Env", "credits": 3, "required": False},
    {"code": "SMNR 101", "name": "Seminar", "credits": 1, "required": True},
    {"code": "MATH 234", "name": "Calc", "credits": 5, "required": True},
    {"code": "CLD 374", "name": "Cloud", "credits": 3, "required": False},
]


class MatchApplyTests(unittest.TestCase):
    def setUp(self):
        self.rows = {r["report_code"]: r for r in gr.match(gr.parse_pages(PAGES), CATALOG)}

    def test_statuses_and_matching(self):
        self.assertEqual(self.rows["ENGL 101"]["match"], "exact")
        self.assertEqual(self.rows["MATH 234A"]["code"], "MATH 234")          # similar code
        self.assertEqual(self.rows["MATH 234A"]["status"], "in_progress")
        self.assertEqual(self.rows["SMNR 101"]["status"], "completed")         # P counts as done
        self.assertEqual(self.rows["SMNR 101"]["credits"], 1)                  # UC is 0 for P -> use UA
        self.assertIsNone(self.rows["ENGL 101 (ENR)"]["code"])

    def test_repeated_course_keeps_latest_attempt(self):
        parsed = {"courses": [
            {"code": "CLD 374", "name": "", "term": "Fall 2024", "grade": "D", "attempted": 3, "carried": 3, "repeated": False},
            {"code": "CLD 374", "name": "", "term": "Spring 2025", "grade": "A", "attempted": 3, "carried": 3, "repeated": True},
        ]}
        (row,) = gr.match(parsed, CATALOG)
        self.assertEqual((row["grade"], row["term"]), ("A", "Spring 2025"))

    def test_apply_marks_completed_and_adds_extras(self):
        req = {"catalog": CATALOG, "completed": ["ENGL 101"], "grades": {"ENGL 101": "C"}}
        new, counts = gr.apply(req, [
            {"code": "ENGL 101", "grade": "B-", "term": "Spring 2023"},
            {"code": "SMNR 101", "grade": "P", "term": "Spring 2023"},
            {"code": "ENGL 101 (ENR)", "grade": "A-", "term": "Spring 2023", "add": {"name": "Enrichment", "credits": 3}},
        ])
        self.assertEqual(counts, {"added_to_curriculum": 1, "newly_completed": 2, "grades_set": 3})
        self.assertEqual(new["grades"]["ENGL 101"], "B-")
        self.assertEqual(new["completed_semesters"]["SMNR 101"], "Spring 2023")
        self.assertEqual(new["catalog"][-1]["category"], gr.EXTRA_CATEGORY)
        self.assertEqual(new["required_remaining"], ["MATH 234"])
        self.assertEqual(req["completed"], ["ENGL 101"])                       # input not changed

    def test_apply_refuses_bad_rows(self):
        for bad in ({"code": "MATH 234", "grade": "RG"}, {"code": "MATH 234", "grade": "F"},
                    {"code": "NOPE 1", "grade": "A"}, {"code": "", "grade": "A"}):
            with self.assertRaises(ValueError):
                gr.apply({"catalog": CATALOG}, [bad])


if __name__ == "__main__":
    unittest.main()
