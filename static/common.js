// Escapes text for safe use inside innerHTML.
function escapeHtml(str) {
  return String(str == null ? "" : str).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// Shared across every page (loaded from base.html) -- keeps a small,
// always-visible status strip in sync so it's never a mystery what data
// the app currently has loaded, without having to click into each page.
(async function () {
  const el = document.getElementById("status-strip");
  if (!el) return;

  // Each request gets its own 8 s timeout and may fail on its own, so the strip
  // always ends up showing something (never stuck on "Loading your data…").
  const get = async (url) => {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 8000);
    try {
      const res = await fetch(url, { signal: ctl.signal });
      if (!res.ok) throw new Error(String(res.status));
      return await res.json();
    } finally {
      clearTimeout(timer);
    }
  };

  try {
    let s;
    try { s = await get("/api/status"); } catch (e) {
      el.innerHTML = `<span class="empty">Couldn't load status. Is the app still running?</span>`;
      return;
    }
    if (!s.sections && !s.progress) {
      el.innerHTML = `<span class="empty">No data loaded yet — pick a sample plan or import your degree audit on the <a href="/curriculum" style="color:inherit;font-weight:700;">Curriculum</a> page. The admin loads this term's courses.</span>`;
      return;
    }
    const chip = (icon, html, cls) => `<span class="status-chip${cls ? " " + cls : ""}"><span aria-hidden="true">${icon}</span> ${html}</span>`;
    const n = (x) => (Math.round(Number(x) * 10) / 10).toString();
    const parts = [];
    if (s.progress) parts.push(chip("🎯", `<strong>${n(s.progress.done)} / ${n(s.progress.total)}</strong> credits · ${Math.round(s.progress.percent)}%`, "progress"));
    if (s.program) parts.push(chip("💻", escapeHtml(s.program), "program"));
    parts.push(chip("📚", `<strong>${s.sections}</strong> section${s.sections === 1 ? "" : "s"} this term`));
    parts.push(chip("✅", `<strong>${s.required_left}</strong> required left`));
    parts.push(chip("⭐", `<strong>${s.wishlist}</strong> on wishlist`));
    el.innerHTML = parts.join("");
  } catch (e) {
    el.innerHTML = `<span class="empty">Couldn't load status.</span>`;
  }
})();


// ---------------------------------------------------------------------------
// Weekly timetable (days as columns, time as rows) drawn from section dicts.
// Used by the Plan page and the Compare page. Two sections at the same time
// are drawn side by side and outlined red instead of hiding one.
// ---------------------------------------------------------------------------
const TT_COLORS = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"];
const TT_ALL_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function _ttMinutes(hhmm) {
  const [h, m] = String(hhmm).split(":").map(Number);
  return h * 60 + m;
}

function timetableHtml(sections, opts) {
  const o = Object.assign({ compact: false, minHour: 8, maxHour: 18 }, opts || {});
  const timed = (sections || []).filter((s) => s.start && s.end && (s.days || []).length && !s.online);
  const online = (sections || []).filter((s) => !timed.includes(s));
  const days = TT_ALL_DAYS.filter((d, i) => i < 5 || timed.some((s) => s.days.includes(d)));
  let lo = o.minHour, hi = o.maxHour;
  timed.forEach((s) => {
    lo = Math.min(lo, Math.floor(_ttMinutes(s.start) / 60));
    hi = Math.max(hi, Math.ceil(_ttMinutes(s.end) / 60));
  });
  const hours = hi - lo, span = hours * 60;
  const codes = [...new Set((sections || []).map((s) => s.code))];
  // Compact blocks show the course number ("111"); if two courses in the plan share a number
  // ("COSC 111" and "MATH 111") they show the full code so labels are always unique.
  const numOf = (c) => String(c).trim().split(/\s+/).pop();
  const numCount = {};
  codes.forEach((c) => { numCount[numOf(c)] = (numCount[numOf(c)] || 0) + 1; });
  const shortLabel = (c) => (numCount[numOf(c)] > 1 ? c : numOf(c));

  const cols = days.map((day) => {
    const items = timed.filter((s) => s.days.includes(day))
      .map((s) => ({ s, a: _ttMinutes(s.start), b: _ttMinutes(s.end) })).sort((x, y) => x.a - y.a || x.b - y.b);
    // Group transitively-overlapping meetings into clusters, then give each a lane.
    const clusters = [];
    items.forEach((it) => {
      const last = clusters[clusters.length - 1];
      if (last && it.a < last.end) { last.items.push(it); last.end = Math.max(last.end, it.b); }
      else clusters.push({ items: [it], end: it.b });
    });
    let html = "";
    clusters.forEach((cl) => {
      const laneEnds = [];
      cl.items.forEach((it) => {
        let lane = laneEnds.findIndex((e) => e <= it.a);
        if (lane === -1) { lane = laneEnds.length; laneEnds.push(0); }
        laneEnds[lane] = it.b;
        it.lane = lane;
      });
      const n = laneEnds.length;
      cl.items.forEach((it) => {
        const s = it.s;
        const top = ((it.a - lo * 60) / span) * 100, height = ((it.b - it.a) / span) * 100;
        const tip = `${s.code}-${s.section} ${s.title || ""}\n${s.start}-${s.end}` + (s.location ? `\nRoom: ${s.location}` : "") + (s.instructor ? `\n${s.instructor}` : "");
        const meta = o.compact ? "" : `<span class="tt-meta">${escapeHtml(s.start)}–${escapeHtml(s.end)}</span>` + (s.location ? `<span class="tt-meta">${escapeHtml(s.location)}</span>` : "");
        html += `<div class="tt-block${n > 1 ? " tt-clash" : ""}" title="${escapeHtml(tip)}" style="top:${top}%;height:${height}%;left:${(it.lane / n) * 100}%;width:${100 / n}%;background:var(--${TT_COLORS[codes.indexOf(s.code) % TT_COLORS.length]})">` +
          `<span class="tt-code">${o.compact ? escapeHtml(shortLabel(s.code)) : escapeHtml(s.code) + "-" + escapeHtml(s.section)}</span>${meta}</div>`;
      });
    });
    return `<div class="tt-day">${html}</div>`;
  }).join("");

  let times = "";
  for (let h = lo; h <= hi; h++) {
    if (h === lo || (o.compact && (h - lo) % 2) || h === hi) continue;
    times += `<span style="top:${((h - lo) / hours) * 100}%">${h}:00</span>`;
  }
  const onlineNote = online.length
    ? `<p class="tt-online">Online / no fixed time: ${online.map((s) => escapeHtml(`${s.code}-${s.section}`)).join(", ")}</p>` : "";
  const legend = o.legend
    ? `<div class="tt-legend">${codes.map((c) => `<span><i style="background:var(--${TT_COLORS[codes.indexOf(c) % TT_COLORS.length]})"></i>${escapeHtml(c)}</span>`).join("")}</div>` : "";
  return `<div class="tt${o.compact ? " tt-compact" : ""}" style="--days:${days.length};--hours:${hours}">` +
    `<div class="tt-head"><span></span>${days.map((d) => `<span>${d}</span>`).join("")}</div>` +
    `<div class="tt-body"><div class="tt-times">${times}</div>${cols}</div></div>${onlineNote}${legend}`;
}

// ---------------------------------------------------------------------------
// Calendar (.ics) download for a list of sections. Returns a sentence saying
// what was exported; throws an Error with a readable message on failure.
// ---------------------------------------------------------------------------
function describeIcsExport(info) {
  const n = info.exported || 0;
  let msg = n
    ? `Downloaded — ${n} repeating class${n === 1 ? "" : "es"}, one per course (not one event per day).`
    : "Downloaded — academic dates only.";
  const src = info.dates_from || {};
  if (src.none) {
    msg += ` ${src.none} had no known term dates, so ${src.none === 1 ? "it repeats" : "they repeat"} for 15 weeks from the next class day.`;
  }
  if (n && info.breaks) msg += ` ${info.breaks} break${info.breaks === 1 ? "" : "s"} skipped.`;
  if (info.calendar_events) msg += ` Plus ${info.calendar_events} academic date${info.calendar_events === 1 ? "" : "s"} (holidays, deadlines, exams) as all-day events.`;
  if (info.skipped && info.skipped.length) {
    msg += ` Not included (no fixed meeting time): ${info.skipped.join(", ")}.`;
  }
  return msg;
}

// Download a PDF the server builds (works in every browser, unlike pop-up print windows).
async function downloadServerPdf(url, filename, statusEl) {
  if (statusEl) statusEl.textContent = "Building the PDF…";
  try {
    const res = await fetch(url);
    if (!res.ok) {
      let detail = "";
      try { detail = (await res.json()).error || ""; } catch (e) { /* not JSON */ }
      if (statusEl) statusEl.textContent = detail || `The PDF export failed (${res.status}).`;
      return false;
    }
    const href = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = href; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(href), 2000);
    if (statusEl) statusEl.textContent = `Downloaded ${filename}.`;
    return true;
  } catch (e) {
    if (statusEl) statusEl.textContent = "Couldn't reach the server to build the PDF. Is the app still running?";
    return false;
  }
}

async function downloadPlanIcs(plan, label) {
  let res;
  try {
    res = await fetch("/api/plan/export/ics", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({}, plan, { label })),
    });
  } catch (e) {
    throw new Error(`Couldn't reach the server: ${e}`);
  }
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).error || ""; } catch (e) { detail = await res.text().catch(() => ""); }
    throw new Error(`Export failed (${res.status})${detail ? ": " + detail : ". Check the terminal running the app for the error."}`);
  }
  let info = {};
  try { info = JSON.parse(res.headers.get("X-Export-Info") || "{}"); } catch (e) { /* header is optional */ }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `registration_plan_${label}.ics`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return describeIcsExport(info);
}

function planKeyOf(sections) {
  return sections.map((s) => `${s.code}-${s.section}`).sort().join("|");
}


// Mobile navigation: the ☰ button shows/hides the menu below 960px (and turns into ✕).
(function () {
  const btn = document.getElementById("nav-toggle"), links = document.getElementById("nav-links");
  if (!btn || !links) return;
  btn.addEventListener("click", () => {
    const open = links.classList.toggle("open");
    btn.setAttribute("aria-expanded", String(open));
    btn.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    btn.firstElementChild.textContent = open ? "✕" : "☰";
  });
})();

// Desktop user menu: click your name for "Signed in as … / Log out".
(function () {
  const btn = document.getElementById("user-btn"), menu = document.getElementById("user-menu");
  if (!btn || !menu) return;
  const set = (open) => { menu.hidden = !open; btn.setAttribute("aria-expanded", String(open)); };
  btn.addEventListener("click", (e) => { e.stopPropagation(); set(menu.hidden); });
  document.addEventListener("click", (e) => { if (!menu.hidden && !menu.contains(e.target)) set(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) { set(false); btn.focus(); } });
})();


// In-page replacement for window.confirm(). Some embedded browsers (e.g. the Claude desktop app's
// browser pane) block pop-up dialogs, so confirm() silently answers "no" and the button seems dead.
// Usage: if (!(await askConfirm("Are you sure?", "Yes, do it"))) return;
window.askConfirm = function (message, okLabel) {
  return new Promise((resolve) => {
    const prev = document.activeElement;
    const overlay = document.createElement("div");
    overlay.className = "confirm-overlay";
    overlay.innerHTML = `<div class="confirm-box" role="alertdialog" aria-modal="true" aria-label="Please confirm">
        <p class="confirm-msg"></p>
        <div class="confirm-actions">
          <button type="button" class="secondary confirm-no">Cancel</button>
          <button type="button" class="confirm-yes"></button>
        </div></div>`;
    overlay.querySelector(".confirm-msg").textContent = message;
    overlay.querySelector(".confirm-yes").textContent = okLabel || "Continue";
    const done = (answer) => {
      document.removeEventListener("keydown", onKey, true);
      overlay.remove();
      if (prev && prev.focus) prev.focus();
      resolve(answer);
    };
    const onKey = (e) => {
      if (e.key === "Escape") { e.stopPropagation(); done(false); }
      else if (e.key === "Tab") {                       // keep focus inside the dialog
        const b = [...overlay.querySelectorAll("button")];
        const i = b.indexOf(document.activeElement);
        e.preventDefault();
        b[(i + (e.shiftKey ? b.length - 1 : 1)) % b.length].focus();
      }
    };
    overlay.querySelector(".confirm-no").addEventListener("click", () => done(false));
    overlay.querySelector(".confirm-yes").addEventListener("click", () => done(true));
    overlay.addEventListener("click", (e) => { if (e.target === overlay) done(false); });
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(overlay);
    overlay.querySelector(".confirm-yes").focus();
  });
};
