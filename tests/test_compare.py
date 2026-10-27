import unittest

import compare


def sec(code, days, start, end, credits=3, section="001", risk="unknown", **kw):
    d = {"code": code, "section": section, "days": days, "start": start, "end": end,
         "credits": credits, "risk": risk, "online": False}
    d.update(kw)
    return d


class MetricsTests(unittest.TestCase):
    def test_basic_metrics(self):
        m = compare.plan_metrics([
            sec("A 100", ["Mon", "Wed"], "09:00", "10:30"),
            sec("B 100", ["Mon"], "13:00", "14:00"),
            sec("C 100", ["Fri"], "08:00", "09:00"),
        ], wishlist=["A 100", "B 100", "C 100", "D 100"])
        self.assertEqual(m["total_credits"], 9)
        self.assertEqual(m["days"], ["Mon", "Wed", "Fri"])
        self.assertEqual(m["days_on_campus"], 3)
        self.assertEqual(m["earliest_start"], 8 * 60)
        self.assertEqual(m["latest_end"], 14 * 60)
        self.assertEqual(m["longest_gap"], 150)          # Mon 10:30 -> 13:00
        self.assertEqual(m["total_wait"], 150)
        self.assertEqual(m["left_out"], ["D 100"])

    def test_overlap_gap_never_negative(self):
        m = compare.plan_metrics([sec("A 1", ["Mon"], "09:00", "11:00"), sec("B 1", ["Mon"], "10:00", "12:00")])
        self.assertEqual(m["total_wait"], 0)

    def test_online_sections_have_no_time(self):
        m = compare.plan_metrics([sec("A 1", [], None, None, online=True), sec("B 1", ["Tue"], "10:00", "11:00")])
        self.assertEqual(m["online"], ["A 1-001"])
        self.assertEqual(m["days_on_campus"], 1)

    def test_empty_plan(self):
        m = compare.plan_metrics([])
        self.assertIsNone(m["earliest_start"])
        self.assertEqual(m["days_on_campus"], 0)
        self.assertFalse(m["has_seat_data"])

    def test_two_sections_same_time_is_not_a_crash(self):
        m = compare.plan_metrics([sec("A 1", ["Mon"], "09:00", "10:00"), sec("B 1", ["Mon"], "09:00", "10:00")])
        self.assertEqual(m["days_on_campus"], 1)

    def test_seat_risk(self):
        m = compare.plan_metrics([sec("A 1", ["Mon"], "09:00", "10:00", risk="low", seats_total=30, seats_available=20),
                                  sec("B 1", ["Tue"], "09:00", "10:00", risk="fills fast")])
        self.assertEqual(m["worst_risk"], "fills fast")
        self.assertEqual(m["risky_sections"], 1)
        self.assertEqual(m["seat_risk"][0]["seats"], "20/30")


class CompareTests(unittest.TestCase):
    def two(self):
        a = compare.plan_metrics([sec("A 1", ["Mon", "Wed"], "08:00", "09:30"), sec("B 1", ["Mon", "Wed"], "12:00", "13:30")])
        b = compare.plan_metrics([sec("A 1", ["Mon", "Fri"], "10:00", "11:30"), sec("B 1", ["Tue", "Thu"], "10:00", "11:30")])
        return a, b

    def test_winners_and_reasons(self):
        a, b = self.two()
        best = compare.compare_plans([a, b])
        self.assertEqual(best["days_on_campus"]["winners"], [0])   # Mon/Wed = 2 days vs 4
        self.assertEqual(best["earliest_start"]["winners"], [1])   # 10:00 beats 08:00
        self.assertEqual(best["total_wait"]["winners"], [1])       # a waits 150 min on Mon and Wed
        self.assertIn("fewest days", best["days_on_campus"]["reason"])

    def test_same_count_different_courses_is_flagged(self):
        a = compare.plan_metrics([sec("A 1", ["Mon"], "09:00", "10:00")], wishlist=["A 1", "B 1"])
        b = compare.plan_metrics([sec("B 1", ["Tue"], "09:00", "10:00")], wishlist=["A 1", "B 1"])
        best = compare.compare_plans([a, b])
        self.assertEqual(best["left_out"]["winners"], [])
        self.assertTrue(best["left_out"]["different"])
        same = compare.compare_plans([a, a])
        self.assertNotIn("left_out", same)             # identical sets: truly no difference

    def test_ties_have_no_winner(self):
        a, _ = self.two()
        best = compare.compare_plans([a, a])
        self.assertEqual(best, {})

    def test_seat_risk_needs_data_for_every_plan(self):
        a = compare.plan_metrics([sec("A 1", ["Mon"], "09:00", "10:00", risk="low")])
        b = compare.plan_metrics([sec("A 1", ["Tue"], "09:00", "10:00")])
        self.assertNotIn("worst_risk", compare.compare_plans([a, b]))
        c = compare.plan_metrics([sec("A 1", ["Tue"], "09:00", "10:00", risk="fills fast")])
        self.assertEqual(compare.compare_plans([a, c])["worst_risk"]["winners"], [0])

    def test_credit_fit_prefers_range_then_closest_to_max(self):
        low = compare.plan_metrics([sec("A 1", ["Mon"], "09:00", "10:00", credits=9)])
        ok = compare.plan_metrics([sec("A 1", ["Mon"], "09:00", "10:00", credits=15)])
        full = compare.plan_metrics([sec("A 1", ["Mon"], "09:00", "10:00", credits=17)])
        self.assertEqual(compare.compare_plans([low, ok, full])["total_credits"]["winners"], [2])
        self.assertEqual(compare.compare_plans([low, ok])["total_credits"]["winners"], [1])

    def test_plan_key_is_order_independent(self):
        x, y = sec("A 1", ["Mon"], "09:00", "10:00"), sec("B 1", ["Tue"], "09:00", "10:00")
        self.assertEqual(compare.plan_key([x, y]), compare.plan_key([y, x]))


if __name__ == "__main__":
    unittest.main()
