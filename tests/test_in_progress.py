import unittest

import scheduler


class InProgressPrereqTest(unittest.TestCase):
    req = {"completed": ["A 100"], "in_progress": ["B 200"], "prereqs": {"B 200": ["A 100"], "C 300": ["B 200"], "D 400": ["C 300"]}}

    def test_in_progress_satisfies_a_prerequisite(self):
        self.assertTrue(scheduler.prereqs_met("C 300", self.req))
        self.assertEqual(scheduler.missing_prereqs("C 300", self.req), [])

    def test_only_one_step_ahead(self):
        self.assertFalse(scheduler.prereqs_met("D 400", self.req))              # C 300 is neither done nor in progress
        self.assertEqual(scheduler.missing_prereqs("D 400", self.req), ["C 300"])

    def test_old_files_without_in_progress_still_work(self):
        old = {"completed": ["A 100"], "prereqs": {"B 200": ["A 100"], "C 300": ["B 200"]}}
        self.assertFalse(scheduler.prereqs_met("C 300", old))


class WishlistAndPlannerTest(unittest.TestCase):
    req = {"completed": ["A 100"], "in_progress": ["B 200"], "prereqs": {"C 300": ["B 200"]}}
    offerings = [{"code": c} for c in ("A 100", "B 200", "C 300")]

    def test_a_wishlisted_retake_is_still_planned(self):
        # Adding a finished / in-progress course is allowed (a deliberate retake); the wishlist flags it.
        slots, _, blocked, none = scheduler.build_slots(self.req, ["A 100", "B 200", "C 300"], self.offerings)
        self.assertEqual([s["label"] for s in slots], ["A 100", "B 200", "C 300"])
        self.assertEqual((blocked, none), ([], []))


class GradeReportInProgressTest(unittest.TestCase):
    def test_current_courses_not_in_the_curriculum_are_added_as_in_progress(self):
        import grade_report
        req = {"completed": ["DONE 100"], "in_progress": [],
               "catalog": [{"code": "KNOWN 100", "name": "k", "category": "Major", "credits": 3, "required": True}]}
        new, added = grade_report.add_in_progress(req, [
            {"code": "KNOWN 100", "name": "k", "credits": 3},
            {"code": "NEW 200", "name": "A new one", "credits": 3},
            {"code": "DONE 100", "name": "already done", "credits": 3},
            {"code": "", "name": "no code"}])
        self.assertEqual(added, 1)
        self.assertEqual(new["in_progress"], ["KNOWN 100", "NEW 200"])
        extra = next(c for c in new["catalog"] if c["code"] == "NEW 200")
        self.assertEqual((extra["category"], extra["credits"], extra["required"]), (grade_report.EXTRA_CATEGORY, 3, False))
        self.assertEqual(len(new["catalog"]), 2)                                  # the known and the finished ones are not duplicated


try:
    import app as app_module
except ImportError:  # Flask missing
    app_module = None


@unittest.skipIf(app_module is None, "Flask not installed")
class OutsideCurriculumTest(unittest.TestCase):
    """A course that isn't on the degree audit (e.g. ICT 340) can still be taken as an elective: its
    prerequisites come from the registrar sheet, and a course in progress counts as done."""
    sheet = [
        {"code": "ICT 340", "prerequisites": ["COSC 111"]}, {"code": "ICT 340", "prerequisites": ["COSC 111"]},
        {"code": "XYZ 401", "prerequisites": ["Year 3/4", "ABC 100"]}, {"code": "FREE 100", "prerequisites": []},
    ]

    def test_codes_only_and_no_duplicates(self):
        self.assertEqual(app_module._sheet_prereqs(self.sheet), {"ICT 340": ["COSC 111"], "XYZ 401": ["ABC 100"]})

    def test_in_progress_prerequisite_counts(self):
        pre = app_module._sheet_prereqs(self.sheet)
        self.assertEqual(app_module._sheet_missing("ICT 340", {"completed": [], "in_progress": []}, pre), ["COSC 111"])
        self.assertEqual(app_module._sheet_missing("ICT 340", {"completed": [], "in_progress": ["COSC 111"]}, pre), [])
        self.assertEqual(app_module._sheet_missing("ICT 340", {"completed": ["COSC 111"]}, pre), [])
        self.assertEqual(app_module._sheet_missing("FREE 100", {}, pre), [])
        self.assertEqual(app_module._sheet_missing("ICT 340", {"preferences": {"ignore_prereqs": True}}, pre), [])


if __name__ == "__main__":
    unittest.main()
