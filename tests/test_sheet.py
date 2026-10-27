import unittest
from datetime import date, datetime

import sheet


class CountdownTests(unittest.TestCase):
    def test_future(self):
        c = sheet.countdown("2026-11-10", date(2026, 10, 28))
        self.assertEqual((c["state"], c["days"]), ("future", 13))
        self.assertIn("in 13 days", c["label"])
        self.assertIn("Tuesday 10 November 2026", c["label"])

    def test_singular_day(self):
        self.assertIn("in 1 day (", sheet.countdown("2026-10-29", date(2026, 10, 28))["label"])

    def test_today_and_past(self):
        self.assertEqual(sheet.countdown("2026-10-28", date(2026, 10, 28))["state"], "today")
        p = sheet.countdown("2026-10-20", datetime(2026, 10, 28, 15, 0))
        self.assertEqual((p["state"], p["days"]), ("past", 8))
        self.assertIn("8 days ago", p["label"])

    def test_missing_or_bad_date(self):
        self.assertIsNone(sheet.countdown(None, date(2026, 1, 1)))
        self.assertIsNone(sheet.countdown("", date(2026, 1, 1)))
        self.assertIsNone(sheet.countdown("next week", date(2026, 1, 1)))


class RowTests(unittest.TestCase):
    sec = {"code": "COSC 121", "section": "002", "title": "CS A", "days": ["Mon", "Wed"], "start": "09:00", "end": "10:30",
           "credits": 3.0, "instructor": "X", "location": "R101", "risk": "fills fast", "online": False}

    def test_row_with_backups_and_online(self):
        online = dict(self.sec, section="003", online=True, days=[], start=None, end=None, location=None)
        r = sheet.sheet_row(self.sec, [online])
        self.assertEqual(r["when"], "Mon/Wed 09:00-10:30")
        self.assertEqual(r["room"], "R101")
        self.assertEqual(r["backups"], [{"section": "003", "when": "Online / no fixed time", "room": ""}])

    def test_blank_fields_never_none(self):
        r = sheet.sheet_row({"code": "A 1", "section": "1", "days": [], "start": None, "end": None}, [])
        self.assertEqual((r["title"], r["room"], r["instructor"], r["risk"]), ("", "", "", "unknown"))

    def test_total(self):
        self.assertEqual(sheet.total_credits([{"credits": 3}, {"credits": 1.5}, {}]), 4.5)


if __name__ == "__main__":
    unittest.main()
