"""Academic dates (holidays, deadlines, exams) in the .ics export."""
import unittest

try:
    import app as app_module
except ImportError:  # Flask missing
    app_module = None

CAL = {
    "term": "Spring 2027", "start": "2027-01-11", "end": "2027-04-30",
    "breaks": [{"name": "Lunar New Year", "start": "2027-02-05", "end": "2027-02-05"}],
    "registration_date": None,
    "events": [
        {"name": "Last day to ADD/DROP courses", "start": "2027-01-15", "end": "2027-01-15", "kind": "deadline"},
        {"name": "Khmer New Year (campus closed)", "start": "2027-04-14", "end": "2027-04-16", "kind": "holiday"},
        {"name": "Final exam period", "start": "2027-05-03", "end": "2027-05-07", "kind": "exam"},
    ],
}
SECTION = {"code": "COSC 221", "section": "001", "title": "CS B", "days": ["Mon", "Thu"], "start": "12:00", "end": "13:30",
           "credits": 3, "instructor": "X", "online": False, "location": None, "start_date": "2027-01-11", "end_date": "2027-04-30"}


@unittest.skipIf(app_module is None, "Flask not installed")
class CalendarDatesTest(unittest.TestCase):
    def build(self, plan, cal=CAL):
        return app_module._build_plan_ics(plan, cal)

    def test_classes_stay_one_repeating_series_and_dates_are_all_day_events(self):
        ics, info = self.build({"sections": [SECTION]})
        self.assertEqual(ics.count("RRULE:FREQ=WEEKLY;BYDAY=MO,TH"), 1)               # still ONE series per class
        self.assertEqual(ics.count("BEGIN:VEVENT"), 1 + 3)
        self.assertEqual(info["calendar_events"], 3)
        self.assertIn("DTSTART;VALUE=DATE:20270414", ics)
        self.assertIn("DTEND;VALUE=DATE:20270417", ics)                                # 14-16 April: end date is exclusive
        self.assertIn("DTSTART;VALUE=DATE:20270503", ics)
        self.assertIn("TRANSP:TRANSPARENT", ics)

    def test_deadlines_get_reminders_other_dates_do_not(self):
        ics, _ = self.build({"sections": []})
        self.assertIn("SUMMARY:Last day to ADD/DROP courses", ics)            # the name already says "Last day", so no "Deadline:" prefix
        self.assertEqual(ics.count("BEGIN:VALARM"), 2)                                 # only the one deadline, two reminders
        self.assertIn("TRIGGER:-PT15H", ics)

    def test_dates_only_and_opt_out(self):
        ics, info = self.build({"sections": [SECTION], "dates_only": True})
        self.assertNotIn("RRULE", ics)
        self.assertEqual((info["exported"], info["calendar_events"]), (0, 3))
        ics, info = self.build({"sections": [SECTION], "include_calendar": False})
        self.assertEqual((info["exported"], info["calendar_events"]), (1, 0))
        self.assertNotIn("VALUE=DATE", ics)

    def test_older_calendars_without_events_fall_back_to_breaks_and_term_dates(self):
        old = dict(CAL, events=[])
        ics, info = self.build({"sections": []}, old)
        self.assertEqual(info["calendar_events"], 3)                                   # the break + first and last day of classes
        self.assertIn("Lunar New Year", ics)
        self.assertIn("First day of classes", ics)

    def test_ids_are_stable_so_importing_twice_does_not_duplicate(self):
        a, _ = self.build({"sections": [SECTION]})
        b, _ = self.build({"sections": [SECTION]})
        uids = lambda t: sorted(l for l in t.splitlines() if l.startswith("UID:"))
        self.assertEqual(uids(a), uids(b))

    def test_calendar_validation_keeps_events_and_rejects_bad_ones(self):
        out = app_module._clean_calendar({"term": "T", "start": "2027-01-11", "end": "2027-04-30",
                                          "events": [{"name": "X", "start": "2027-03-07", "kind": "DEADLINE"},
                                                     {"name": "Y", "start": "2027-02-01", "end": "2027-02-03", "kind": "weird"}]})
        self.assertEqual([(e["name"], e["kind"], e["end"]) for e in out["events"]], [("Y", "other", "2027-02-03"), ("X", "deadline", "2027-03-07")])
        with self.assertRaises(ValueError):
            app_module._clean_calendar({"events": [{"name": "No date"}]})
        with self.assertRaises(ValueError):
            app_module._clean_calendar({"events": [{"name": "Backwards", "start": "2027-03-07", "end": "2027-03-01"}]})


if __name__ == "__main__":
    unittest.main()
