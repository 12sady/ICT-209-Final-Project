"""structure.py: counting completed courses against a program structure."""
import unittest

import structure

ST = {
    "total_credits": 15,
    "categories": [
        {"name": "Gen Ed", "credits": 3, "groups": [
            {"name": "Foundation", "courses": [{"code": "G 1", "name": "G one", "credits": 3}]},
            {"name": "Arts", "courses": [{"code": "G 2", "name": "G two", "credits": 3}]}]},
        {"name": "Major", "credits": 6, "courses": [{"code": "M 1", "credits": 3}, {"code": "M 2", "credits": 3}]},
        {"name": "Electives", "credits": 6, "courses": [{"code": "E 1", "credits": 3}, {"code": "E 2", "credits": 3}, {"code": "E 3", "credits": 3}]},
    ],
    "not_counted": [{"name": "Enrichment", "courses": [{"code": "G 1 (ENR)", "credits": 3}]}],
}


class EvaluateTests(unittest.TestCase):
    def test_any_listed_course_counts_and_extras_are_capped(self):
        ev = structure.evaluate(ST, ["G 1", "G 2", "M 1", "E 1", "E 2", "E 3"])
        rows = {r["category"]: r for r in ev["rows"]}
        self.assertEqual((rows["Gen Ed"]["done"], rows["Gen Ed"]["extra"]), (3, 3))     # 6 earned, 3 needed
        self.assertEqual((rows["Electives"]["done"], rows["Electives"]["extra"]), (6, 3))
        self.assertEqual(rows["Major"]["done"], 3)
        self.assertEqual(ev["done"], 12)
        self.assertEqual(ev["remaining"], 3)
        self.assertEqual(ev["percent"], 80.0)

    def test_required_only_when_list_equals_target(self):
        ev = structure.evaluate(ST, ["M 1"])
        rows = {r["category"]: r for r in ev["rows"]}
        self.assertTrue(rows["Major"]["all_required"])
        self.assertFalse(rows["Electives"]["all_required"])
        self.assertEqual(ev["remaining_required"], ["M 2"])

    def test_not_counted_and_unknown_courses(self):
        ev = structure.evaluate(ST, ["G 1 (ENR)", "X 9", "m1"])
        self.assertEqual(ev["not_counted"], [
            {"group": "Enrichment (not counted)", "courses": ["G 1 (ENR)"]},
            {"group": structure.NOT_IN_STRUCTURE, "courses": ["X 9"]}])
        self.assertEqual(ev["done"], 3)        # "m1" matches M 1 (spacing / case ignored)


class OverlayTests(unittest.TestCase):
    def test_categories_required_flags_and_added_courses(self):
        req = {"completed": ["G 1"], "catalog": [
            {"code": "G 1", "name": "G one", "category": "General Education (Required)", "credits": 3, "required": True},
            {"code": "G 2", "name": "G two", "category": "General Education (Required)", "credits": 3, "required": True},
            {"code": "E 1", "name": "E one", "category": "Major Electives", "credits": 3, "required": True, "plan_year": 3},
            {"code": "PHIL 1", "name": "Old plan course", "category": "Major", "credits": 3, "required": True},
        ]}
        out = structure.overlay(req, ST)
        cat = {c["code"]: c for c in out["catalog"]}
        self.assertEqual((cat["G 1"]["category"], cat["G 1"]["sub_category"]), ("Gen Ed", "Foundation"))
        self.assertFalse(cat["G 2"]["required"])          # Gen Ed already complete -> nothing more needed
        self.assertTrue(cat["E 1"]["required"])           # Electives not complete: keep the plan's flag
        self.assertEqual(cat["E 1"]["plan_year"], 3)      # sample-plan order kept for the Roadmap
        self.assertEqual(cat["PHIL 1"]["category"], structure.NOT_IN_STRUCTURE)
        self.assertFalse(cat["PHIL 1"]["required"])
        self.assertTrue(cat["M 2"]["required"])           # added from the structure, all-required category
        self.assertEqual(cat["G 1 (ENR)"]["category"], "Enrichment (not counted)")
        self.assertEqual(out["required_remaining"], ["E 1", "M 1", "M 2"])
        self.assertEqual(req["catalog"][0]["category"], "General Education (Required)")   # input unchanged


class RealDataTests(unittest.TestCase):
    def test_software_development_file_adds_up(self):
        st = structure.get("software-development")
        if st is None:
            self.skipTest("data/program_structures.json not found from this folder")
        self.assertEqual(sum(c["credits"] for c in st["categories"]), st["total_credits"])
        major = [c for c in structure.categories(st) if c["name"] == "Major"][0]
        self.assertTrue(major["all_required"])


if __name__ == "__main__":
    unittest.main()
