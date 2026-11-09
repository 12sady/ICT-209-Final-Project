"""ai_check.py and the AI error explanations, with FAKE providers only: no network is ever touched."""
import io
import os
import unittest
import urllib.request
from unittest import mock

import ai
import ai_check

KEY = "SECRETKEY123456789012345"


class Out:
    def __init__(self):
        self.lines = []

    def __call__(self, s=""):
        self.lines.append(str(s))

    @property
    def text(self):
        return "\n".join(self.lines)


def cfg(**kw):
    base = {"provider": "openai", "label": "OpenAI-compatible server (Ollama, Gemini, ...)", "model": "m1", "host": "example.com",
            "base_url": "https://example.com/v1", "key_set": True, "key_needed": True}
    base.update(kw)
    return base


class FakeProv:
    """ping -> `ping_reply` (or raises ping_error); tool round: calls `tool_name` once if set, then answers."""
    def __init__(self, ping_reply="ready", ping_error=None, tool_name="get_progress", final="You have no curriculum yet."):
        self.ping_reply, self.ping_error, self.tool_name, self.final = ping_reply, ping_error, tool_name, final
        self.tool_rounds = 0

    def step(self, system, convo, tools=None):
        if tools == []:                                   # the plain message
            if self.ping_error:
                raise self.ping_error
            return self.ping_reply, []
        self.tool_rounds += 1
        if self.tool_name and self.tool_rounds == 1:
            return "", [{"id": "c1", "name": self.tool_name, "input": {}}]
        return self.final, []


IMPLS = lambda: {"get_progress": lambda a: {"error": "The student has no curriculum yet."}}


class NoNetworkMixin:
    def setUp(self):
        p = mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("network call in a test!"))
        p.start()
        self.addCleanup(p.stop)


class RunTests(NoNetworkMixin, unittest.TestCase):
    def test_success(self):
        out = Out()
        code = ai_check.run(FakeProv(), IMPLS(), cfg(), out)
        self.assertEqual(code, 0)
        self.assertIn("OK: the model replied", out.text)
        self.assertIn("called get_progress correctly", out.text)
        self.assertIn("All good", out.text)

    def test_ping_failures_give_plain_fixes(self):
        cases = [
            (ai.AIAuthenticationError("HTTP 401"), "rejected your API key", "AI_API_KEY"),
            (ai.AIRateLimitError("HTTP 429"), "over its limit", "Wait a minute"),
            (ai.AIConnectionError("boom"), "Couldn't reach example.com", "internet"),
            (ai.AIError("HTTP 404 {\"error\":\"model not found\"}"), "doesn't know the model", "ollama list"),
            (ai.AIError("HTTP 400 tools not supported"), "rejected the request", "tool"),
            (ai.AIError("HTTP 503"), "internal error", "try again"),
        ]
        for exc, what, fix in cases:
            with mock.patch.dict(os.environ, {"AI_BASE_URL": "https://example.com/v1", "AI_MODEL": "m1", "AI_API_KEY": KEY}):
                out = Out()
                code = ai_check.run(FakeProv(ping_error=exc), IMPLS(), cfg(), out)
            self.assertEqual(code, 1, exc)
            self.assertIn(what, out.text)
            self.assertIn(fix, out.text)
            self.assertNotIn("Step 2", out.text.split("Stopped here")[-1])   # stops before the tool step

    def test_ollama_not_running_message(self):
        with mock.patch.dict(os.environ, {"AI_BASE_URL": "http://localhost:11434/v1", "AI_MODEL": "llama3.1"}, clear=False):
            out = Out()
            ai_check.run(FakeProv(ping_error=ai.AIConnectionError("refused")), IMPLS(),
                         cfg(host="localhost:11434", key_set=False, key_needed=False, base_url="http://localhost:11434/v1"), out)
        self.assertIn("Couldn't reach Ollama", out.text)
        self.assertIn("ollama serve", out.text)

    def test_empty_ping_reply(self):
        out = Out()
        self.assertEqual(ai_check.run(FakeProv(ping_reply="  "), IMPLS(), cfg(), out), 1)
        self.assertIn("empty reply", out.text)

    def test_model_never_calls_the_tool(self):
        out = Out()
        code = ai_check.run(FakeProv(tool_name=None, final="I think you have 0 credits."), IMPLS(), cfg(), out)
        self.assertEqual(code, 1)
        self.assertIn("answered without calling get_progress", out.text)
        self.assertIn("What this means", out.text)
        self.assertIn("invent", out.text)

    def test_model_calls_the_wrong_tool_and_nothing_writes(self):
        ran = []
        impls = IMPLS()                                    # only get_progress exists: add_to_wishlist can't run
        out = Out()
        prov = FakeProv(tool_name="add_to_wishlist")
        code = ai_check.run(prov, impls, cfg(), out)
        self.assertEqual(code, 1)
        self.assertIn("called add_to_wishlist instead of get_progress", out.text)
        self.assertEqual(ran, [])

    def test_error_during_tool_step(self):
        class Boom(FakeProv):
            def step(self, system, convo, tools=None):
                if tools == []:
                    return "ready", []
                raise ai.AIRateLimitError("429")
        out = Out()
        self.assertEqual(ai_check.run(Boom(), IMPLS(), cfg(), out), 1)
        self.assertIn("over its limit", out.text)

    def test_key_is_never_printed(self):
        with mock.patch.dict(os.environ, {"AI_BASE_URL": "https://example.com/v1", "AI_MODEL": "m1", "AI_API_KEY": KEY}):
            out = Out()
            leaky = ai.AIError(f"HTTP 400 Incorrect API key provided: {KEY}. Also sk-abcdefghijklmnopqrstuv")
            ai_check.run(FakeProv(ping_error=leaky), IMPLS(), ai_check.describe_config(), out)
            ok = Out()
            ai_check.run(FakeProv(final=f"echo {KEY}"), IMPLS(), ai_check.describe_config(), ok)
        for text in (out.text, ok.text):
            self.assertNotIn(KEY, text)
            self.assertNotIn(KEY[:10], text)
            self.assertNotIn("sk-abcdefghij", text)
        self.assertIn("set (hidden)", out.text)


class ConfigTests(unittest.TestCase):
    def test_describe_config_variants(self):
        g = ai_check.describe_config({"AI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai", "AI_MODEL": "gemini-3.8-flash", "AI_API_KEY": KEY})
        self.assertEqual((g["provider"], g["model"], g["host"], g["key_set"]), ("openai", "gemini-3.8-flash", "generativelanguage.googleapis.com", True))
        self.assertNotIn(KEY, repr(g))
        o = ai_check.describe_config({"AI_BASE_URL": "http://localhost:11434/v1", "AI_MODEL": "llama3.1"})
        self.assertFalse(o["key_needed"])
        self.assertEqual(o["host"], "localhost:11434")
        c = ai_check.describe_config({"ANTHROPIC_API_KEY": KEY})
        self.assertEqual((c["provider"], c["host"]), ("anthropic", "api.anthropic.com"))
        self.assertNotIn(KEY, repr(c))
        self.assertIsNone(ai_check.describe_config({})["provider"])

    def test_config_problems(self):
        self.assertIn("No AI is configured", ai_check.config_problem({"provider": None})[0])
        self.assertIn("AI_MODEL", ai_check.config_problem(ai_check.describe_config({"AI_BASE_URL": "https://x.com/v1", "AI_API_KEY": "k"}))[0])
        self.assertIn("API key", ai_check.config_problem(ai_check.describe_config({"AI_BASE_URL": "https://x.com/v1", "AI_MODEL": "m"}))[0])
        self.assertIsNone(ai_check.config_problem(ai_check.describe_config({"AI_BASE_URL": "http://localhost:11434/v1", "AI_MODEL": "m"})))


class ProviderPayloadTests(NoNetworkMixin, unittest.TestCase):
    def test_plain_message_sends_no_tools_and_chat_sends_all(self):
        prov = ai.OpenAICompatProvider(base_url="https://example.com/v1", api_key="k", model="m")
        sent = []
        prov._post = lambda payload: (sent.append(payload), {"choices": [{"message": {"content": "ready"}}]})[1]
        self.assertEqual(prov.step(["sys"], [{"role": "user", "content": "hi"}], tools=[]), ("ready", []))
        prov.step(["sys"], [{"role": "user", "content": "hi"}])
        self.assertNotIn("tools", sent[0])
        self.assertEqual(len(sent[1]["tools"]), len(ai.TOOLS))


class ExplainErrorTests(unittest.TestCase):
    def test_scrub_hides_keys_and_long_tokens(self):
        self.assertNotIn(KEY, ai.scrub(f"bad key {KEY}", key=KEY))
        self.assertNotIn("sk-proj-abcdefghijklmnop", ai.scrub("Incorrect API key: sk-proj-abcdefghijklmnop1234", key=""))

    def test_anthropic_wording_uses_its_own_key_name(self):
        what, fix = ai.explain_error(ai.AIAuthenticationError("x"), "anthropic", "", "claude")
        self.assertIn("ANTHROPIC_API_KEY", fix)

    def test_chat_endpoint_uses_the_hints(self):
        try:
            import flask  # noqa: F401
        except ImportError:
            self.skipTest("Flask isn't installed for this Python")
        import tempfile, importlib, sys, shutil
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        old, tmp = os.getcwd(), tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, "data")); os.chdir(tmp); sys.path.insert(0, root)
            appm = importlib.import_module("app")
            appm.app.config["TESTING"] = True
            c = appm.app.test_client()
            c.post("/signup", data={"username": "chatter", "password": "secret1", "confirm": "secret1"})

            def boom(*a, **k):
                raise ai.AIError("HTTP 404 nope")
            with mock.patch.dict(os.environ, {"AI_BASE_URL": "http://localhost:11434/v1", "AI_MODEL": "llama9"}), \
                 mock.patch.object(ai, "run_chat", boom):
                r = c.post("/api/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]})
            self.assertEqual(r.status_code, 502)
            self.assertIn("llama9", r.get_json()["error"])
            self.assertIn("ollama list", r.get_json()["error"])
        finally:
            os.chdir(old)
            sys.path.remove(root)
            shutil.rmtree(tmp, ignore_errors=True)



class GeminiThoughtSignatureTest(unittest.TestCase):
    """Gemini 3 returns extra_content.google.thought_signature on tool calls and
    returns HTTP 400 if the next request doesn't send it back unchanged."""

    def test_signature_is_echoed_back_unchanged(self):
        sig = {"google": {"thought_signature": "opaque-signature-123"}}
        sent = []

        def fake_post(payload):
            sent.append(payload)
            if len(sent) == 1:
                return {"choices": [{"message": {"content": "", "tool_calls": [
                    {"id": "c1", "type": "function", "extra_content": sig,
                     "function": {"name": "get_progress", "arguments": "{}"}}]}}]}
            return {"choices": [{"message": {"content": "done"}}]}

        prov = ai.OpenAICompatProvider(base_url="https://example.com/v1", api_key="k", model="m")
        prov._post = fake_post
        out = ai.run_chat([{"role": "user", "content": "hi"}], "ctx",
                          {"get_progress": lambda a: {"ok": 1}}, prov=prov)
        self.assertEqual(out["reply"], "done")
        assistant = [m for m in sent[1]["messages"] if m["role"] == "assistant"][0]
        self.assertEqual(assistant["tool_calls"][0]["extra_content"], sig)

    def test_calls_without_signature_are_unchanged(self):
        sent = []

        def fake_post(payload):
            sent.append(payload)
            if len(sent) == 1:
                return {"choices": [{"message": {"content": "", "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}]}}]}
            return {"choices": [{"message": {"content": "ok"}}]}

        prov = ai.OpenAICompatProvider(base_url="https://example.com/v1", api_key="k", model="m")
        prov._post = fake_post
        ai.run_chat([{"role": "user", "content": "hi"}], "ctx", {"t": lambda a: {"ok": 1}}, prov=prov)
        assistant = [m for m in sent[1]["messages"] if m["role"] == "assistant"][0]
        self.assertNotIn("extra_content", assistant["tool_calls"][0])


if __name__ == "__main__":
    unittest.main()


class UserAgentAndBlockTests(unittest.TestCase):
    """Groq (behind Cloudflare) answers Python's default User-Agent with 403 'error code: 1010'."""

    def _http_error(self, code, body):
        import io
        import urllib.error
        return urllib.error.HTTPError("https://x/v1/chat/completions", code, "err", {}, io.BytesIO(body))

    def test_sends_own_user_agent(self):
        seen = {}

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"choices": []}'

        def fake_urlopen(req, timeout=None):
            seen["ua"] = req.get_header("User-agent")
            return Resp()

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            ai.OpenAICompatProvider("https://x/v1", "k", "m")._post({})
        self.assertEqual(seen["ua"], ai.USER_AGENT)

    def test_firewall_block_is_not_reported_as_bad_key(self):
        p = ai.OpenAICompatProvider("https://x/v1", "k", "m")
        with mock.patch("urllib.request.urlopen", side_effect=self._http_error(403, b"error code: 1010\n")):
            with self.assertRaises(ai.AIConnectionError):
                p._post({})
        with mock.patch("urllib.request.urlopen", side_effect=self._http_error(401, b"bad key")):
            with self.assertRaises(ai.AIAuthenticationError):
                p._post({})


class RateLimitRetryTests(unittest.TestCase):
    """On HTTP 429 the client waits as long as the service asks, then tries again."""

    def _429(self, headers):
        import io
        import urllib.error
        return urllib.error.HTTPError("https://x/v1/chat/completions", 429, "Too Many Requests", headers, io.BytesIO(b"{}"))

    def test_retry_wait_reads_headers(self):
        self.assertEqual(ai.retry_wait({"retry-after": "7"}), 7.5)
        self.assertEqual(ai.retry_wait({"x-ratelimit-reset-tokens": "2.5s"}), 3.0)
        self.assertEqual(ai.retry_wait({"x-ratelimit-reset-tokens": "1m0s"}), 30.0)     # capped
        self.assertEqual(ai.retry_wait({"x-ratelimit-reset-tokens": "120ms"}), 1.0)     # at least 1 s
        self.assertEqual(ai.retry_wait({}), 10.5)

    def test_waits_then_succeeds(self):
        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"choices": [{"message": {"content": "hi"}}]}'
        answers = [self._429({"retry-after": "2"}), Resp()]

        def fake_urlopen(req, timeout=None):
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return a

        slept = []
        with mock.patch("urllib.request.urlopen", fake_urlopen), mock.patch.object(ai, "_sleep", slept.append):
            out = ai.OpenAICompatProvider("https://x/v1", "k", "m")._post({})
        self.assertEqual(slept, [2.5])
        self.assertEqual(out["choices"][0]["message"]["content"], "hi")

    def test_gives_up_after_total_wait_budget(self):
        slept = []
        with mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: (_ for _ in ()).throw(self._429({"retry-after": "25"}))), \
                mock.patch.object(ai, "_sleep", slept.append):
            with self.assertRaises(ai.AIRateLimitError):
                ai.OpenAICompatProvider("https://x/v1", "k", "m")._post({})
        self.assertEqual(slept, [25.5])        # a second 25 s wait would pass the 40 s budget

    def test_reasoning_effort_only_when_set(self):
        sent = {}

        def fake_post(self, payload):
            sent.update(payload)
            return {"choices": [{"message": {"content": "ok"}}]}
        p = ai.OpenAICompatProvider("https://x/v1", "k", "m")
        with mock.patch.object(ai.OpenAICompatProvider, "_post", fake_post), mock.patch.dict(os.environ, {"AI_REASONING_EFFORT": "low"}):
            p.step(["sys"], [{"role": "user", "content": "hi"}], tools=[])
        self.assertEqual(sent["reasoning_effort"], "low")
        sent.clear()
        env = {k: v for k, v in os.environ.items() if k != "AI_REASONING_EFFORT"}
        with mock.patch.object(ai.OpenAICompatProvider, "_post", fake_post), mock.patch.dict(os.environ, env, clear=True):
            p.step(["sys"], [{"role": "user", "content": "hi"}], tools=[])
        self.assertNotIn("reasoning_effort", sent)


class WaitEventTests(unittest.TestCase):
    def test_rate_limit_pause_is_reported(self):
        import io
        import urllib.error
        err = urllib.error.HTTPError("https://x/v1/chat/completions", 429, "Too Many", {"retry-after": "3"}, io.BytesIO(b"{}"))

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"choices": [{"message": {"content": "hi"}}]}'
        answers = [err, Resp()]

        def fake_urlopen(req, timeout=None):
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return a
        events = []
        prov = ai.OpenAICompatProvider("https://x/v1", "k", "m")
        with mock.patch("urllib.request.urlopen", fake_urlopen), mock.patch.object(ai, "_sleep", lambda s: None):
            out = ai.run_chat([{"role": "user", "content": "hi"}], "ctx", {}, prov=prov, on_event=events.append)
        self.assertEqual(out["reply"], "hi")
        self.assertIn({"type": "wait", "seconds": 4}, events)
