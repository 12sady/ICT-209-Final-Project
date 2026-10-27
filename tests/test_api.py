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

    # ---- GPA ----
    def test_grades_roundtrip_and_survive_curriculum_save(self):
        c = self.student
        self.assertEqual(c.put("/api/grades", json={"grades": {"A 100": "a-"}}).status_code, 200)
        g = c.get("/api/gpa").get_json()
        self.assertAlmostEqual(g["summary"]["gpa"], 3.7)
        stale = json.loads(json.dumps(CURRICULUM))          # a Curriculum page that has never seen grades
        self.assertEqual(c.put("/api/curriculum", json=stale).status_code, 200)
        self.assertEqual(c.get("/api/curriculum").get_json()["grades"], {"A 100": "A-"})
        self.assertEqual(c.put("/api/grades", json={"grades": {"A 100": "Z"}}).status_code, 400)
        self.assertEqual(c.put("/api/grades", json={"grades": {"B 200": "A"}}).status_code, 400)   # not completed
        self.assertEqual(c.put("/api/grades", json={"grades": {"A 100": ""}}).status_code, 200)
        self.assertIsNone(c.get("/api/gpa").get_json()["summary"]["gpa"])

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


if __name__ == "__main__":
    unittest.main()
