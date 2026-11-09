import unittest

import excel_importer


class CodePrefixTest(unittest.TestCase):
    def test_csci_becomes_cosc(self):
        self.assertEqual(excel_importer.normalize_code_prefix("CSCI 111"), "COSC 111")
        self.assertEqual(excel_importer.normalize_code_prefix("csci 241"), "COSC 241")

    def test_other_prefixes_unchanged(self):
        for code in ("COSC 121", "ITEC 101", "HIST 131"):
            self.assertEqual(excel_importer.normalize_code_prefix(code), code)

    def test_cross_listed_row_gives_one_cosc_row(self):
        import os
        import tempfile
        import pandas as pd
        df = pd.DataFrame([{
            "Course Code": "COSC 111/CSCI 111", "Section": "001/001", "Course Title": "Computer Science Survey",
            "Days": "Mon/Thu", "Start": "12:00", "End": "13:30", "Credits": 3, "Instructor": "X",
        }])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sheet.xlsx")
            df.to_excel(path, index=False)
            mapping = excel_importer.guess_mapping(list(df.columns))
            rows, errors = excel_importer.parse_with_mapping(path, mapping)
        self.assertEqual(errors, [])
        self.assertEqual([r["code"] for r in rows], ["COSC 111"])


if __name__ == "__main__":
    unittest.main()
