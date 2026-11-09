"""scheduler.enumerate_plans(stats=...): the 'Why this schedule?' account of the search."""
import unittest

from scheduler import enumerate_plans, public_stats


def sec(code, section, days, start, end, credits=3, **kw):
    return {"code": code, "section": section, "days": days, "start": start, "end": end, "credits": credits, **kw}


REQ = {"completed": [], "prereqs": {}, "target_credits": {"min": 3, "max": 9},
       "preferences": {"avoid_before": "10:00", "avoid_days": ["Fri"]}}
OFFERINGS = [
    sec("ITM 360", "A", ["Mon", "Wed"], "10:00", "11:30"),
    sec("ITM 360", "B", ["Tue", "Thu"], "13:00", "14:30"),
    sec("COSC 331", "A", ["Mon", "Wed"], "10:30", "12:00"),     # clashes with ITM 360-A
    sec("COSC 331", "B", ["Mon", "Wed"], "14:00", "15:30"),
    sec("INFO 652", "A", ["Fri"], "13:00", "14:30"),             # day off
    sec("INFO 652", "B", ["Tue", "Thu"], "08:00", "09:30"),      # too early
    sec("INFO 652", "C", ["Tue", "Thu"], "13:00", "14:30"),      # clashes with ITM 360-B
    sec("INFO 652", "D", ["Tue"], "16:00", "17:30", risk="full"),
]
WISH = ["ITM 360", "COSC 331", "INFO 652"]


class SearchStatsTests(unittest.TestCase):
    def test_stats_do_not_change_the_plans(self):
        plain = enumerate_plans(REQ, OFFERINGS, WISH)
        stats = {}
        with_stats = enumerate_plans(REQ, OFFERINGS, WISH, stats=stats)
        self.assertEqual(plain, with_stats)

    def test_counts(self):
        stats = {}
        plans, *_ = enumerate_plans(REQ, OFFERINGS, WISH, stats=stats)
        s = public_stats(stats)
        self.assertNotIn("_seen", s)
        self.assertEqual(s["removed_before_search"], {"too_early": 1, "day_off": 1, "full": 1})
        by = {c["code"]: c for c in s["courses"]}
        self.assertEqual((by["INFO 652"]["sections"], by["INFO 652"]["usable"]), (4, 1))
        self.assertEqual(s["wishlist_courses"], 3)
        self.assertEqual(s["most_courses_that_fit"], 3)
        self.assertEqual(s["valid_plans"], len(plans))
        self.assertGreater(s["steps"], 0)
        self.assertGreater(s["rejected"]["time_clash"], 0)
        pairs = {frozenset((c["a"], c["b"])) for c in s["clashes"]}
        self.assertIn(frozenset(("ITM 360-A", "COSC 331-A")), pairs)
        self.assertTrue(s["exhausted"])

    def test_credit_limit_rejections(self):
        stats = {}
        req = dict(REQ, target_credits={"min": 3, "max": 6})
        enumerate_plans(req, OFFERINGS, WISH, stats=stats)
        self.assertEqual(stats["most_courses_that_fit"], 2)
        self.assertGreater(stats["rejected"]["over_credits"], 0)


if __name__ == "__main__":
    unittest.main()
