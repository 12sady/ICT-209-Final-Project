"""End-to-end checks through Flask's test client, on a throw-away data folder
(never your real data/). Skipped automatically if Flask isn't installed for the
Python running the tests."""
import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest

try:
    import flask  # noqa: F401
    HAVE_FLASK = True
except ImportError:
    HAVE_FLASK = False

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CURRICULUM = {
    "program": "Test Program", "program_id": "", "semester": "Fall 2026",
    "completed": ["A 100"], "completed_semesters": {"A 100": "Fall 2025"},
    "catalog": [
        {"code": "A 100", "name": "Intro", "category": "Gen Ed", "credits": 3, "required": True, "hard_prereqs": [], "plan_year": 1, "plan_term": "Fall"},
        {"code": "B 200", "name": "Second", "category": "Major", "credits": 3, "required": True, "hard_prereqs": ["A 100"], "plan_year": 1, "plan_term": "Spring"},
        {"code": "C 300", "name": "Third", "category": "Major", "credits": 3, "required": True, "hard_prereqs": ["B 200"], "plan_year": 2, "plan_term": "Fall"},
        {"code": "E 100", "name": "Some elective", "category": "Electives", "credits": 3, "required": False, "hard_prereqs": []},
    ],
    "prereqs": {"B 200": ["A 100"], "C 300": ["B 200"]},
    "elective_slots": [{"title": "Elective", "credits": 3, "year": 2, "term": "Fall"}],
    "target_credits": {"min": 3, "max": 6},
    "preferences": {"avoid_before": "", "avoid_days": [], "priority_courses": [], "ignore_prereqs": False},
}


def sec(code, section, days, start, end, title="T", **kw):
    d = {"code": code, "section": section, "title": title, "days": days, "start": start, "end": end, "credits": 3.0,
         "instructor": "X", "seats_total": None, "seats_available": None, "risk": "unknown", "online": False,
         "department": "TST", "location": None, "start_date": None, "end_date": None}
    d.update(kw)
    return d


OFFERINGS = [
    sec("B 200", "001", ["Mon", "Wed"], "09:00", "10:30"),
    sec("B 200", "002", ["Tue", "Thu"], "09:00", "10:30"),
    sec("C 300", "001", ["Mon", "Wed"], "09:00", "10:30"),   # same time as B 200-001
    sec("E 100", "001", ["Fri"], "13:00", "14:30"),
]


@unittest.skipUnless(HAVE_FLASK, "Flask isn't installed for this Python")
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_cwd = os.getcwd()
        cls.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(cls.tmp, "data"))
        with open(os.path.join(cls.tmp, "data", "course_offerings.json"), "w") as f:
            json.dump(OFFERINGS, f)
        os.chdir(cls.tmp)
        sys.path.insert(0, ROOT)
        cls.app = importlib.import_module("app")
        cls.app.app.config["TESTING"] = True
        cls.admin = cls._signup("admin1")
        cls.student = cls._signup("student1")
        for c in (cls.admin, cls.student):
            assert c.put("/api/curriculum", json=CURRICULUM).status_code == 200
        assert cls.student.post("/api/wishlist", json={"code": "B 200"}).status_code == 200

    @classmethod
    def _signup(cls, name):
        c = cls.app.app.test_client()
        r = c.post("/signup", data={"username": name, "password": "secret1", "confirm": "secret1"})
        assert r.status_code == 302, r.data
        return c

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.old_cwd)
        sys.path.remove(ROOT)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- permissions ----
    def test_non_admin_cannot_write_shared_data(self):
        row = sec("Z 100", "001", ["Mon"], "09:00", "10:00")
        self.assertEqual(self.student.post("/api/offerings/section", json={"section": row}).status_code, 403)
        self.assertEqual(self.student.put("/api/academic-calendar", json={"term": "Fall 2026"}).status_code, 403)
        self.assertEqual(self.student.post("/api/programs", json={"name": "X"}).status_code, 403)
        self.assertEqual(self.admin.put("/api/academic-calendar", json={"term": "Fall 2026"}).status_code, 200)

    def test_new_pages_need_login(self):
        anon = self.app.app.test_client()
        for url in ("/", "/gpa", "/compare", "/roadmap", "/api/gpa", "/api/roadmap", "/api/dashboard"):
            self.assertIn(anon.get(url).status_code, (302, 401), url)

    def test_use_plan_fills_year_and_semester_only_when_empty(self):
        prog = {"name": "Fill Test", "degree": "Single", "credit_total": 6, "terms": [
            {"year": 1, "term": "Fall", "courses": [{"code": "ZZ 100", "title": "One", "credits": 3}]},
            {"year": 2, "term": "Fall", "courses": [{"code": "ZZ 200", "title": "Two", "credits": 3}]}]}
        pid = self.admin.post("/api/programs", json=prog).get_json()["program"]["id"]
        self.admin.put("/api/academic-calendar", json={"term": "Fall 2026"})
        empty = self._signup("fillempty")
        r = empty.post("/api/curriculum/from-program", json={"program_id": pid}).get_json()
        self.assertEqual(sorted(r["filled"]), ["semester", "year"])
        got = empty.get("/api/curriculum").get_json()
        self.assertEqual((got["year"], got["semester"]), ("1st year", "Fall 2026"))
        typed = self._signup("filltyped")
        body = json.loads(json.dumps(CURRICULUM)); body["year"] = "Junior"; body["semester"] = "Spring 2027"
        typed.put("/api/curriculum", json=body)
        r = typed.post("/api/curriculum/from-program", json={"program_id": pid}).get_json()
        self.assertEqual(r["filled"], [])
        got = typed.get("/api/curriculum").get_json()
        self.assertEqual((got["year"], got["semester"]), ("Junior", "Spring 2027"))     # untouched
        self.admin.put("/api/academic-calendar", json={"term": "Fall 2026"})

    def test_mark_through_endpoint(self):
        c = self.student
        r = c.post("/api/curriculum/through", json={"year": 1, "term": "Spring"}).get_json()
        self.assertEqual(r["codes"], ["A 100", "B 200"])
        self.assertEqual(r["new"], ["B 200"])                 # A 100 is already completed
        self.assertEqual(c.post("/api/curriculum/through", json={"year": 9, "term": "Winter"}).status_code, 400)

    def test_demo_student_admin_only_and_fully_filled(self):
        self.assertEqual(self.student.post("/api/admin/demo-student").status_code, 403)
        self.assertEqual(self.admin.post("/api/admin/demo-student").status_code, 400)       # no AI plan published yet
        prog = {"name": "Artificial Intelligence", "degree": "Single", "credit_total": 12, "terms": [
            {"year": 1, "term": "Fall", "courses": [{"code": "AA 100", "title": "Intro", "credits": 3, "category": "General Education"}]},
            {"year": 1, "term": "Spring", "courses": [{"code": "BB 200", "title": "Second", "credits": 3, "prereqs": ["AA 100"]}]},
            {"year": 2, "term": "Fall", "courses": [{"code": "CC 300", "title": "Third", "credits": 3, "prereqs": ["BB 200"]}]},
            {"year": 3, "term": "Fall", "courses": [{"code": "DD 400", "title": "Fourth", "credits": 3, "prereqs": ["CC 300"]}]}]}
        self.assertEqual(self.admin.post("/api/programs", json=prog).status_code, 200)
        r = self.admin.post("/api/admin/demo-student")
        self.assertEqual(r.status_code, 200, r.data)
        d = r.get_json()
        self.assertEqual(d["summary"]["completed"], 3)
        demo_client = self.app.app.test_client()
        ok = demo_client.post("/login", data={"username": d["username"], "password": d["password"]})
        self.assertEqual(ok.status_code, 302)
        g = demo_client.get("/api/gpa").get_json()
        self.assertEqual(len(g["entries"]), 3)
        self.assertEqual(g["ungraded"], [])
        self.assertIsNotNone(g["summary"]["gpa"])
        self.assertEqual(demo_client.get("/api/dashboard").get_json()["progress"]["done"], 9)
        second = self.admin.post("/api/admin/demo-student").get_json()
        self.assertNotEqual(second["username"], d["username"])                              # each press = a new account

    def test_registration_sheet(self):
        c = self.student
        self.assertIsNone(c.get("/api/registration-sheet").get_json()["plan"])               # no active plan yet
        self.assertEqual(self.admin.put("/api/academic-calendar", json={"term": "Fall 2026", "registration_date": "soon"}).status_code, 400)
        self.assertEqual(self.student.put("/api/academic-calendar", json={"registration_date": "2099-01-01"}).status_code, 403)
        self.assertEqual(self.admin.put("/api/academic-calendar", json={"term": "Fall 2026", "registration_date": "2099-01-01"}).status_code, 200)
        c.post("/api/plan/active", json={"sections": [{"code": "B 200", "section": "001"}]})
        d = c.get("/api/registration-sheet").get_json()
        self.assertEqual(d["countdown"]["state"], "future")
        row = d["plan"]["rows"][0]
        self.assertEqual((row["code"], row["section"], row["when"]), ("B 200", "001", "Mon/Wed 09:00-10:30"))
        self.assertEqual([b["section"] for b in row["backups"]], ["002"])                      # the Tue/Thu section is the backup
        self.assertEqual(d["plan"]["total_credits"], 3)
        c.delete("/api/plan/active")
        self.admin.put("/api/academic-calendar", json={"term": "Fall 2026"})

    def test_advisor_summary(self):
        c = self.admin
        c.put("/api/grades", json={"grades": {"A 100": "A"}})
        d = c.get("/api/advisor-summary").get_json()
        self.assertTrue(d["has_curriculum"])
        self.assertEqual(d["progress"]["done"], 3)
        self.assertEqual(d["gpa"]["value"], 4.0)
        self.assertEqual([x["code"] for x in d["gpa"]["courses"]], ["A 100"])
        self.assertEqual(d["gpa"]["semesters"][0]["semester"], "Fall 2025")
        self.assertTrue(d["roadmap"]["terms"])
        self.assertTrue(all("label" in t and "courses" in t for t in d["roadmap"]["terms"]))
        self.assertIsNone(d["plan"])
        c.put("/api/grades", json={"grades": {"A 100": ""}})
        brand_new = self._signup("summarynew")
        self.assertFalse(brand_new.get("/api/advisor-summary").get_json()["has_curriculum"])
        self.assertEqual(brand_new.get("/advisor-summary").status_code, 200)

    # ---- GPA ----
    def test_grades_roundtrip_and_survive_curriculum_save(self):
        c = self.student
        self.assertEqual(c.put("/api/grades", json={"grades": {"A 100": "a-"}}).status_code, 200)
        g = c.get("/api/gpa").get_json()
        self.assertAlmostEqual(g["summary"]["gpa"], 3.67)
        stale = json.loads(json.dumps(CURRICULUM))          # a Curriculum page that has never seen grades
        self.assertEqual(c.put("/api/curriculum", json=stale).status_code, 200)
        self.assertEqual(c.get("/api/curriculum").get_json()["grades"], {"A 100": "A-"})
        self.assertEqual(c.put("/api/grades", json={"grades": {"A 100": "Z"}}).status_code, 400)
        self.assertEqual(c.put("/api/grades", json={"grades": {"B 200": "A"}}).status_code, 400)   # not completed
        self.assertEqual(c.put("/api/grades", json={"grades": {"A 100": ""}}).status_code, 200)
        self.assertIsNone(c.get("/api/gpa").get_json()["summary"]["gpa"])

    def test_grade_report_import(self):
        import io
        from unittest import mock
        from tests.test_grade_report import PAGES
        c = self._signup("gradereport")
        self.assertEqual(c.put("/api/curriculum", json=CURRICULUM).status_code, 200)
        bad = c.post("/api/grade-report/preview", data={"file": (io.BytesIO(b"hello"), "x.pdf")})
        self.assertEqual(bad.status_code, 400)
        with mock.patch.object(self.app.grade_report, "read_pdf", return_value=PAGES):
            r = c.post("/api/grade-report/preview", data={"file": (io.BytesIO(b"%PDF-1.4 fake"), "report.pdf")})
        self.assertEqual(r.status_code, 200, r.data)
        rows = {x["report_code"]: x for x in r.get_json()["rows"]}
        self.assertEqual(rows["ICT 209"]["status"], "in_progress")
        self.assertIsNone(c.get("/api/curriculum").get_json().get("grades"))        # preview saved nothing
        picked = [{"code": "A 100", "grade": "B+", "term": "Fall 2025"},
                  {"code": "CLD 374", "grade": "B+", "term": "Summer 2025", "add": {"name": "Cloud", "credits": 3}}]
        a = c.post("/api/grade-report/apply", json={"courses": picked})
        self.assertEqual(a.status_code, 200, a.data)
        cur = c.get("/api/curriculum").get_json()
        self.assertIn("CLD 374", cur["completed"])
        self.assertEqual(cur["grades"], {"A 100": "B+", "CLD 374": "B+"})
        self.assertAlmostEqual(c.get("/api/gpa").get_json()["summary"]["gpa"], 3.33)
        self.assertEqual(c.post("/api/grade-report/apply", json={"courses": [{"code": "B 200", "grade": "RG"}]}).status_code, 400)

    def test_degree_audit_import(self):
        import io
        from unittest import mock
        from tests.test_degree_audit import PAGES
        c = self._signup("degreeaudit")
        self.assertEqual(c.put("/api/curriculum", json=CURRICULUM).status_code, 200)
        self.assertEqual(c.post("/api/degree-audit/preview", data={"file": (io.BytesIO(b"hello"), "x.pdf")}).status_code, 400)
        fake = lambda: (io.BytesIO(b"%PDF-1.4 fake"), "audit.pdf")
        with mock.patch.object(self.app.degree_audit, "read_pdf", return_value=PAGES):
            r = c.post("/api/degree-audit/preview", data={"file": fake()})
            self.assertEqual(r.status_code, 200, r.data)
            self.assertEqual(r.get_json()["counts"]["passed"], 4)
            self.assertNotIn("audit_structure", c.get("/api/curriculum").get_json())      # preview saved nothing
            a = c.post("/api/degree-audit/apply", data={"file": fake()})
        self.assertEqual(a.status_code, 200, a.data)
        cur = c.get("/api/curriculum").get_json()
        self.assertEqual(len(cur["catalog"]), 9)
        self.assertEqual(cur["grades"]["ENGL 101"], "A")
        rows = {r["category"]: r["done"] for r in cur["structure_progress"]["rows"]}
        self.assertEqual(rows, {"Major": 0, "Major Electives": 0, "General Education": 7, "Core/Major": 0})
        self.assertEqual(cur["structure_progress"]["total"], 24)
        groups = {g["group"]: g["courses"] for g in cur["structure_progress"]["not_counted"]}
        self.assertEqual(groups["Not counted by the SIS audit (not counted)"], ["ZZZ 110"])
        self.assertEqual(groups["Not in program structure"], ["A 100"])          # passed earlier, not on the audit
        self.assertEqual(c.put("/api/curriculum", json=cur).status_code, 200)               # GET -> PUT keeps the audit structure
        again = c.get("/api/curriculum").get_json()
        self.assertEqual(again["structure_progress"]["total"], 24)
        # picking a sample plan again drops the audit's structure
        self.assertEqual(c.put("/api/curriculum", json={k: v for k, v in again.items() if k != "audit_structure"}).status_code, 200)

    def _user_id(self, client):
        with client.session_transaction() as sess:
            return sess["user_id"]

    def test_program_structure_counts_by_category(self):
        import shutil as _sh
        _sh.copy(os.path.join(ROOT, "data", "program_structures.json"), os.path.join("data", "program_structures.json"))
        try:
            c = self._signup("structure1")
            cur = json.loads(json.dumps(CURRICULUM))
            cur["program_id"] = "software-development"
            cur["completed"] = ["COSC 111", "ENGL 101", "ENGL 101 (ENR)", "AIN 320"]
            cur["catalog"].append({"code": "COSC 111", "name": "CS Survey", "category": "Major", "credits": 3, "required": True})
            self.assertEqual(c.put("/api/curriculum", json=cur).status_code, 200)
            got = c.get("/api/curriculum").get_json()
            sp = got["structure_progress"]
            rows = {r["category"]: r["done"] for r in sp["rows"]}
            self.assertEqual(rows, {"General Education": 3, "Major": 3, "Core/Major": 0, "Electives": 3})
            self.assertEqual(sp["total"], 120)
            self.assertIn("ENGL 101 (ENR)", sp["not_counted"][0]["courses"])
            self.assertIn("MATH 234A", {x["code"] for x in got["catalog"]})          # added from the structure
            self.assertEqual(c.put("/api/curriculum", json=got).status_code, 200)     # GET -> PUT round trip
            req_file = os.path.join(self.app.auth.user_dir(self._user_id(c)), "degree_requirements.json")
            with open(req_file) as f:
                self.assertNotIn("structure_progress", json.load(f))                 # read-only extra not saved
            d = c.get("/api/dashboard").get_json()
            self.assertEqual(d["progress"]["done"], 9)
            self.assertEqual(d["progress"]["total"], 120)
            self.assertEqual(d["remaining_required"], 13)                              # 14 Major courses - COSC 111
        finally:
            os.remove(os.path.join("data", "program_structures.json"))

    def test_status_strip_endpoint(self):
        d = self.student.get("/api/status").get_json()
        self.assertEqual(d["program"], "Test Program")
        self.assertEqual(d["sections"], len(OFFERINGS))
        self.assertEqual(d["wishlist"], 1)
        self.assertEqual(d["required_left"], 2)                   # B 200, C 300
        self.assertEqual((d["progress"]["done"], d["progress"]["total"]), (3, 12))   # A 100 of 3 required + 1 slot
        self.assertIsNone(self._signup("statusnew").get("/api/status").get_json()["progress"])

    def test_old_file_without_grades_still_works(self):
        d = self.admin.get("/api/gpa").get_json()
        self.assertEqual(len(d["entries"]), 1)
        self.assertEqual(d["ungraded"], ["A 100"])

    def test_whatif_and_target(self):
        c = self.admin
        c.put("/api/grades", json={"grades": {"A 100": "B"}})
        r = c.post("/api/gpa/whatif", json={"target": 3.6, "credits": 3}).get_json()["target"]
        self.assertFalse(r["feasible"])                      # would need a 4.2 average
        r = c.post("/api/gpa/whatif", json={"target": 3.2, "credits": 3}).get_json()["target"]
        self.assertTrue(r["feasible"])
        self.assertAlmostEqual(r["needed"], 3.4, places=2)
        c.put("/api/grades", json={"grades": {"A 100": ""}})

    # ---- compare / active plan ----
    def test_pins_active_and_compare_with_conflicting_sections(self):
        c = self.student
        keys = [{"code": "B 200", "section": "001"}, {"code": "C 300", "section": "001"}]   # overlap in time
        self.assertEqual(c.post("/api/plan/pins", json={"sections": keys}).status_code, 200)
        self.assertEqual(c.post("/api/plan/pins", json={"sections": [{"code": "B 200", "section": "002"}]}).status_code, 200)
        self.assertEqual(c.post("/api/plan/pins", json={"sections": [{"code": "E 100", "section": "001"}]}).status_code, 200)
        self.assertEqual(c.post("/api/plan/pins", json={"sections": [{"code": "B 200", "section": "001"}]}).status_code, 400)  # 4th
        self.assertEqual(c.post("/api/plan/pins", json={"sections": [{"code": "NOPE 1", "section": "1"}]}).status_code, 400)
        cmp_ = c.get("/api/plan/compare").get_json()
        self.assertEqual([p["name"] for p in cmp_["plans"]], ["A", "B", "C"])
        self.assertIn("days_on_campus", cmp_["best"])
        self.assertEqual(c.post("/api/plan/active", json={"sections": keys[:1]}).status_code, 200)
        planned = c.get("/api/gpa").get_json()
        self.assertEqual(planned["planned_source"], "active")
        for pin in c.get("/api/plan/choices").get_json()["pins"]:
            c.delete(f"/api/plan/pins/{pin['id']}")
        c.delete("/api/plan/active")

    # ---- roadmap ----
    def test_roadmap_order_moves_and_validation(self):
        c = self.admin
        c.put("/api/roadmap/settings", json={"start_term": "Fall 2026", "max_credits": 6})
        road = c.get("/api/roadmap").get_json()["roadmap"]
        order = [(t["label"], [x["id"] for x in t["courses"]]) for t in road["terms"]]
        self.assertEqual(order[0][1][0], "B 200")                        # A 100 is done; B before C
        pos = {x["id"]: i for i, (_, ids) in enumerate(order) for x in [{"id": i2} for i2 in ids]}
        self.assertLess(pos["B 200"], pos["C 300"])
        # move C 300 into the first term: allowed, but warns
        r = c.post("/api/roadmap/move", json={"id": "C 300", "term": "Fall 2026"})
        self.assertEqual(r.status_code, 200)
        first = r.get_json()["roadmap"]["terms"][0]["courses"]
        warned = next(x for x in first if x["id"] == "C 300")
        self.assertTrue(warned["warnings"])
        self.assertEqual(c.post("/api/roadmap/move", json={"id": "NOPE", "term": "Fall 2026"}).status_code, 400)
        self.assertEqual(c.post("/api/roadmap/move", json={"id": "C 300", "term": "Fall 2099"}).status_code, 400)
        self.assertEqual(c.post("/api/roadmap/reset").get_json()["overridden"], 0)
        c.put("/api/roadmap/settings", json={"start_term": "", "max_credits": ""})

    def test_brand_new_account_has_empty_states_everywhere(self):
        n = self._signup("brandnew")
        self.assertFalse(n.get("/api/roadmap").get_json()["has_curriculum"])
        self.assertEqual(n.get("/api/gpa").get_json()["entries"], [])
        self.assertEqual(n.get("/api/plan/compare").get_json()["plans"], [])
        d = n.get("/api/dashboard").get_json()
        self.assertFalse(d["has_curriculum"])
        for url in ("/", "/gpa", "/compare", "/roadmap", "/plan"):
            self.assertEqual(n.get(url).status_code, 200, url)

    def test_dashboard(self):
        d = self.admin.get("/api/dashboard").get_json()
        self.assertEqual(d["progress"]["done"], 3)
        self.assertEqual(d["progress"]["total"], 3 * 3 + 3)             # 3 required + 1 slot
        self.assertEqual([x["code"] for x in d["available"]], ["B 200"])
        self.assertEqual(d["bottlenecks"][0]["code"], "B 200")

    # ---- AI tools ----
    def _tools(self, client_name="admin1"):
        user = self.app.auth._find_by_username(client_name)
        ctx = self.app.app.test_request_context()
        ctx.push()
        self.app.g.user = user
        self.addCleanup(ctx.pop)
        return self.app._advisor_tools()

    def test_ai_tools_match_schema_and_cannot_write_grades(self):
        import ai
        tools = self._tools()
        self.assertEqual({t["name"] for t in ai.TOOLS}, set(tools))
        self.assertFalse([n for n in tools if "grade" in n and n not in ("gpa_what_if",) and n.startswith(("set_", "add_", "update_", "save_"))])
        # the grade-related tools must be read-only: the student's file is byte-identical afterwards
        path = self.app.requirements_path()
        with open(path, "rb") as f:
            before = f.read()
        for name, args in [("get_gpa", {}), ("gpa_what_if", {"default_grade": "A"}), ("gpa_target", {"target_gpa": 3.5}),
                           ("get_roadmap", {"graduate_by": "Spring 2028"}), ("get_progress", {})]:
            tools[name](args)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), before)

    def test_ai_tool_answers(self):
        t = self._tools("admin1")
        rm = t["get_roadmap"]({"graduate_by": "Fall 2026"})
        self.assertFalse(rm["graduate_by"]["feasible_as_planned"])        # B then C needs more than one term
        self.assertIn("projection", rm["accuracy_note"])
        self.assertEqual(t["get_roadmap"]({"graduate_by": "Spring 2090"})["graduate_by"]["feasible_as_planned"], True)
        self.assertIn("error", t["get_roadmap"]({"graduate_by": "someday"}))
        self.assertIn("error", t["gpa_what_if"]({"grades": [{"code": "B 200", "grade": "Q"}]}))
        pr = t["get_progress"]({})
        self.assertEqual(pr["credits_done"], 3)

    def test_chat_loop_runs_new_tools_with_a_fake_model(self):
        import ai

        class Fake:
            def __init__(self):
                self.n = 0
            def step(self, system, convo):
                self.n += 1
                if self.n == 1:
                    return "", [{"id": "1", "name": "get_roadmap", "input": {"graduate_by": "Spring 2028"}},
                                {"id": "2", "name": "get_gpa", "input": {}}]
                tool_msgs = [m for m in convo if m["role"] == "tool"][-1]["results"]
                assert all(not r["is_error"] for r in tool_msgs), tool_msgs
                return "ok", []
        out = ai.run_chat([{"role": "user", "content": "can I graduate by Spring 2028?"}], "ctx", self._tools(), prov=Fake())
        self.assertEqual(out["reply"], "ok")
        self.assertEqual(out["actions"], [])      # nothing was changed

    def test_chat_reports_steps_and_events(self):
        import ai

        class Fake:
            def __init__(self):
                self.n = 0
            def step(self, system, convo):
                self.n += 1
                if self.n == 1:
                    return "", [{"id": "1", "name": "get_progress", "input": {}}, {"id": "2", "name": "nope", "input": {}}]
                return "done", []
        events = []
        out = ai.run_chat([{"role": "user", "content": "hi"}], "ctx", self._tools(), prov=Fake(), on_event=events.append)
        self.assertEqual([s["name"] for s in out["steps"]], ["get_progress", "nope"])
        self.assertEqual([s["ok"] for s in out["steps"]], [True, False])
        self.assertEqual(out["steps"][0]["label"], "Checking your degree progress")
        self.assertIn("credits_done", out["steps"][0]["preview"])
        self.assertEqual([e["type"] for e in events], ["thinking", "tool", "tool_done", "tool", "tool_done", "thinking"])

    def test_chat_stream_endpoint(self):
        import ai
        from unittest import mock

        class Fake:
            def __init__(self):
                self.n = 0
            def step(self, system, convo):
                self.n += 1
                if self.n == 1:
                    return "", [{"id": "1", "name": "get_gpa", "input": {}}, {"id": "2", "name": "get_progress", "input": {}}]
                return "Your GPA is fine.", []
        c = self._signup("streamer1")
        self.assertEqual(c.put("/api/curriculum", json=CURRICULUM).status_code, 200)
        with mock.patch.object(ai, "status", return_value={"available": True}), \
                mock.patch.object(ai, "make_provider", return_value=Fake()):
            r = c.post("/api/ai/chat?stream=1", json={"messages": [{"role": "user", "content": "gpa?"}]})
            self.assertEqual(r.status_code, 200)
            self.assertIn("ndjson", r.content_type)
            lines = [json.loads(l) for l in r.get_data(as_text=True).splitlines() if l.strip()]
        types = [l["type"] for l in lines]
        self.assertEqual(types[0], "thinking")
        self.assertIn({"type": "tool", "name": "get_gpa", "label": "Checking your GPA", "input": {}}, lines)
        self.assertEqual(types[-1], "done")
        self.assertEqual(lines[-1]["reply"], "Your GPA is fine.")
        self.assertEqual(lines[-1]["steps"][0]["name"], "get_gpa")
        for step in lines[-1]["steps"]:
            self.assertTrue(step["ok"], step["preview"])                  # tools saw the logged-in student

    def test_chat_stream_reports_errors_as_events(self):
        import ai
        from unittest import mock

        class Broken:
            def step(self, system, convo):
                raise ai.AIRateLimitError("HTTP 429")
        c = self._signup("streamer2")
        with mock.patch.object(ai, "status", return_value={"available": True}), \
                mock.patch.object(ai, "make_provider", return_value=Broken()):
            r = c.post("/api/ai/chat?stream=1", json={"messages": [{"role": "user", "content": "hi"}]})
            lines = [json.loads(l) for l in r.get_data(as_text=True).splitlines() if l.strip()]
        self.assertEqual(lines[-1]["type"], "error")
        self.assertIn("over its limit", lines[-1]["error"])


if __name__ == "__main__":
    unittest.main()
