"""The plan PDF download (pdf_export.py + /api/plan/export/pdf)."""
import io
import unittest

import pdf_export

SECTIONS = [
    {"code": "COSC 221", "section": "001", "title": "Computer Science B", "days": ["Mon", "Thu"], "start": "08:30", "end": "10:00",
     "credits": 3, "instructor": "Dona Valy", "location": "B101", "online": False},
    {"code": "ICT 340", "section": "002", "title": "Vibe Coding – Conversational Software", "days": ["Tue", "Fri"], "start": "13:45",
     "end": "15:15", "credits": 3, "instructor": "Rottana Ly", "location": None, "online": False},
    {"code": "ENGL 301", "section": "A", "title": "Online seminar", "days": [], "start": None, "end": None, "credits": 3, "online": True},
]


class PlanPdfTest(unittest.TestCase):
    def test_builds_a_real_pdf_with_the_plan_in_it(self):
        data = pdf_export.plan_pdf(SECTIONS, program="Artificial Intelligence", term="Spring 2027", label="1", unmet=["ITM 380"])
        self.assertTrue(data.startswith(b"%PDF"))
        try:
            import pdfplumber
        except ImportError:
            return
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        for needle in ("Registration plan 1 - Spring 2027", "Artificial Intelligence", "COSC 221-001", "ICT 340", "B101",
                       "Online / TBA", "ITM 380", "9 credits"):
            self.assertIn(needle, text)
        self.assertIn("Vibe Coding - Conversational", text)            # the en dash was made safe for the PDF font

    def test_unusual_text_does_not_break_it(self):
        weird = [dict(SECTIONS[0], title="Crème • … ពាក្យ 中文", instructor=None, location="")]
        self.assertTrue(pdf_export.plan_pdf(weird).startswith(b"%PDF"))

    def test_many_sections_and_a_saturday_class_still_work(self):
        many = [dict(SECTIONS[0], code=f"C {i:03d}", days=["Sat"] if i == 0 else ["Mon"], start=f"{8 + i % 8:02d}:00", end=f"{9 + i % 8:02d}:00") for i in range(14)]
        self.assertTrue(pdf_export.plan_pdf(many).startswith(b"%PDF"))
        self.assertTrue(pdf_export.plan_pdf([SECTIONS[2]]).startswith(b"%PDF"))      # nothing timed: table only


if __name__ == "__main__":
    unittest.main()
