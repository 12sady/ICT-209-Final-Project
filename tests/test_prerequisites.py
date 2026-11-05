import unittest

import excel_importer as ex


class ParsePrerequisitesTest(unittest.TestCase):
    def test_none_and_blank_mean_no_prerequisites(self):
        for raw in ("NONE", "none", "", None, float("nan"), "N/A"):
            self.assertEqual(ex.parse_prerequisites(raw), [])

    def test_single_and_multiple_codes(self):
        self.assertEqual(ex.parse_prerequisites("ENGL 101"), ["ENGL 101"])
        self.assertEqual(ex.parse_prerequisites("ITEC 101,MATH 177"), ["ITEC 101", "MATH 177"])
        self.assertEqual(ex.parse_prerequisites("itec101; math 177 and COSC 111"), ["ITEC 101", "MATH 177", "COSC 111"])

    def test_non_code_text_is_kept_and_duplicates_dropped(self):
        self.assertEqual(ex.parse_prerequisites("Year 3/4"), ["Year 3/4"])
        self.assertEqual(ex.parse_prerequisites("COSC 111, COSC 111"), ["COSC 111"])

    def test_header_is_guessed(self):
        m = ex.guess_mapping(["Course Code", "Section", "Pre-requisite", "Course Title"])
        self.assertEqual(m.get("prerequisites"), "Pre-requisite")


try:
    import app as app_module
except ImportError:  # Flask missing
    app_module = None


@unittest.skipIf(app_module is None, "Flask not installed")
class SectionKeepsPrerequisitesTest(unittest.TestCase):
    base = {"code": "COSC 121", "section": "001", "title": "X", "credits": 3, "days": ["Mon"], "start": "09:00", "end": "10:30"}

    def test_list_and_text_forms_are_cleaned(self):
        self.assertEqual(app_module._clean_section({**self.base, "prerequisites": ["COSC 111"]})["prerequisites"], ["COSC 111"])
        self.assertEqual(app_module._clean_section({**self.base, "prerequisites": "itec101, MATH 177"})["prerequisites"], ["ITEC 101", "MATH 177"])
        self.assertEqual(app_module._clean_section(self.base)["prerequisites"], [])


if __name__ == "__main__":
    unittest.main()
