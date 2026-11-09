// AI advisor drawer (loaded on every page for logged-in students).
(function () {
  const $ = (id) => document.getElementById(id);
  const fab = $("advisor-fab");
  if (!fab) return;

  const KEY = "advisor-chat-v1";
  let messages = []; // [{role, content, actions?}]
  let busy = false;
  let statusInfo = null;
  let live = [];      // steps of the answer being worked on: [{label, done, ok}] or {wait: seconds}

  const SUGGESTIONS = [
    { icon: "🎓", text: "Can I graduate by Spring 2027?" },
    { icon: "📈", text: "What GPA do I need this term to reach a 3.8?" },
    { icon: "🗓️", text: "What should I take next term?" },
    { icon: "⏰", text: "No classes before 10am and keep Fridays free" },
  ];

  // Short chip name + icon for each tool, shown under an answer.
  const TOOL_CHIPS = {
    get_curriculum_status: ["📋", "Curriculum"], search_offerings: ["🔎", "Class search"],
    get_wishlist: ["⭐", "Wishlist"], add_to_wishlist: ["➕", "Wishlist"], remove_from_wishlist: ["➖", "Wishlist"],
    set_preferences: ["⚙️", "Preferences"], get_gpa: ["🎓", "GPA"], gpa_what_if: ["🧮", "What-if GPA"],
    gpa_target: ["🎯", "GPA target"], get_roadmap: ["🗺️", "Roadmap"], get_progress: ["📊", "Degree progress"],
    get_best_plans: ["🗓️", "Schedule planner"],
  };

  function load() {
    try { messages = JSON.parse(sessionStorage.getItem(KEY) || "[]"); } catch (e) { messages = []; }
  }
  function save() {
    try { sessionStorage.setItem(KEY, JSON.stringify(messages.slice(-40))); } catch (e) { /* private mode */ }
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  // Tiny, safe formatter: escape first, then **bold**, "- " bullets, line breaks.
  function format(text) {
    const lines = esc(text).split("\n");
    let html = "", inList = false;
    lines.forEach((line) => {
      const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
      const bolded = (t) => t.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
      if (bullet) {
        if (!inList) { html += "<ul>"; inList = true; }
        html += `<li>${bolded(bullet[1])}</li>`;
      } else {
        if (inList) { html += "</ul>"; inList = false; }
        html += line.trim() ? `<p>${bolded(line)}</p>` : "";
      }
    });
    if (inList) html += "</ul>";
    return html;
  }

  function render() {
    const log = $("advisor-log");
    log.innerHTML = "";
    if (!messages.length && !busy && statusInfo && statusInfo.available) log.appendChild(welcome());
    messages.forEach((m) => {
      const row = document.createElement("div");
      row.className = `advisor-row ${m.role}`;
      const div = document.createElement("div");
      div.className = `advisor-msg ${m.role}`;
      div.innerHTML = m.role === "assistant" ? format(m.content) : `<p>${esc(m.content)}</p>`;
      if (m.actions && m.actions.length) {
        const chips = document.createElement("div");
        chips.className = "advisor-actions";
        chips.innerHTML = m.actions.map((a) => `<span class="advisor-chip">✓ ${esc(a)}</span>`).join("");
        div.appendChild(chips);
      }
      if (m.role === "assistant" && m.steps && m.steps.length) div.appendChild(toolChips(m.steps));
      if (m.role === "assistant" && m.steps) div.appendChild(howIGotThis(m.steps));
      if (m.error) div.classList.add("error");
      if (m.role === "assistant") row.appendChild(avatar());
      row.appendChild(div);
      log.appendChild(row);
    });
    if (busy) {
      const row = document.createElement("div");
      row.className = "advisor-row assistant";
      const t = document.createElement("div");
      t.className = "advisor-msg assistant thinking";
      const steps = live.map((s) => s.wait
        ? `<li class="wait"><span class="advisor-step-icon">⏳</span> The AI service asked us to slow down: waiting ${esc(s.wait)} s…</li>`
        : s.done
          ? `<li class="${s.ok ? "ok" : "bad"}"><span class="advisor-step-icon">${s.ok ? "✓" : "✗"}</span> ${esc(doneLabel(s.label))}</li>`
          : `<li class="running"><span class="advisor-spinner" aria-hidden="true"></span> ${esc(s.label)}…</li>`).join("");
      t.innerHTML = `<p class="advisor-working"><span class="advisor-dots" aria-hidden="true"><i></i><i></i><i></i></span> ${live.length ? "Working on it" : "Thinking"}</p>${steps ? `<ul class="advisor-steps">${steps}</ul>` : ""}`;
      row.append(avatar(), t);
      log.appendChild(row);
    }
    log.scrollTop = log.scrollHeight;
    $("advisor-suggest").hidden = true;
    $("advisor-send").disabled = busy;
  }

  function avatar() {
    const a = document.createElement("div");
    a.className = "advisor-mini";
    a.setAttribute("aria-hidden", "true");
    a.textContent = "✦";
    return a;
  }

  // "Checking your GPA" -> "Checked your GPA" once it's done.
  function doneLabel(label) {
    return label.replace(/^Checking/, "Checked").replace(/^Looking at/, "Looked at").replace(/^Searching/, "Searched")
      .replace(/^Running/, "Ran").replace(/^Calculating/, "Calculated").replace(/^Working out/, "Worked out")
      .replace(/^Adding/, "Added").replace(/^Removing/, "Removed").replace(/^Updating/, "Updated");
  }

  // Empty chat: greeting + idea cards.
  function welcome() {
    const name = ($("advisor-panel").dataset.username || "").split(/[-_.]/)[0];
    const hello = name ? `Hi ${name.charAt(0).toUpperCase()}${name.slice(1)}!` : "Hi there!";
    const box = document.createElement("div");
    box.className = "advisor-welcome";
    box.innerHTML = `<div class="advisor-wave" aria-hidden="true">👋</div><h3>${esc(hello)}</h3>
      <p>Ask about your courses, GPA, schedule or graduation. I'll look up your real data.</p>
      <div class="advisor-cards">${SUGGESTIONS.map((s, i) =>
        `<button type="button" class="advisor-card" data-i="${i}"><span aria-hidden="true">${s.icon}</span>${esc(s.text)}</button>`).join("")}</div>`;
    box.querySelectorAll(".advisor-card").forEach((b) => { b.onclick = () => send(SUGGESTIONS[Number(b.dataset.i)].text); });
    return box;
  }

  // One chip per distinct tool used, e.g. "📊 Degree progress".
  function toolChips(steps) {
    const seen = new Set();
    const chips = [];
    steps.forEach((s) => {
      const [icon, name] = TOOL_CHIPS[s.name] || ["🔧", s.name];
      if (seen.has(name)) return;
      seen.add(name);
      chips.push(`<span class="advisor-tool-chip${s.ok ? "" : " bad"}">${icon} ${esc(name)}</span>`);
    });
    const div = document.createElement("div");
    div.className = "advisor-tool-chips";
    div.innerHTML = chips.join("");
    return div;
  }

  // "How I got this": the tools the AI used for an answer and what each returned,
  // so a student (or the audience in a demo) can check the answer came from real data.
  function howIGotThis(steps) {
    const box = document.createElement("details");
    box.className = "advisor-how";
    if (!steps.length) {
      box.innerHTML = `<summary>How I got this <span class="advisor-how-count">(no tools)</span></summary><p class="hint">Answered from the short snapshot of your data, without looking anything up.</p>`;
      return box;
    }
    box.innerHTML = `<summary>How I got this <span class="advisor-how-count">(${steps.length} tool${steps.length === 1 ? "" : "s"})</span></summary>
      <ol>${steps.map((s) => {
        const args = s.input && Object.keys(s.input).length ? ` <code>${esc(JSON.stringify(s.input))}</code>` : "";
        return `<li><strong>${esc(s.label)}</strong>${s.ok ? "" : " (failed)"} <span class="hint-inline">${esc(s.name)}</span>${args}<pre>${esc(s.preview || "")}</pre></li>`;
      }).join("")}</ol>`;
    return box;
  }

  function onEvent(ev) {
    if (ev.type === "tool") live.push({ name: ev.name, label: ev.label, done: false });
    else if (ev.type === "tool_done") {
      const s = live.find((x) => x.name === ev.name && !x.done && !x.wait);
      if (s) { s.done = true; s.ok = ev.ok; }
    } else if (ev.type === "wait") live.push({ wait: ev.seconds });
    else return;
    render();
  }

  // Reads the server's one-JSON-object-per-line stream; returns the final event.
  async function readStream(res) {
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "", last = null;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line); } catch (e) { continue; }
        if (ev.type === "done" || ev.type === "error") last = ev; else onEvent(ev);
      }
    }
    return last;
  }

  // Header: green dot + "Online" when a model is set up, grey otherwise.
  function renderHeaderStatus() {
    const ok = !!(statusInfo && statusInfo.available);
    $("advisor-dot").classList.toggle("off", !ok);
    $("advisor-status").textContent = !statusInfo ? "Reads your real data" : ok ? "Online · reads your real data" : "Not set up yet";
  }

  // The input grows with what you type (up to about 5 lines).
  function autoGrow() {
    const ta = $("advisor-input");
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
  }

  function renderSetup() {
    const box = $("advisor-setup");
    if (!statusInfo || statusInfo.available) { box.hidden = true; return; }
    box.hidden = false;
    $("advisor-form").hidden = true;
    box.innerHTML = statusInfo.reason === "no_sdk"
      ? `<p><strong>One more install.</strong> The Claude library isn't installed on this computer. In the terminal, run:</p><pre>pip install anthropic</pre><p>then restart the app.</p>`
      : statusInfo.reason === "no_model"
      ? `<p><strong>Pick a model.</strong> The AI address is set but not which model to use. Add this before starting the app, then restart it:</p><pre>export AI_MODEL="llama3.1"</pre><p class="hint">Use the model name your provider lists (for Ollama, the one you pulled).</p>`
      : `<p><strong>The advisor needs an AI model.</strong> Easiest: create a file named <code>.env</code> next to <code>app.py</code> (copy <code>.env.example</code>), put these lines in it, then restart the app:</p>
         <pre>AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
AI_MODEL=gemini-3.6-flash
AI_API_KEY=key from aistudio.google.com</pre>
         <p class="hint">Already made <code>.env</code>? Check it's in the same folder as app.py, is named exactly <code>.env</code> (not <code>.env.txt</code>), and that you restarted the app.</p>
         <p>Or set them in the terminal before starting the app (Mac/Linux shown; on Windows PowerShell write <code>$env:AI_MODEL = "..."</code> instead of <code>export</code>). Option 1 is free and private.</p>
         <p><strong>1. Free, on this computer (Ollama)</strong></p>
         <pre>ollama pull llama3.1
export AI_BASE_URL="http://localhost:11434/v1"
export AI_MODEL="llama3.1"
python3 app.py</pre>
         <p><strong>2. Free online tier (e.g. Google Gemini)</strong></p>
         <pre>export AI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai"
export AI_API_KEY="key from aistudio.google.com"
export AI_MODEL="gemini-3.6-flash"
python3 app.py</pre>
         <p><strong>3. Claude (paid)</strong></p>
         <pre>pip install anthropic
export ANTHROPIC_API_KEY="your-key"
python3 app.py</pre>
         <p class="hint">Keys and settings stay on that computer; they're never stored in the app's files or shown to students.</p>`;
  }

  async function checkStatus() {
    try { statusInfo = await (await fetch("/api/ai/status")).json(); } catch (e) { statusInfo = { available: false, reason: "no_key" }; }
    renderSetup();
    renderHeaderStatus();
    render();
  }

  async function send(text) {
    text = (text || "").trim();
    if (!text || busy) return;
    messages.push({ role: "user", content: text });
    $("advisor-input").value = "";
    autoGrow();
    busy = true; live = []; save(); render();
    try {
      const res = await fetch("/api/ai/chat?stream=1", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: messages.filter((m) => !m.error).map((m) => ({ role: m.role, content: m.content })) }),
      });
      const streamed = res.ok && (res.headers.get("Content-Type") || "").includes("ndjson") && res.body;
      const data = streamed ? (await readStream(res)) || { type: "error", error: "The answer was cut off. Try again." } : await res.json();
      if (!res.ok || data.type === "error") {
        messages.push({ role: "assistant", content: data.error || "Something went wrong.", error: true });
        if (data.reason) { statusInfo = { available: false, reason: data.reason }; renderSetup(); }
      } else {
        messages.push({ role: "assistant", content: data.reply, actions: data.actions || [], steps: data.steps || [] });
        if ((data.actions || []).length) document.dispatchEvent(new CustomEvent("advisor:changed"));
      }
    } catch (e) {
      messages.push({ role: "assistant", content: "Couldn't reach the app. Is it still running?", error: true });
    }
    busy = false; live = []; save(); render();
  }

  function open(on) {
    const panel = $("advisor-panel");
    panel.hidden = !on;
    fab.hidden = on;
    fab.setAttribute("aria-expanded", String(on));
    if (on) { checkStatus(); setTimeout(() => $("advisor-input").focus(), 50); }
  }

  fab.addEventListener("click", () => open(true));
  $("advisor-close").addEventListener("click", () => open(false));
  $("advisor-clear").addEventListener("click", () => { messages = []; save(); render(); });
  $("advisor-form").addEventListener("submit", (e) => { e.preventDefault(); send($("advisor-input").value); });
  $("advisor-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send($("advisor-input").value); }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("advisor-panel").hidden) open(false); });

  $("advisor-input").addEventListener("input", autoGrow);

  load();
  render();
})();
