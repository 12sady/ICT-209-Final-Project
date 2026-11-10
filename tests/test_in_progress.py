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


if __name__ == "__main__":
    unittest.main()
