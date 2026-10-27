import unittest

import progress as pg


def c(code, credits=3, cat="Major", required=True, prereqs=(), year=None, term="Fall"):
    d = {"code": code, "name": code, "credits": credits, "category": cat, "required": required, "hard_prereqs": list(prereqs)}
    if year:
        d["plan_year"], d["plan_term"] = year, term
    return d


class CategoryTests(unittest.TestCase):
    def test_rows_and_overall(self):
        cat = [c("A 1", cat="Gen Ed"), c("B 1", cat="Gen Ed"), c("M 1", credits=4), c("E 1", cat="Electives", required=False)]
        r = pg.category_progress(cat, ["A 1", "M 1"], [])
        rows = {x["category"]: x for x in r["rows"]}
        self.assertEqual((rows["Gen Ed"]["done"], rows["Gen Ed"]["total"]), (3, 6))
        self.assertEqual((rows["Major"]["done"], rows["Major"]["total"]), (4, 4))
        self.assertEqual((r["done"], r["total"], r["remaining"]), (7, 10, 3))
        self.assertEqual(r["percent"], 70.0)

    def test_completed_electives_use_up_slots(self):
        cat = [c("M 1"), c("E 1", required=False), c("E 2", required=False)]
        slots = [{"credits": 3}, {"credits": 3}, {"credits": 3}]
        r = pg.category_progress(cat, ["E 1", "E 2"], slots)
        elec = next(x for x in r["rows"] if x["category"] == "Open electives")
        self.assertEqual((elec["done"], elec["total"]), (6, 9))
        filled, still = pg.open_slots(cat, ["E 1", "E 2"], slots)
        self.assertEqual((len(filled), len(still)), (2, 1))

    def test_extra_electives_reported(self):
        cat = [c("M 1"), c("E 1", required=False), c("E 2", required=False)]
        r = pg.category_progress(cat, ["E 1", "E 2"], [{"credits": 3}])
        self.assertEqual(r["extra_electives"], 1)

    def test_empty_catalog(self):
        r = pg.category_progress([], [], [])
        self.assertEqual((r["total"], r["percent"]), (0, 0.0))


class AvailabilityTests(unittest.TestCase):
    cat = [c("A 1", year=1), c("B 1", prereqs=["A 1"], year=2), c("C 1", prereqs=["B 1"], year=3), c("D 1", year=1)]

    def test_available_now(self):
        out = pg.available_now(self.cat, [], {"B 1": ["A 1"], "C 1": ["B 1"]}, offered={"A 1"})
        self.assertEqual([x["code"] for x in out], ["A 1", "D 1"])
        self.assertEqual([x["offered"] for x in out], [True, False])

    def test_completing_unlocks(self):
        out = pg.available_now(self.cat, ["A 1"], {"B 1": ["A 1"], "C 1": ["B 1"]})
        self.assertEqual([x["code"] for x in out], ["D 1", "B 1"])   # sample-plan year 1 before year 2
        self.assertIsNone(out[0]["offered"])


class BottleneckTests(unittest.TestCase):
    def test_counts_indirect_dependents(self):
        cat = [c("A 1"), c("B 1", prereqs=["A 1"]), c("C 1", prereqs=["B 1"]), c("D 1", prereqs=["A 1"]), c("Z 1")]
        rows = pg.bottlenecks(cat, [], {})
        self.assertEqual(rows[0]["code"], "A 1")
        self.assertEqual(rows[0]["unlocks"], 3)   # B, C (via B), D
        self.assertEqual(rows[0]["direct"], 2)
        self.assertTrue(rows[0]["available_now"])
        self.assertNotIn("Z 1", [r["code"] for r in rows])

    def test_completed_courses_dont_count(self):
        cat = [c("A 1"), c("B 1", prereqs=["A 1"]), c("C 1", prereqs=["B 1"])]
        rows = pg.bottlenecks(cat, ["A 1"], {})
        self.assertEqual([(r["code"], r["unlocks"]) for r in rows], [("B 1", 1)])

    def test_loop_does_not_hang(self):
        cat = [c("A 1", prereqs=["B 1"]), c("B 1", prereqs=["A 1"])]
        pg.bottlenecks(cat, [], {})


if __name__ == "__main__":
    unittest.main()
