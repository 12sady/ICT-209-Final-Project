import unittest
from datetime import date

import roadmap as rm


def course(code, credits=3, prereqs=(), year=None, term=None, required=True, name=None):
    c = {"code": code, "name": name or code, "credits": credits, "required": required,
         "hard_prereqs": list(prereqs)}
    if year:
        c["plan_year"], c["plan_term"] = year, term
    return c


def build(catalog, completed=(), slots=(), **kw):
    prereqs = {c["code"]: c["hard_prereqs"] for c in catalog if c["hard_prereqs"]}
    kw.setdefault("start_term", "Fall 2026")
    return rm.build_roadmap(catalog, set(completed), prereqs, list(slots), **kw)


def term_of(road, code):
    for t in road["terms"]:
        if any(c["id"] == code for c in t["courses"]):
            return t["label"]
    return None


class TermLabelTests(unittest.TestCase):
    def test_sequence_without_summer(self):
        self.assertEqual(rm.term_labels("Fall 2026", 4), ["Fall 2026", "Spring 2027", "Fall 2027", "Spring 2028"])

    def test_sequence_with_summer(self):
        self.assertEqual(rm.term_labels("Spring 2027", 4, include_summer=True),
                         ["Spring 2027", "Summer 2027", "Fall 2027", "Spring 2028"])

    def test_summer_start_moves_to_fall_when_summers_off(self):
        self.assertEqual(rm.normalize_start("Summer 2027"), "Fall 2027")

    def test_bad_label(self):
        with self.assertRaises(ValueError):
            rm.normalize_start("Autumn 2026")

    def test_guess_start(self):
        self.assertEqual(rm.guess_start_term(date(2026, 10, 27)), "Fall 2026")
        self.assertEqual(rm.guess_start_term(date(2027, 2, 1)), "Spring 2027")


class PlacementTests(unittest.TestCase):
    def test_prereq_goes_in_an_earlier_term(self):
        r = build([course("A 100"), course("B 200", prereqs=["A 100"]), course("C 300", prereqs=["B 200"])])
        self.assertEqual([term_of(r, c) for c in ("A 100", "B 200", "C 300")], ["Fall 2026", "Spring 2027", "Fall 2027"])
        self.assertEqual(r["graduation_term"], "Fall 2027")

    def test_completed_prereq_is_satisfied(self):
        r = build([course("A 100"), course("B 200", prereqs=["A 100"])], completed=["A 100"])
        self.assertEqual(term_of(r, "B 200"), "Fall 2026")

    def test_credit_limit_respected(self):
        cat = [course(f"X {i}00", credits=3) for i in range(1, 8)]  # 21 credits, limit 9
        r = build(cat, max_credits=9)
        self.assertTrue(all(t["credits"] <= 9 for t in r["terms"]))
        self.assertEqual(len(r["terms"]), 3)

    def test_oversized_course_gets_its_own_term(self):
        r = build([course("BIG 100", credits=12)], max_credits=9)
        self.assertEqual(len(r["terms"]), 1)
        self.assertTrue(r["terms"][0]["warnings"])  # over the limit is reported

    def test_sample_plan_order_preferred(self):
        cat = [course("L 400", year=4, term="Fall"), course("E 100", year=1, term="Fall"), course("M 200", year=2, term="Fall")]
        r = build(cat, max_credits=3)
        self.assertEqual([term_of(r, c) for c in ("E 100", "M 200", "L 400")], ["Fall 2026", "Spring 2027", "Fall 2027"])

    def test_long_chain_starts_early_over_dead_end(self):
        cat = [course("A 1"), course("B 1", prereqs=["A 1"]), course("C 1", prereqs=["B 1"]), course("Z 1")]
        r = build(cat, max_credits=3)
        self.assertEqual(term_of(r, "A 1"), "Fall 2026")  # chain start beats the lone course

    def test_not_required_courses_are_skipped(self):
        r = build([course("A 100"), course("ELEC 100", required=False)])
        self.assertIsNone(term_of(r, "ELEC 100"))

    def test_elective_slots_are_scheduled(self):
        r = build([course("A 100")], slots=[{"title": "Elective", "credits": 3, "year": 1, "term": "Fall"}])
        self.assertEqual(r["remaining_credits"], 6)
        self.assertEqual(term_of(r, "slot-1"), "Fall 2026")

    def test_prereq_loop_is_reported_not_crashed(self):
        r = build([course("A 1", prereqs=["B 1"]), course("B 1", prereqs=["A 1"]), course("C 1")])
        self.assertEqual({u["code"] for u in r["unplaced"]}, {"A 1", "B 1"})
        self.assertIsNone(r["graduation_term"])
        self.assertTrue(any(x["kind"] == "unplaced" for x in r["risks"]))

    def test_everything_done(self):
        r = build([course("A 100")], completed=["A 100"])
        self.assertEqual(r["terms"], [])
        self.assertIsNone(r["graduation_term"])

    def test_prereq_not_in_curriculum_is_assumed_but_warned(self):
        r = build([course("B 200", prereqs=["OUT 100"])])
        self.assertEqual(term_of(r, "B 200"), "Fall 2026")
        self.assertIn("isn't in your curriculum", r["terms"][0]["courses"][0]["warnings"][0])

    def test_first_term_uses_real_offerings(self):
        r = build([course("A 100"), course("B 100")], offered_first={"B 100"})
        self.assertEqual(term_of(r, "B 100"), "Fall 2026")
        self.assertEqual(term_of(r, "A 100"), "Spring 2027")
        self.assertEqual(r["real_offerings_term"], "Fall 2026")

    def test_same_season_option(self):
        cat = [course("S 100", year=1, term="Spring")]
        self.assertEqual(term_of(build(cat, same_season=True), "S 100"), "Spring 2027")
        self.assertEqual(term_of(build(cat, same_season=False), "S 100"), "Fall 2026")

    def test_summer_option_shortens_graduation(self):
        cat = [course(f"X {i}", credits=3) for i in range(1, 7)]
        no = build(cat, max_credits=3, start_term="Fall 2026")
        yes = build(cat, max_credits=3, start_term="Fall 2026", include_summer=True)
        self.assertEqual(no["graduation_term"], "Spring 2029")
        self.assertEqual(yes["graduation_term"], "Summer 2028")


class OverrideTests(unittest.TestCase):
    cat = [course("A 100"), course("B 200", prereqs=["A 100"])]

    def test_override_before_prereq_warns_but_is_kept(self):
        r = build(self.cat, overrides={"B 200": "Fall 2026", "A 100": "Spring 2027"})
        b = next(c for c in r["terms"][0]["courses"] if c["id"] == "B 200")
        self.assertTrue(b["fixed"])
        self.assertIn("planned later", b["warnings"][0])

    def test_override_same_term_warns(self):
        r = build(self.cat, overrides={"B 200": "Fall 2026", "A 100": "Fall 2026"})
        b = next(c for c in r["terms"][0]["courses"] if c["id"] == "B 200")
        self.assertIn("same term", b["warnings"][0])

    def test_free_courses_flow_around_overrides(self):
        r = build(self.cat, overrides={"A 100": "Spring 2027"})
        self.assertEqual(term_of(r, "B 200"), "Fall 2027")  # after its (moved) prereq

    def test_overload_via_override_warns(self):
        cat = [course("A 100", credits=9), course("B 100", credits=9)]
        r = build(cat, max_credits=12, overrides={"A 100": "Fall 2026", "B 100": "Fall 2026"})
        self.assertTrue(any("over your" in w for w in r["terms"][0]["warnings"]))

    def test_unknown_override_ignored(self):
        r = build(self.cat, overrides={"NOPE 1": "Fall 2026", "A 100": "Winter 2026"})
        self.assertEqual(term_of(r, "A 100"), "Fall 2026")


class RiskTests(unittest.TestCase):
    def test_long_chain_flagged(self):
        cat = [course("A 1"), course("B 1", prereqs=["A 1"]), course("C 1", prereqs=["B 1"]), course("D 1", prereqs=["C 1"])]
        r = build(cat)
        chain = next(x for x in r["risks"] if x["kind"] == "chain")
        self.assertEqual(chain["courses"], ["A 1", "B 1", "C 1", "D 1"])
        self.assertIn("sets your graduation term", chain["text"])

    def test_heavy_term_flagged(self):
        cat = [course(f"H {i}", credits=6) for i in range(3)]  # 18 credits
        r = build(cat, max_credits=18)
        self.assertTrue(any(x["kind"] == "heavy" for x in r["risks"]))


if __name__ == "__main__":
    unittest.main()


class SlotConsumptionTests(unittest.TestCase):
    def test_completed_elective_uses_a_slot(self):
        cat = [course("A 100"), course("E 100", required=False)]
        slots = [{"title": "Elective", "credits": 3, "year": 1, "term": "Fall"}, {"title": "Elective", "credits": 3, "year": 2, "term": "Fall"}]
        r = build(cat, completed=["E 100"], slots=slots)
        self.assertEqual(r["remaining_credits"], 3 + 3)   # A 100 + one slot left
        self.assertEqual(sum(1 for t in r["terms"] for c in t["courses"] if c["slot"]), 1)
        self.assertEqual([c["id"] for t in r["terms"] for c in t["courses"] if c["slot"]], ["slot-2"])  # ids don't shift
