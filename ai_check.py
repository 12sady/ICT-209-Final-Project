"""
ai_check.py
-----------
Checks that the AI advisor can really talk to your model. Run it from this folder with
the SAME environment variables you use for the app:

    python3 ai_check.py

It reads AI_BASE_URL / AI_MODEL / AI_API_KEY (Ollama, Gemini, ...) or ANTHROPIC_API_KEY,
prints which provider and model it will use (never the key, not even part of it), then:

  1. sends one tiny plain message, and
  2. runs one tool-calling round trip with a harmless read-only tool (get_progress on a
     temporary, empty student made in a throw-away folder: your real data is never touched).

Exit code: 0 = everything works, 1 = a check failed, 2 = not configured.
"""

import importlib
import os
import shutil
import sys
import tempfile

import envfile
envfile.load()  # AI settings from .env (git-ignored), before ai.py reads them

import ai

ROOT = os.path.dirname(os.path.abspath(__file__))
PING = "Reply with just the single word: ready"
TOOL_QUESTION = ("Use your get_progress tool to look at my degree progress, "
                 "then tell me in one short sentence what it says.")
EXPECTED_TOOL = "get_progress"


# ---- configuration ---------------------------------------------------------

def describe_config(env=None):
    """What would be used, with no secrets: provider, model, server host, whether a key is set."""
    env = os.environ if env is None else env
    if env.get("AI_BASE_URL"):
        base = env["AI_BASE_URL"]
        return {"provider": "openai", "label": "OpenAI-compatible server (Ollama, Gemini, ...)", "model": env.get("AI_MODEL", ""),
                "host": ai._host(base), "base_url": base, "key_set": bool(env.get("AI_API_KEY")),
                "key_needed": "localhost" not in base and "127.0.0.1" not in base}
    if env.get("ANTHROPIC_API_KEY"):
        return {"provider": "anthropic", "label": "Claude (Anthropic API)", "model": env.get("ANTHROPIC_MODEL", ai.MODEL),
                "host": "api.anthropic.com", "base_url": "", "key_set": True, "key_needed": True}
    return {"provider": None}


def config_problem(cfg):
    """(what, fix) when the setup is incomplete, else None."""
    if cfg["provider"] is None:
        return ("No AI is configured. Neither AI_BASE_URL nor ANTHROPIC_API_KEY is set in this terminal.",
                'Free, on your computer:  export AI_BASE_URL="http://localhost:11434/v1" AI_MODEL="llama3.1"\n'
                '    Free online (Gemini):    export AI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai" '
                'AI_API_KEY="<your key>" AI_MODEL="gemini-3.6-flash"\n'
                "    (set them in the same terminal you run this script and the app from)")
    if cfg["provider"] == "openai" and not cfg["model"]:
        return ("AI_BASE_URL is set but AI_MODEL is not.", 'Add the model name, e.g.  export AI_MODEL="gemini-3.6-flash"  (Ollama: the one you pulled).')
    if cfg["provider"] == "openai" and cfg["key_needed"] and not cfg["key_set"]:
        return ("This server needs an API key but AI_API_KEY is not set.", 'export AI_API_KEY="<your key>"  (create one at aistudio.google.com for Gemini).')
    if cfg["provider"] == "anthropic":
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return ("The Claude library isn't installed.", "pip install anthropic")
    return None


# ---- the two checks --------------------------------------------------------

def check_ping(prov):
    """Plain message, no tools. Returns {"ok": True, "reply": str} or {"ok": False, "what": str, "fix": str}."""
    try:
        text, calls = prov.step(["You are a connection test. Answer in a few words."], [{"role": "user", "content": PING}], tools=[])
    except Exception as e:  # every provider failure becomes a plain-language message
        what, fix = ai.explain_error(e, _cfg_name(), os.environ.get("AI_BASE_URL", ""))
        return {"ok": False, "what": what, "fix": fix}
    if not text.strip():
        return {"ok": False, "what": "The model connected but sent back an empty reply.",
                "fix": "Try again; if it keeps happening, pick another model (some models return nothing when a length limit is hit)."}
    return {"ok": True, "reply": text.strip()}


def check_tools(prov, impls):
    """One tool round trip using the advisor's real tool list and system prompt.
    impls: {tool name: callable} - only these can run, anything else the model calls is refused.
    Returns {"ok", "called": [names], "reply", "problem"}."""
    calls_made = []

    def wrap(name, fn):
        def inner(args):
            calls_made.append(name)
            return fn(args)
        return inner

    wrapped = {n: wrap(n, f) for n, f in impls.items()}
    refused = []

    class Guard(dict):  # unknown tools are recorded, then refused by run_chat as "Unknown tool"
        def get(self, k, d=None):
            if k not in self:
                refused.append(k)
            return dict.get(self, k, d)

    try:
        result = ai.run_chat([{"role": "user", "content": TOOL_QUESTION}], "A brand-new student with no curriculum yet.", Guard(wrapped), prov=prov)
    except Exception as e:
        what, fix = ai.explain_error(e, _cfg_name(), os.environ.get("AI_BASE_URL", ""))
        return {"ok": False, "called": calls_made, "reply": "", "problem": what, "fix": fix, "kind": "error"}
    reply = (result.get("reply") or "").strip()
    if EXPECTED_TOOL in calls_made:
        return {"ok": True, "called": calls_made, "reply": reply, "problem": None, "kind": "ok"}
    if refused:
        return {"ok": False, "called": calls_made, "reply": reply, "kind": "wrong_tool",
                "problem": f"The model called {', '.join(sorted(set(refused)))} instead of {EXPECTED_TOOL}."}
    return {"ok": False, "called": calls_made, "reply": reply, "kind": "no_tool",
            "problem": f"The model answered without calling {EXPECTED_TOOL}."}


def tool_failure_meaning(kind):
    if kind == "error":
        return "The tool test couldn't finish (see the fix above)."
    return ("What this means: the advisor needs the model to look things up with tools. A model that can't do that will answer "
            "from memory and may invent course codes, times or GPA numbers. Chatting still works, but don't trust its facts.\n"
            "    Try a stronger model: Gemini Flash, Ollama llama3.1 (8B or larger) or qwen2.5, or Claude. Very small models are the usual culprit.")


# ---- running it ------------------------------------------------------------

def _cfg_name():
    return ai.provider()


def real_tool_impls():
    """The app's own get_progress for a temporary empty student, in a throw-away data folder.
    Falls back to an equivalent stub if Flask isn't installed. Returns (impls, cleanup)."""
    tmp = tempfile.mkdtemp(prefix="ai_check_")
    old = os.getcwd()
    try:
        import flask  # noqa: F401
        os.makedirs(os.path.join(tmp, "data"))
        os.chdir(tmp)                      # app.py reads/writes ./data, so this keeps it away from your real data
        sys.path.insert(0, ROOT)
        app_mod = importlib.import_module("app")
        user, _ = app_mod.auth.create_user("check_student", "check-pass", "check-pass")
        ctx = app_mod.app.test_request_context()
        ctx.push()
        app_mod.g.user = user
        tool = app_mod._advisor_tools()[EXPECTED_TOOL]

        def cleanup():
            ctx.pop()
            os.chdir(old)
            shutil.rmtree(tmp, ignore_errors=True)
        return {EXPECTED_TOOL: tool}, cleanup
    except ImportError:
        os.chdir(old)
        return ({EXPECTED_TOOL: lambda _a: {"error": "The student has no curriculum yet."}}, lambda: shutil.rmtree(tmp, ignore_errors=True))


def run(prov, impls, cfg, out=print):
    """Both checks; prints a report; returns the exit code (0 ok, 1 failed)."""
    out("AI connection check")
    out("-------------------")
    out(f"Provider : {cfg['label']}")
    out(f"Model    : {cfg['model'] or '(not set)'}")
    out(f"Server   : {cfg['host']}")
    out(f"API key  : {'set (hidden)' if cfg['key_set'] else 'not set' + (' (fine for a local Ollama)' if not cfg['key_needed'] else '')}")
    out("")

    out("Step 1 of 2: sending one tiny message ...")
    r = check_ping(prov)
    if not r["ok"]:
        out(f"  FAILED: {r['what']}")
        out(f"  Fix: {r['fix']}")
        out("\nStopped here: fix this first, then run the check again.")
        return 1
    out(f'  OK: the model replied "{ai.scrub(r["reply"][:120])}"')
    out("")

    out("Step 2 of 2: tool-calling round trip (read-only get_progress on a temporary empty student) ...")
    t = check_tools(prov, impls)
    if t["ok"]:
        out(f"  OK: the model called {EXPECTED_TOOL} correctly.")
        if t["reply"]:
            out(f'  It then said: "{ai.scrub(t["reply"][:160])}"')
        out("\nAll good: the AI advisor should work with this setup.")
        return 0
    out(f"  FAILED: {t['problem']}")
    if t.get("fix"):
        out(f"  Fix: {t['fix']}")
    out("  " + tool_failure_meaning(t["kind"]))
    out("\nThe connection works, but the tool-calling test failed (see above)." if t["kind"] != "error" else "\nThe tool test hit an error (see above).")
    return 1


def main():
    cfg = describe_config()
    problem = config_problem(cfg)
    if problem:
        print("AI connection check\n-------------------")
        print(f"Not ready: {problem[0]}\nFix: {problem[1]}")
        return 2
    prov = ai.OpenAICompatProvider(timeout=60) if cfg["provider"] == "openai" else ai.AnthropicProvider()
    impls, cleanup = real_tool_impls()
    try:
        return run(prov, impls, cfg)
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
