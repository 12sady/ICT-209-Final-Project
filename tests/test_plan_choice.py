"""Choosing between many plans: the metrics, filters and sorts shared by the Plan page and the AI tool."""
import unittest

try:
    import app as app_module
except ImportError:  # Flask missing
    app_module = None


def sec(code, days, start, end, **kw):
    return dict({"code": code, "section": "001", "days": days, "start": start, "end": end, "online": False, "risk": "unknown"}, **kw)


def plan(sections, **kw):
    days = {d for s in sections for d in s["days"]}
    base = {"sections": sections, "total_credits": 3 * len(sections), "days_on_campus": len(days), "earliest_start": min(int(s["start"][:2]) * 60 + int(s["start"][3:]) for s in sections),
            "gap_minutes": 0, "unmet_wishlist": [], "meets_min_credits": True}
    base.update(kw)
    return base


@unittest.skipIf(app_module is None, "Flask not installed")
class PlanChoiceTest(unittest.TestCase):
    A = plan([sec("A 1", ["Mon", "Thu"], "08:00", "09:30"), sec("B 1", ["Mon", "Thu"], "10:00", "11:30")], gap_minutes=30)              # early, Mon/Thu
    B = plan([sec("A 1", ["Tue", "Fri"], "13:00", "14:30"), sec("B 1", ["Tue", "Fri"], "15:00", "16:30")], gap_minutes=30)             # afternoons, Tue/Fri
    C = plan([sec("A 1", ["Mon", "Wed", "Fri"], "10:00", "11:30"), sec("B 1", ["Tue"], "10:00", "11:30", risk="fills fast")], gap_minutes=120,
             unmet_wishlist=["C 1"])
    PLANS = [A, B, C]

    def pick(self, **args):
        rows, n = app_module._choose_plans(self.PLANS, args)
        return [r[0] for r in rows], n

    def test_metrics(self):
        m = app_module._plan_metrics(self.A)
        self.assertEqual((m["days"], m["free_weekdays"], m["latest_end"], m["classes_before_9"]), (["Mon", "Thu"], ["Tue", "Wed", "Fri"], 690, 1))
        self.assertEqual(m["longest_day_minutes"], 210)
        self.assertEqual(app_module._plan_metrics(self.C)["crowded_sections"], 1)

    def test_no_filters_keeps_the_planners_order(self):
        self.assertEqual(self.pick(), ([0, 1, 2], 3))

    def test_free_day_and_time_filters(self):
        self.assertEqual(self.pick(free_days=["Fri"])[0], [0])
        self.assertEqual(self.pick(free_days=["fri", "Mon"])[0], [])                      # plan B uses Fri, A and C use Mon
        self.assertEqual(self.pick(start_after="09:00")[0], [1, 2])                       # A starts at 8:00
        self.assertEqual(self.pick(end_by="12:00")[0], [0, 2])
        self.assertEqual(self.pick(max_days=2)[0], [0, 1])
        self.assertEqual(self.pick(max_gap_minutes=60)[0], [0, 1])
        self.assertEqual(self.pick(keep_all=True)[0], [0, 1])                             # C drops a wishlist course

    def test_sorting(self):
        self.assertEqual(self.pick(sort_by="latest_start")[0][0], 1)                      # plan B starts at 13:00, the latest
        self.assertEqual(self.pick(sort_by="earliest_finish")[0], [0, 2, 1])
        self.assertEqual(self.pick(sort_by="least_crowded")[0][-1], 2)
        self.assertEqual(self.pick(sort_by="fewest_days")[0][0], 0)
        self.assertEqual(self.pick(sort_by="nonsense")[0], [0, 1, 2])                     # unknown sort: fall back to the planner's order

    def test_the_ai_tool_describes_the_filters(self):
        import ai
        tool = next(t for t in ai.TOOLS if t["name"] == "get_best_plans")
        props = tool["input_schema"]["properties"]
        for k in ("free_days", "start_after", "end_by", "max_days", "max_gap_minutes", "keep_all", "sort_by"):
            self.assertIn(k, props)
        self.assertIn("MANY schedules", ai.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
