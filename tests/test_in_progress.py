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
