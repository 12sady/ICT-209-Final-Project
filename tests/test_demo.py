import unittest

import demo
import gpa
import progress
import programs


def program():
    def crs(code, cat="Major", prereqs=()):
        return {"code": code, "title": code, "credits": 3, "prereqs": list(prereqs), "category": cat}
    terms = [
        {"year": 1, "term": "Fall", "courses": [crs("A 100", "General Education"), crs("B 100")]},
        {"year": 1, "term": "Spring", "courses": [crs("A 200", "General Education"), crs("B 200", prereqs=["B 100"])]},
        {"year": 2, "term": "Fall", "courses": [crs("C 300", prereqs=["B 200"])]},
        {"year": 2, "term": "Spring", "courses": [crs("D 300", prereqs=["C 300"])]},
        {"year": 3, "term": "Fall", "courses": [crs("E 400", prereqs=["D 300"]), crs("F 400", prereqs=["C 300"]), crs("G 400"), crs("H 400")]},
    ]
    return {"id": "t", "name": "Test", "degree": "Single", "credit_total": 30, "terms": terms, "electives": []}


def sec(code, section, days, start, end):
    return {"code": code, "section": section, "title": code, "days": days, "start": start, "end": end, "credits": 3.0,
            "risk": "unknown", "online": False}


class DemoTests(unittest.TestCase):
    def test_semester_labels(self):
        self.assertEqual(demo.demo_semester(1, "Fall"), "Fall 2024")
        self.assertEqual(demo.demo_semester(1, "Spring"), "Spring 2025")
        self.assertEqual(demo.demo_semester(2, "Fall"), "Fall 2025")
        self.assertEqual(demo.demo_semester(2, "Spring"), "Spring 2026")

    def test_grades_are_deterministic_and_valid(self):
        for code in ["COSC 111", "ENGL 101", "X 1"]:
            g = demo.demo_grade(code)
            self.assertEqual(g, demo.demo_grade(code))
            self.assertIn(g, gpa.GRADE_SCALE)

    def test_requirements_two_years_completed(self):
        req = demo.build_requirements(program())
        self.assertEqual(req["completed"], ["A 100", "B 100", "A 200", "B 200", "C 300", "D 300"])
        self.assertEqual(set(req["grades"]), set(req["completed"]))
        self.assertEqual(req["completed_semesters"]["D 300"], "Spring 2026")
        self.assertEqual(req["required_remaining"], ["E 400", "F 400", "G 400", "H 400"])
        self.assertEqual(req["semester"], "Fall 2026")

    def test_grades_produce_a_sensible_gpa(self):
        req = demo.build_requirements(program())
        entries = [{"credits": 3, "grade": g} for g in req["grades"].values()]
        self.assertTrue(2.0 <= gpa.totals(entries)["gpa"] <= 4.0)

    def test_wishlist_and_two_plans(self):
        req = demo.build_requirements(program())
        offerings = [sec("E 400", "1", ["Mon", "Wed"], "09:00", "10:30"), sec("E 400", "2", ["Tue", "Thu"], "09:00", "10:30"),
                     sec("F 400", "1", ["Mon", "Wed"], "11:00", "12:30"), sec("G 400", "1", ["Fri"], "09:00", "12:00"),
                     sec("D 300", "1", ["Mon"], "09:00", "10:00")]     # D 300 is completed: must not be wishlisted
        wl, plans = demo.choose_wishlist_and_plans(req, offerings)
        self.assertIn("F 400", wl)
        self.assertNotIn("D 300", wl)
        self.assertIn("E 400", wl)                                        # its prerequisite D 300 is done
        self.assertEqual(len(plans), 2)
        self.assertNotEqual(sorted(map(str, plans[0])), sorted(map(str, plans[1])))
        import compare
        by_key = {(s["code"], s["section"]): s for s in offerings}
        m = [compare.plan_metrics([by_key[(k["code"], k["section"])] for k in p], wl) for p in plans]
        self.assertTrue(compare.compare_plans(m))                          # the two plans differ somewhere

    def test_no_offerings_gives_empty_wishlist(self):
        req = demo.build_requirements(program())
        self.assertEqual(demo.choose_wishlist_and_plans(req, []), ([], []))


if __name__ == "__main__":
    unittest.main()
