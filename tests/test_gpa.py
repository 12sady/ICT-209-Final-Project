import unittest

import gpa


def e(credits, grade, semester=""):
    return {"credits": credits, "grade": grade, "semester": semester}


class TotalsTests(unittest.TestCase):
    def test_weighted_average(self):
        t = gpa.totals([e(3, "A"), e(3, "B"), e(4, "C+")])
        self.assertAlmostEqual(t["quality_points"], 12 + 9 + 9.2)
        self.assertAlmostEqual(t["gpa"], 30.2 / 10)

    def test_ungraded_and_unknown_grades_ignored(self):
        t = gpa.totals([e(3, ""), e(3, None), e(3, "Z"), e(3, "A-")])
        self.assertEqual(t["gpa_credits"], 3)
        self.assertAlmostEqual(t["gpa"], 3.7)

    def test_pass_withdrawn_excluded_from_gpa(self):
        t = gpa.totals([e(3, "A"), e(3, "P"), e(3, "W"), e(3, "NP"), e(3, "I"), e(3, "AU")])
        self.assertEqual(t["gpa"], 4.0)
        self.assertEqual(t["gpa_credits"], 3)
        self.assertEqual(t["attempted"], 9)   # A, P, NP
        self.assertEqual(t["earned"], 6)      # A, P

    def test_fail_counts_as_attempted_not_earned(self):
        t = gpa.totals([e(3, "F"), e(3, "B")])
        self.assertAlmostEqual(t["gpa"], 1.5)
        self.assertEqual(t["attempted"], 6)
        self.assertEqual(t["earned"], 3)

    def test_empty_gives_none(self):
        self.assertIsNone(gpa.totals([])["gpa"])
        self.assertIsNone(gpa.totals([e(3, "P")])["gpa"])

    def test_lowercase_grades_normalised(self):
        self.assertEqual(gpa.normalize_grade(" b+ "), "B+")
        self.assertEqual(gpa.normalize_grade("zz"), "")


class SemesterTests(unittest.TestCase):
    def test_order_and_cumulative(self):
        rows = gpa.by_semester([
            e(3, "A", "Fall 2025"), e(3, "C", "Spring 2025"), e(3, "B", "Spring 2025"), e(3, "A", ""),
        ])
        self.assertEqual([r["semester"] for r in rows], ["Spring 2025", "Fall 2025", "No semester picked"])
        self.assertAlmostEqual(rows[0]["gpa"], 2.5)
        self.assertAlmostEqual(rows[1]["cumulative_gpa"], (2 + 3 + 4) / 3, places=3)
        self.assertIsNone(rows[2]["cumulative_gpa"])


class WhatIfTests(unittest.TestCase):
    def test_new_gpa(self):
        w = gpa.what_if([e(30, "B")], [e(15, "A")])
        self.assertAlmostEqual(w["new_gpa"], (90 + 60) / 45, places=3)
        self.assertAlmostEqual(w["change"], (150 / 45) - 3.0, places=3)

    def test_no_history(self):
        w = gpa.what_if([], [e(3, "A")])
        self.assertEqual(w["new_gpa"], 4.0)
        self.assertIsNone(w["change"])


class RequiredAverageTests(unittest.TestCase):
    base = [e(30, "B")]  # 90 quality points over 30 credits

    def test_boundary_unreachable(self):
        r = gpa.required_average(self.base, 15, 3.5)
        self.assertFalse(r["feasible"])
        self.assertIn("isn't reachable", r["message"])
        # 90 QP over 30 cr; straight 4.0s: (90 + 4x) / (30 + x) = 3.5  ->  x = 30
        self.assertAlmostEqual(r["credits_at_top"], 30.0, places=1)

    def test_reachable_target(self):
        r = gpa.required_average(self.base, 15, 3.3)
        self.assertTrue(r["feasible"])
        self.assertAlmostEqual(r["needed"], (3.3 * 45 - 90) / 15, places=3)  # 3.9
        self.assertEqual(r["letter"], "A")

    def test_already_met(self):
        r = gpa.required_average(self.base, 15, 2.0)
        self.assertTrue(r["feasible"])
        self.assertEqual(r["needed"], 0.0)
        self.assertIn("already", r["message"])

    def test_bad_inputs(self):
        self.assertIsNone(gpa.required_average(self.base, 0, 3.5)["needed"])
        self.assertIsNone(gpa.required_average(self.base, 15, 4.5)["needed"])
        self.assertIsNone(gpa.required_average(self.base, "abc", 3.5)["needed"])

    def test_a_or_an(self):
        self.assertEqual(gpa.article("A"), "an")
        self.assertEqual(gpa.article("F"), "an")
        self.assertEqual(gpa.article("B+"), "a")
        self.assertEqual(gpa.article("C"), "a")
        r = gpa.required_average([e(30, "B")], 15, 3.3)         # needs 3.9 -> an A
        self.assertIn("about an A)", r["message"])
        r = gpa.required_average([e(30, "B")], 15, 2.0 + 1.2)    # needs about 3.4 -> a B+ or A-
        self.assertNotIn("about a A", r["message"])

    def test_new_student(self):
        r = gpa.required_average([], 15, 3.8)
        self.assertTrue(r["feasible"])
        self.assertAlmostEqual(r["needed"], 3.8)


if __name__ == "__main__":
    unittest.main()
