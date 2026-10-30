// AI advisor drawer (loaded on every page for logged-in students).
(function () {
  const $ = (id) => document.getElementById(id);
  const fab = $("advisor-fab");
  if (!fab) return;

  const KEY = "advisor-chat-v1";
  let messages = []; // [{role, content, actions?}]
  let busy = false;
  let statusInfo = null;

  const SUGGESTIONS = [
    "What should I take next term?",
    "What do I need this term to reach a 3.8 GPA?",
    "Can I graduate by Spring 2028?",
    "Explain why my best plan ranks first",
    "No classes before 10am and keep Fridays free",
  ];

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
    messages.forEach((m) => {
      const div = document.createElement("div");
      div.className = `advisor-msg ${m.role}`;
      div.innerHTML = m.role === "assistant" ? format(m.content) : `<p>${esc(m.content)}</p>`;
      if (m.actions && m.actions.length) {
        const chips = document.createElement("div");
        chips.className = "advisor-actions";
        chips.innerHTML = m.actions.map((a) => `<span class="advisor-chip">${esc(a)}</span>`).join("");
        div.appendChild(chips);
      }
      if (m.error) div.classList.add("error");
      log.appendChild(div);
    });
    if (busy) {
      const t = document.createElement("div");
      t.className = "advisor-msg assistant thinking";
      t.textContent = "Thinking…";
      log.appendChild(t);
    }
    log.scrollTop = log.scrollHeight;
    $("advisor-suggest").hidden = messages.length > 0 || !(statusInfo && statusInfo.available);
    $("advisor-send").disabled = busy;
  }

  function renderSuggestions() {
    $("advisor-suggest").innerHTML = SUGGESTIONS.map((s) => `<button type="button" class="advisor-suggest-btn">${esc(s)}</button>`).join("");
    document.querySelectorAll(".advisor-suggest-btn").forEach((b) => { b.onclick = () => send(b.textContent); });
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
      : `<p><strong>The advisor needs an AI model.</strong> Whoever runs the app picks one of these, in the terminal, before starting it. Option 1 is free and private.</p>
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
    render();
  }

  async function send(text) {
    text = (text || "").trim();
    if (!text || busy) return;
    messages.push({ role: "user", content: text });
    $("advisor-input").value = "";
    busy = true; save(); render();
    try {
      const res = await fetch("/api/ai/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: messages.filter((m) => !m.error).map((m) => ({ role: m.role, content: m.content })) }),
      });
      const data = await res.json();
      if (!res.ok) {
        messages.push({ role: "assistant", content: data.error || "Something went wrong.", error: true });
        if (data.reason) { statusInfo = { available: false, reason: data.reason }; renderSetup(); }
      } else {
        messages.push({ role: "assistant", content: data.reply, actions: data.actions || [] });
        if ((data.actions || []).length) document.dispatchEvent(new CustomEvent("advisor:changed"));
      }
    } catch (e) {
      messages.push({ role: "assistant", content: "Couldn't reach the app. Is it still running?", error: true });
    }
    busy = false; save(); render();
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

  load();
  renderSuggestions();
  render();
})();
