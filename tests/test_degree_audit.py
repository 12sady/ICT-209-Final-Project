"""Degree audit import (degree_audit.py). The pages below are made up, laid out
like AUPP's real audit (column positions, wrapped cells, shaded blank-category
rows, summary page). No real student data is used."""
import unittest

import degree_audit as da
import structure


def W(text, x, top):
    return {"text": text, "x0": float(x), "top": float(top)}


def row(top, cat, subject, number, name, credits, term=(), grade="", earned=None):
    """One table row. `cat` is e.g. ("M", "-", "Major"); `term` e.g. ("Fall", "2026")."""
    ws = []
    x = 35
    for t in cat:
        ws.append(W(t, x, top))
        x += 14 if len(t) < 3 else 40
    ws.append(W(subject, 166, top))
    if number:
        ws.append(W(number, 188, top))
    ws += [W(t, 216 + 30 * i, top) for i, t in enumerate(name.split())]
    ws.append(W(str(credits), 372, top))
    for i, t in enumerate(term):
        ws.append(W(t, 411 + 26 * i, top))
    if grade:
        ws.append(W(grade, 471, top))
    if earned is not None:
        ws.append(W(str(earned), 505, top))
    return ws


PAGE1 = [
    W("Student", 343, 27), W("ID/Name:", 374, 27), W("0000000", 413, 27), W("-", 445, 27), W("TEST,", 450, 27), W("Person", 475, 27),
    W("Date", 343, 44), W("of", 361, 44), W("Birth", 371, 44), W(":", 409, 44), W("01-Jan-2000", 413, 44),
    W("Catalog", 343, 60), W("Term", 373, 60), W(":", 409, 60), W("Fall", 413, 60), W("2024", 428, 60),
    W("Kork", 305, 76), W("Degree", 343, 76), W(":", 409, 76), W("Bachelor", 413, 76), W("of", 448, 76),
    W("Science", 457, 76), W("in", 487, 76),
    W("Website:", 40, 87), W("Testing", 409, 87), W("(AUPP)", 454, 87),
    W("Category", 35, 120), W("AUPP", 166, 120), W("CSN", 190, 120), W("Course", 216, 120), W("Name", 245, 120),
    W("Credits", 372, 120), W("Semester", 411, 120), W("Grade", 471, 120), W("Credits", 505, 120),
]
# blank category = shaded row, passed
PAGE1 += row(140, (), "ZZZ", "110", "Shaded Course", 3, ("Spring", "2026"), "A", 3)
PAGE1 += row(152, ("M", "-", "Major"), "COSC", "111", "Intro CS", 3, ("Fall", "2026"), "RG")
PAGE1 += row(164, ("M", "-", "Major"), "MATH", None, "Calculus I", 5)
PAGE1 += [W("234A", 166, 175)]                                               # number wrapped onto the next line
PAGE1 += row(187, ("GER", "-", "General", "Education"), "ENGL", "101", "English I", 3, ("Fall", "2025"), "A", 3)
PAGE1 += [W("(Required)", 35, 198)]

PAGE2 = []
PAGE2 += row(40, ("GER", "-", "General", "Education"), "SMNR", "101", "First Year", 1, ("Fall", "2025"), "P", 1)
PAGE2 += [W("(Required)", 35, 51)]
PAGE2 += row(63, ("GER", "-", "General", "Education"), "PSYC", "101", "Psychology", 3, ("Summer",), "A", 3)
PAGE2 += [W("2026", 411, 74), W("(Required)", 35, 74)]                       # year wrapped onto the next line
PAGE2 += row(86, ("ME", "-", "Major", "Electives"), "CLD", "371", "Cloud Ops", 3)
PAGE2 += row(98, ("ME", "-", "Major", "Electives"), "CLD", "372", "Cloud Arch", 3)
PAGE2 += row(110, ("CM", "-", "Core/Major"), "FYP", "401", "Final Project", 3)
PAGE2 += [W("Notes!", 35, 140), W("Shaded", 35, 152), W("courses", 70, 152)]

PAGE3 = [
    W("Recommended", 51, 31), W("course", 109, 31),
    W("Required:", 36, 67), W("Completed:", 313, 67),
    W("24", 268, 72), W("7", 550, 72),
    W("in", 36, 102), W("Testing", 44, 102), W("Major:", 122, 102), W("8", 273, 102),
    W("in", 313, 102), W("Testing", 322, 102), W("Major:", 399, 102), W("0", 555, 102),
    W("Major", 36, 124), W("Electives:", 58, 124), W("3", 273, 124), W("Major", 313, 124), W("Electives:", 336, 124), W("0", 555, 124),
    W("General", 36, 147), W("Education", 66, 147), W("(Required):", 105, 147), W("7", 273, 147),
    W("General", 313, 147), W("Education", 344, 147), W("(Required):", 383, 147), W("7", 550, 147),
    W("Core/Major:", 36, 169), W("6", 273, 169), W("Core/Major:", 313, 169), W("0", 555, 169),
]

PAGES = [{"width": 595.0, "height": 842.0, "words": w} for w in (PAGE1, PAGE2, PAGE3)]


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.parsed = da.parse_pages(PAGES)
        self.by = {c["code"]: c for c in self.parsed["courses"]}

    def test_header_values_only(self):
        self.assertEqual(self.parsed["program"], "Bachelor of Science in Testing")
        self.assertEqual(self.parsed["catalog_term"], "Fall 2024")
        self.assertNotIn("TEST", str(self.parsed))          # the name/ID/date-of-birth lines are never read
        self.assertNotIn("0000000", str(self.parsed))

    def test_rows_wrapped_cells_and_categories(self):
        self.assertEqual(set(self.by), {"ZZZ 110", "COSC 111", "MATH 234A", "ENGL 101", "SMNR 101", "PSYC 101", "CLD 371", "CLD 372", "FYP 401"})
        self.assertEqual(self.by["MATH 234A"]["credits"], 5)                       # number on the next line
        self.assertEqual(self.by["PSYC 101"]["term"], "Summer 2026")               # year on the next line
        self.assertEqual(self.by["ENGL 101"]["category"], "General Education (Required)")
        self.assertEqual(self.by["FYP 401"]["category"], "Core/Major")
        self.assertEqual(self.by["ZZZ 110"]["category"], "")                       # shaded

    def test_statuses(self):
        st = {c: v["status"] for c, v in self.by.items()}
        self.assertEqual(st["ENGL 101"], "completed")
        self.assertEqual(st["SMNR 101"], "completed")                              # P counts as passed
        self.assertEqual(st["COSC 111"], "in_progress")                            # RG
        self.assertEqual(st["CLD 371"], "not_taken")

    def test_summary_page(self):
        s = self.parsed["summary"]
        self.assertEqual((s["total_required"], s["total_completed"]), (24, 7))
        self.assertEqual({c["label"]: c["required"] for c in s["categories"]},
                         {"in Testing Major": 8, "Major Electives": 3, "General Education (Required)": 7, "Core/Major": 6})


class SummaryAndStructureTest(unittest.TestCase):
    def setUp(self):
        self.parsed = da.parse_pages(PAGES)
        self.sum = da.summarize(self.parsed)

    def test_category_targets_come_from_the_summary(self):
        rows = {c["name"]: c for c in self.sum["categories"]}
        self.assertEqual((rows["Major"]["target"], rows["Major"]["listed"]), (8, 8))
        self.assertEqual((rows["Major Electives"]["target"], rows["Major Electives"]["listed"]), (3, 6))
        self.assertEqual((rows["General Education"]["target"], rows["General Education"]["passed_credits"]), (7, 7))
        self.assertEqual(self.sum["counts"], {"courses": 9, "passed": 4, "in_progress": 1, "not_taken": 4, "not_counted": 1})

    def test_warns_when_a_category_lists_fewer_credits_than_it_needs(self):
        self.assertTrue(any("Core/Major needs 6 credits" in w for w in self.sum["warnings"]))
        self.assertFalse(any("General Education" in w for w in self.sum["warnings"]))     # passed credits match the audit

    def test_structure_has_categories_and_the_shaded_group(self):
        st = da.to_structure(self.parsed)
        self.assertEqual(st["total_credits"], 24)
        cats = {c["name"]: c for c in structure.categories(st)}
        self.assertTrue(cats["Major"]["all_required"])                 # 8 listed = 8 needed
        self.assertFalse(cats["Major Electives"]["all_required"])      # choose 3 of 6
        self.assertTrue(cats["Core/Major"]["all_required"])            # lists fewer credits than needed: all of them are required
        self.assertEqual([g["name"] for g in st["not_counted"]], [da.NOT_COUNTED_GROUP])
        ev = structure.evaluate(st, ["ENGL 101", "SMNR 101", "PSYC 101", "ZZZ 110"])
        self.assertEqual({r["category"]: r["done"] for r in ev["rows"]}["General Education"], 7)
        self.assertEqual(ev["not_counted"], [{"group": da.NOT_COUNTED_GROUP + " (not counted)", "courses": ["ZZZ 110"]}])


class MoveTest(unittest.TestCase):
    def setUp(self):
        self.st = da.to_structure(da.parse_pages(PAGES))

    def cat(self, st, name):
        return next(c for c in st["categories"] if c["name"] == name)

    def test_move_a_shaded_course_into_a_category(self):
        moved = da.move_course(self.st, "ZZZ 110", "General Education")
        self.assertIn("ZZZ 110", [c["code"] for c in self.cat(moved, "General Education")["courses"]])
        self.assertNotIn("not_counted", moved)                                     # the group is empty now, so it's dropped
        self.assertIn("ZZZ 110", [c["code"] for g in self.st["not_counted"] for c in g["courses"]])   # input untouched
        ev = structure.evaluate(moved, ["ENGL 101", "SMNR 101", "PSYC 101", "ZZZ 110"])
        ge = {r["category"]: r for r in ev["rows"]}["General Education"]
        self.assertEqual((ge["done"], ge["extra"]), (7, 3))                        # counts up to the 7 needed, the rest is extra

    def test_move_back_to_not_counted_and_errors(self):
        moved = da.move_course(self.st, "ENGL 101", "")
        self.assertEqual([c["code"] for c in moved["not_counted"][0]["courses"]], ["ZZZ 110", "ENGL 101"])
        with self.assertRaises(ValueError):
            da.move_course(self.st, "NOPE 999", "Major")
        with self.assertRaises(ValueError):
            da.move_course(self.st, "ZZZ 110", "No such category")

    def test_moves_survive_a_new_upload(self):
        req = {"audit_moves": {"ZZZ 110": "General Education", "GONE 1": "Major"}}
        new, _ = da.apply(req, da.parse_pages(PAGES))
        self.assertIn("ZZZ 110", [c["code"] for c in self.cat(new["audit_structure"], "General Education")["courses"]])
        self.assertEqual(new["audit_moves"], req["audit_moves"])


class SuggestTest(unittest.TestCase):
    def setUp(self):
        self.parsed = da.parse_pages(PAGES)          # one shaded course: ZZZ 110

    def one(self, plan, moves=None):
        return da.suggest(self.parsed, plan, moves)["ZZZ 110"]

    def test_sample_plan_general_education(self):
        got = self.one({"ZZZ110": {"category": "General Education (Required)", "required": True}})
        self.assertEqual(got["category"], "General Education")
        self.assertEqual(got["source"], "sample plan")

    def test_compulsory_elective_goes_to_core_major(self):
        self.assertEqual(self.one({"ZZZ110": {"category": "Electives", "required": True}})["category"], "Core/Major")

    def test_plain_elective_goes_to_major_electives(self):
        self.assertEqual(self.one({"ZZZ110": {"category": "Electives", "required": False}})["category"], "Major Electives")
        self.assertEqual(self.one({"ZZZ110": {"category": "Major Electives", "required": False}})["category"], "Major Electives")

    def test_major_only_when_it_has_room(self):
        got = self.one({"ZZZ110": {"category": "Major", "required": True}})      # Major lists 8 of 8: full
        self.assertEqual(got["category"], "")
        self.assertIn("already full", got["reason"])

    def test_no_hint_means_no_suggestion_and_earlier_choice_wins(self):
        self.assertEqual(self.one({})["category"], "")
        self.assertEqual(self.one({}, {"ZZZ 110": "General Education"})["category"], "General Education")
        self.assertEqual(self.one({}, {"ZZZ 110": "General Education"})["source"], "you")

    def test_summary_lists_only_shaded_courses_with_suggestions(self):
        s = da.summarize(self.parsed, {"ZZZ110": {"category": "General Education (Required)"}}, None, with_suggestions=True)
        self.assertEqual([u["code"] for u in s["uncounted"]], ["ZZZ 110"])
        self.assertEqual(s["uncounted"][0]["category"], "General Education")
        self.assertEqual(da.summarize(self.parsed)["uncounted"], [])             # not asked for: left out

    def test_match_program_by_name_or_pick(self):
        progs = [{"id": "biz", "name": "Business"}, {"id": "ba", "name": "Business Administration"}, {"id": "ai", "name": "Artificial Intelligence"}]
        self.assertEqual(da.match_program(progs, "", "Bachelor of Science in Business Administration (AUPP)")["id"], "ba")
        self.assertEqual(da.match_program(progs, "ai", "anything")["id"], "ai")
        self.assertIsNone(da.match_program(progs, "", "Bachelor of Arts in Law"))

    def test_reupload_keeps_courses_added_by_hand(self):
        first, _ = da.apply({}, self.parsed)
        first["catalog"].append({"code": "HAND 100", "name": "Added by me", "category": "Electives", "credits": 3, "required": False})
        again, _ = da.apply(first, self.parsed)
        self.assertIn("HAND 100", [c["code"] for c in again["catalog"]])
        old_plan_req = {"catalog": [{"code": "OLD 100", "name": "Sample plan course", "category": "Major", "credits": 3}]}
        fresh, _ = da.apply(old_plan_req, self.parsed)                              # first audit upload replaces the sample plan
        self.assertNotIn("OLD 100", [c["code"] for c in fresh["catalog"]])


class ApplyTest(unittest.TestCase):
    def test_apply_rebuilds_the_curriculum_from_the_audit(self):
        req = {"program": "Old", "completed": ["OLD 100", "COSC 111"], "completed_semesters": {"OLD 100": "Fall 2024"},
               "grades": {"OLD 100": "B"},
               "catalog": [{"code": "COSC 111", "name": "x", "category": "Major", "credits": 3, "required": True,
                            "hard_prereqs": ["ITM 380"], "plan_year": 1, "plan_term": "Fall"}]}
        new, counts = da.apply(req, da.parse_pages(PAGES))
        by = {c["code"]: c for c in new["catalog"]}
        self.assertEqual(len(new["catalog"]), 9)
        self.assertEqual(by["COSC 111"]["hard_prereqs"], ["ITM 380"])          # kept from the old catalog
        self.assertEqual(by["COSC 111"]["name"], "Intro CS")
        self.assertEqual(by["ENGL 101"]["category"], "General Education")
        self.assertEqual(by["ZZZ 110"]["category"], "")
        self.assertEqual(set(new["completed"]), {"OLD 100", "ENGL 101", "SMNR 101", "PSYC 101", "ZZZ 110"})
        self.assertNotIn("COSC 111", new["completed"])                         # the audit says in progress, not passed
        self.assertEqual(new["grades"]["ENGL 101"], "A")
        self.assertEqual(new["grades"]["SMNR 101"], "P")
        self.assertEqual(new["grades"]["OLD 100"], "B")                        # not on the audit: kept
        self.assertEqual(new["completed_semesters"]["PSYC 101"], "Summer 2026")
        self.assertEqual(new["program"], "Bachelor of Science in Testing")
        self.assertEqual(new["audit_structure"]["total_credits"], 24)
        self.assertEqual(counts, {"courses": 9, "completed": 4, "in_progress": 1, "not_counted": 1})
        self.assertEqual(new["in_progress"], ["COSC 111"])                       # RG: remembered, counts as done for what's next


if __name__ == "__main__":
    unittest.main()
