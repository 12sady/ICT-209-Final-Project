const PALETTE = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"];

let planData = null;
let activeIndex = 0;
let sortMode = "best";
let alternatesRequest = 0;
let choices = { pins: [], active: null, max_pins: 3 };

async function loadChoices() {
  try { choices = await (await fetch("/api/plan/choices")).json(); } catch (e) { /* keep defaults */ }
}

const keysOfPlan = (plan) => plan.sections.map((s) => ({ code: s.code, section: s.section }));
const isPinned = (plan) => choices.pins.some((p) => p.key === planKeyOf(plan.sections));
const isActive = (plan) => !!choices.active && choices.active.key === planKeyOf(plan.sections);

function updateChoiceButtons() {
  if (!planData || !planData.plans.length) return;
  const plan = planData.plans[activeIndex];
  const pinned = isPinned(plan), active = isActive(plan);
  const pin = document.getElementById("pin-btn");
  pin.textContent = pinned ? "Unpin from compare" : `Pin to compare (${choices.pins.length}/${choices.max_pins})`;
  document.getElementById("active-btn").textContent = active ? "Active plan ✓ (click to clear)" : "Make this my active plan";
  const link = document.getElementById("compare-link");
  link.hidden = !choices.pins.length;
  link.textContent = `Compare ${choices.pins.length} pinned plan${choices.pins.length === 1 ? "" : "s"} →`;
}

async function togglePin() {
  const plan = planData.plans[activeIndex];
  const status = document.getElementById("export-status");
  if (isPinned(plan)) {
    const pin = choices.pins.find((p) => p.key === planKeyOf(plan.sections));
    await fetch(`/api/plan/pins/${encodeURIComponent(pin.id)}`, { method: "DELETE" });
  } else {
    const res = await fetch("/api/plan/pins", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sections: keysOfPlan(plan) }) });
    if (!res.ok) { status.textContent = (await res.json()).error || "Couldn't pin that plan."; return; }
  }
  status.textContent = "";
  await loadChoices();
  renderTabs();
  updateChoiceButtons();
}

async function toggleActive() {
  const plan = planData.plans[activeIndex];
  const wasActive = isActive(plan);
  const res = await fetch("/api/plan/active", wasActive
    ? { method: "DELETE" }
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sections: keysOfPlan(plan) }) });
  if (!res.ok) { document.getElementById("export-status").textContent = (await res.json()).error || "Couldn't change the active plan."; return; }
  document.getElementById("export-status").textContent = wasActive ? "Active plan cleared." : "This is now your active plan.";
  await loadChoices();
  renderTabs();
  updateChoiceButtons();
}

let viewMode = "week";
try { viewMode = localStorage.getItem("plan-view") === "list" ? "list" : "week"; } catch (e) { /* storage blocked */ }

function colorForCode(code, codeList) {
  return PALETTE[codeList.indexOf(code) % PALETTE.length];
}

async function loadPlans() {
  const res = await fetch("/api/plans");
  planData = await res.json();
  await loadChoices();

  // Rebuild full section objects from the shared pool, and remember the
  // server's best-first order so "Best fit" can be restored after re-sorting.
  planData.plans.forEach((plan, i) => {
    plan.sections = plan.picks.map((idx) => planData.section_pool[idx]);
    plan.rank = i;
  });

  document.getElementById("program-name").textContent = planData.program;
  renderBanners();
  activeIndex = 0;

  if (!planData.plans.length) {
    document.getElementById("calendar-legend").innerHTML = "";
    document.getElementById("calendar").innerHTML = `
      <div class="empty-state">
        <p>${planData.wishlist_count
          ? "None of your wishlist courses can be scheduled right now."
          : "Your wishlist is empty, so there's nothing to plan yet."}</p>
        <p>${planData.wishlist_count
          ? `Check the notes above — a course may be missing a prerequisite or not offered this term. You can also remove it from your wishlist at the right.`
          : `Add the courses you want in <a href="/browse">Browse &amp; Wishlist</a> and your plan will appear here.`}</p>
      </div>`;
    document.getElementById("plan-tabs").innerHTML = "";
    document.getElementById("plan-export-bar").hidden = true;
    document.getElementById("plan-export-bar2").hidden = true;
    document.getElementById("plan-summary").innerHTML = "";
    document.getElementById("alternates-list").innerHTML = `<p class="hint">No plan to show backups for.</p>`;
    return;
  }

  document.getElementById("plan-export-bar").hidden = false;
  document.getElementById("plan-export-bar2").hidden = false;
  applySort();
  // Open on the student's active plan when it's still one of the valid plans.
  const act = choices.active ? planData.plans.findIndex((p) => planKeyOf(p.sections) === choices.active.key) : -1;
  activeIndex = Math.max(0, act);
  renderTabs();
  renderPlan(activeIndex);
}

function renderBanners() {
  const el = document.getElementById("banners");
  el.innerHTML = "";

  const req = planData.blocked_required || [];
  const wl = planData.blocked_wishlist || [];
  const noSec = planData.no_sections || [];

  if (planData.ignore_prereqs) {
    const b = document.createElement("div");
    b.className = "banner warn";
    b.innerHTML = `<strong>Ignoring prerequisites</strong> — this plan may include courses you haven't met the requirements for yet. Turn this off in Planning preferences once you're scheduling for real.`;
    el.appendChild(b);
  }
  if (req.length) {
    const b = document.createElement("div");
    b.className = "banner danger";
    b.innerHTML = `<strong>Can't schedule yet — missing prerequisites:</strong> ` +
      req.map((r) => `${r.code} (needs ${r.missing_prereqs.join(", ") || "a prereq"})`).join("; ");
    el.appendChild(b);
  }
  // Wishlist courses that can't be in any plan this term: one short line of chips
  // instead of a full-width yellow bar per reason. Hover a chip for the reason.
  const chips = [
    ...noSec.map((code) => `<span class="left-chip gray" title="No sections of ${escapeHtml(code)} are offered this term">Not offered · <strong>${escapeHtml(code)}</strong></span>`),
    ...wl.map((r) => {
      const need = r.missing_prereqs.join(", ") || "a prerequisite";
      return `<span class="left-chip warn" title="You haven't completed ${escapeHtml(need)} yet">Needs ${escapeHtml(need)} · <strong>${escapeHtml(r.code)}</strong></span>`;
    }),
  ];
  if (chips.length) {
    const b = document.createElement("div");
    b.className = "left-out";
    b.innerHTML = `<span class="left-out-label">Left out of every plan:</span> ${chips.join("")}`;
    el.appendChild(b);
  }
}

const SORTS = {
  best: { label: "Best fit", cmp: (a, b) => a.rank - b.rank },
  days: { label: "Fewest days on campus", cmp: (a, b) => a.days_on_campus - b.days_on_campus || a.gap_minutes - b.gap_minutes || a.rank - b.rank },
  gaps: { label: "Fewest gaps between classes", cmp: (a, b) => a.gap_minutes - b.gap_minutes || a.days_on_campus - b.days_on_campus || a.rank - b.rank },
  late: { label: "Latest start", cmp: (a, b) => (b.earliest_start ?? 0) - (a.earliest_start ?? 0) || a.rank - b.rank },
  credits: { label: "Most credits", cmp: (a, b) => b.total_credits - a.total_credits || a.rank - b.rank },
};

function applySort() {
  planData.plans.sort(SORTS[sortMode].cmp);
  planData.plans.forEach((plan, i) => { plan.label = String(i + 1); });
}

function fmtMinutes(m) {
  if (m == null) return "—";
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`;
}

function planOptionText(plan) {
  const drops = plan.unmet_wishlist.length ? ` · drops ${plan.unmet_wishlist.join(", ")}` : "";
  return `${isActive(plan) ? "★ " : ""}${isPinned(plan) ? "📌 " : ""}Plan ${plan.label} · ${plan.total_credits} cr · ${plan.days_on_campus} day${plan.days_on_campus === 1 ? "" : "s"} · starts ${fmtMinutes(plan.earliest_start)}${drops}`;
}

function selectPlan(i) {
  activeIndex = Math.max(0, Math.min(planData.plans.length - 1, i));
  document.getElementById("plan-select").value = String(activeIndex);
  updatePickerButtons();
  renderPlan(activeIndex);
}

function updatePickerButtons() {
  document.getElementById("plan-prev").disabled = activeIndex <= 0;
  document.getElementById("plan-next").disabled = activeIndex >= planData.plans.length - 1;
}

function renderTabs() {
  const total = planData.plans.length;
  const found = planData.total_found;
  const more = found > total || !planData.exhausted;
  const note = more
    ? `Showing the best ${total.toLocaleString()} of ${found.toLocaleString()}${planData.exhausted ? "" : "+"} possible plans — remove a course or skip early sections to narrow it down.`
    : total === 1 ? "1 possible plan" : `All ${total.toLocaleString()} possible plans`;
  const el = document.getElementById("plan-tabs");
  el.innerHTML = `
    <div class="plan-picker">
      <button id="plan-prev" class="secondary" aria-label="Previous plan">‹</button>
      <select id="plan-select" aria-label="Choose a plan"></select>
      <button id="plan-next" class="secondary" aria-label="Next plan">›</button>
      <select id="plan-sort" aria-label="Sort plans"></select>
    </div>
    <p class="hint plan-count">${note}</p>`;

  const sel = document.getElementById("plan-select");
  planData.plans.forEach((plan, i) => sel.add(new Option(planOptionText(plan), String(i))));
  sel.value = String(activeIndex);
  sel.onchange = () => selectPlan(Number(sel.value));
  document.getElementById("plan-prev").onclick = () => selectPlan(activeIndex - 1);
  document.getElementById("plan-next").onclick = () => selectPlan(activeIndex + 1);

  const sortSel = document.getElementById("plan-sort");
  Object.entries(SORTS).forEach(([key, v]) => sortSel.add(new Option("Sort: " + v.label, key)));
  sortSel.value = sortMode;
  sortSel.onchange = () => {
    sortMode = sortSel.value;
    applySort();
    activeIndex = 0;
    renderTabs();
    renderPlan(0);
  };
  updatePickerButtons();
}

function cssVarFor(varName) {
  return getComputedStyle(document.documentElement).getPropertyValue(`--${varName}`);
}

function setView(mode) {
  viewMode = mode;
  try { localStorage.setItem("plan-view", mode); } catch (e) { /* ignore */ }
  document.getElementById("view-week").setAttribute("aria-pressed", String(mode === "week"));
  document.getElementById("view-list").setAttribute("aria-pressed", String(mode === "list"));
  document.getElementById("calendar").hidden = mode !== "week";
  document.getElementById("plan-list").hidden = mode !== "list";
}

function listHtml(plan) {
  const rows = plan.sections.map((s) => `<tr>
    <td class="code-cell">${escapeHtml(s.code)}-${escapeHtml(s.section)}</td><td class="wrap">${escapeHtml(s.title || "")}</td>
    <td class="nw">${s.start && s.end && (s.days || []).length ? `${escapeHtml(s.days.join(" "))} ${escapeHtml(s.start)}–${escapeHtml(s.end)}` : "Online / no fixed time"}</td>
    <td class="nw">${escapeHtml(s.location || "—")}</td><td class="wrap">${escapeHtml(s.instructor || "—")}</td><td class="num">${escapeHtml(s.credits ?? "")}</td></tr>`).join("");
  return `<table class="course-table"><thead><tr><th>Section</th><th>Title</th><th>When</th><th>Room</th><th>Instructor</th><th class="num">Cr</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderPlan(index) {
  const plan = planData.plans[index];
  const codeList = [...new Set(plan.sections.map((s) => s.code))];
  const onlineSections = plan.sections.filter((s) => !s.start || !s.end || !(s.days || []).length || s.online);

  document.getElementById("calendar").innerHTML = timetableHtml(plan.sections, {});
  document.getElementById("plan-list").innerHTML = listHtml(plan);
  document.getElementById("print-title").innerHTML =
    `<h2>Registration plan ${escapeHtml(plan.label)}</h2><p>${escapeHtml(planData.program || "")} · ${escapeHtml(plan.total_credits)} credits</p>`;
  setView(viewMode);

  renderLegend(plan, codeList);
  renderSummary(plan, onlineSections);
  renderWhy(plan);
  loadAlternates(plan);
  updateChoiceButtons();
}

// ---------------------------------------------------------------------------
// "Why this schedule?" -- how the planner's constraint search got here
// (scheduler.enumerate_plans fills planData.search) and why this plan ranks
// where it does. Nothing is recomputed here; it only explains.
// ---------------------------------------------------------------------------

const _RANK_RULES = [
  { label: "fits more of your wishlist", value: (p) => p.unmet_wishlist.length, show: (p) => `${p.sections.length} course${p.sections.length === 1 ? "" : "s"}` },
  { label: "meets your minimum credits", value: (p) => (p.meets_min_credits ? 0 : 1), show: (p) => (p.meets_min_credits ? "meets it" : "below it") },
  { label: "is closer to your credit limit", value: (p) => Math.abs(planData.max_credits - p.total_credits), show: (p) => `${p.total_credits} cr` },
  { label: "has fewer days on campus", value: (p) => p.days_on_campus, show: (p) => `${p.days_on_campus} day${p.days_on_campus === 1 ? "" : "s"}` },
  { label: "has less waiting between classes", value: (p) => p.gap_minutes || 0, show: (p) => `${Math.round(p.gap_minutes || 0)} min` },
];

function plural(n, word) { return `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`; }

function whyRanking(plan) {
  const byRank = [...planData.plans].sort((a, b) => a.rank - b.rank);
  const pos = byRank.indexOf(plan);
  const rules = `<ol class="why-rules">${_RANK_RULES.map((r) => `<li>${escapeHtml(r.label)}</li>`).join("")}</ol>`;
  const intro = `<p class="hint">Valid plans are ranked by these rules, in order. A later rule only matters when the earlier ones are tied:</p>${rules}`;
  if (byRank.length < 2) return intro + `<p>This is the only valid plan, so it's first.</p>`;
  const other = pos === 0 ? byRank[1] : byRank[pos - 1];
  const rule = _RANK_RULES.find((r) => r.value(plan) !== r.value(other));
  const name = (p) => `Plan ${escapeHtml(p.label)}`;
  let verdict;
  if (!rule) verdict = `${name(plan)} and ${name(other)} tie on every rule; they're just listed in course-code order.`;
  else if (pos === 0) verdict = `<strong>${name(plan)} is the best fit</strong>: compared with the runner-up (${name(other)}), it ${rule.label} (${rule.show(plan)} vs ${rule.show(other)}).`;
  else verdict = `${name(plan)} is <strong>#${pos + 1}</strong> in best-fit order: the plan just above it (${name(other)}) ${rule.label} (${rule.show(other)} vs ${rule.show(plan)}).`;
  return intro + `<p>${verdict}</p>`;
}

function renderWhy(plan) {
  const card = document.getElementById("why-card");
  const s = planData.search;
  if (!s || !s.wishlist_courses) { card.hidden = true; return; }
  card.hidden = false;
  const offered = s.courses.reduce((a, c) => a + c.sections, 0);
  const rm = s.removed_before_search;
  const removed = [
    rm.too_early ? `${plural(rm.too_early, "section")} start before ${escapeHtml(planData.avoid_before)}` : "",
    rm.day_off ? `${plural(rm.day_off, "section")} meet on a day you keep free (${escapeHtml(planData.avoid_days.join(", "))})` : "",
    rm.full ? `${plural(rm.full, "section")} ${rm.full === 1 ? "is" : "are"} full` : "",
  ].filter(Boolean);
  const clashes = (s.clashes || []).map((c) =>
    `<li><span class="nw">${escapeHtml(c.a)}</span> and <span class="nw">${escapeHtml(c.b)}</span> both meet ${escapeHtml(c.days.join(", "))} (${escapeHtml(c.a_time)} vs ${escapeHtml(c.b_time)})</li>`).join("");
  const fitAll = s.most_courses_that_fit === s.wishlist_courses;
  document.getElementById("why-body").innerHTML = `
    <p class="hint">The planner treats your timetable as a <strong>constraint satisfaction problem</strong>: pick one section per course so that no two classes overlap, credits stay at or under ${planData.max_credits}, and your preferences hold. It searches by <strong>backtracking</strong>: choose a section, move to the next course, and step back to try another section whenever a rule breaks.</p>
    <h3 class="why-h">How it searched</h3>
    <ul class="why-list">
      <li>Your wishlist: <strong>${plural(s.wishlist_courses, "course")}</strong> with ${plural(offered, "section")} offered.</li>
      <li>Removed before searching: ${removed.length ? removed.join("; ") : "none (no section broke your preferences)"}.</li>
      <li>Explored <strong>${plural(s.steps, "step")}</strong> of the search tree${s.exhausted ? "" : " (stopped early: too many possibilities)"}.</li>
      <li>Refused <strong>${plural(s.rejected.time_clash, "choice")}</strong> because of a time clash${s.rejected.over_credits ? ` and <strong>${plural(s.rejected.over_credits, "choice")}</strong> for going over ${planData.max_credits} credits` : ""}.</li>
      <li>Result: <strong>${plural(s.valid_plans, "valid plan")}</strong> ${fitAll ? `fit all ${s.wishlist_courses} courses` : `fit at most ${s.most_courses_that_fit} of your ${s.wishlist_courses} courses together`}.</li>
    </ul>
    ${clashes ? `<h3 class="why-h">Example clashes it avoided</h3><ul class="why-list">${clashes}</ul>${s.clash_pairs > s.clashes.length ? `<p class="hint">…and ${plural(s.clash_pairs - s.clashes.length, "more clashing pair")}.</p>` : ""}` : ""}
    <h3 class="why-h">Why this plan is ranked here</h3>
    ${whyRanking(plan)}`;
}

function renderLegend(plan, codeList) {
  const legend = document.getElementById("calendar-legend");
  legend.innerHTML = codeList
    .map((code) => {
      const sec = plan.sections.find((s) => s.code === code);
      const color = cssVarFor(colorForCode(code, codeList));
      return `<span class="legend-item"><span class="swatch" style="background:${color}"></span>${code} — ${sec ? sec.title : ""}</span>`;
    })
    .join("");
}

function fmtWait(m) {
  m = Math.round(m || 0);
  if (!m) return "None";
  const h = Math.floor(m / 60), r = m % 60;
  return h ? `${h} h${r ? ` ${r} m` : ""}` : `${r} m`;
}

// Six small tiles instead of a tall list; extra notes underneath only when they matter.
function renderSummary(plan, onlineSections) {
  const box = document.getElementById("plan-summary");
  const dropped = (plan.unmet_wishlist || []).length;
  const tile = (label, value, cls) => `<div class="sum-tile${cls ? " " + cls : ""}"><span>${label}</span><strong>${value}</strong></div>`;
  let html = `<div class="sum-tiles">
    ${tile("Credits", plan.total_credits, plan.meets_min_credits ? "" : "low")}
    ${tile("Courses", plan.sections.length)}
    ${tile("Days", plan.days_on_campus)}
    ${tile("Starts", fmtMinutes(plan.earliest_start))}
    ${tile("Waiting", fmtWait(plan.gap_minutes))}
    ${tile("Dropped", dropped, dropped ? "low" : "")}
  </div>`;
  if (!plan.meets_min_credits) {
    const short = planData.min_credits - plan.total_credits;
    html += `<div class="sum-warn"><span>⚠ ${short} credit${short === 1 ? "" : "s"} below your ${planData.min_credits}-credit minimum</span>
      <a class="sum-fix" href="/browse">Find a course →</a></div>`;
  }
  if (dropped) {
    html += `<p class="sum-note"><strong>Didn't fit this plan:</strong> ${plan.unmet_wishlist.map(escapeHtml).join(", ")}. Remove one from your wishlist to try fitting the rest.</p>`;
  }
  if (onlineSections && onlineSections.length) {
    html += `<p class="sum-note"><strong>Online / no fixed time:</strong> ${onlineSections.map((s) => `${escapeHtml(s.code)}-${escapeHtml(s.section)}`).join(", ")} (listed under the timetable)</p>`;
  }
  box.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Your wishlist, editable right here -- so if something didn't make it into
// the plan (shown above), you can see everything you've added and remove
// one on the spot to see what changes, instead of bouncing to Browse.
// ---------------------------------------------------------------------------

async function loadWishlistPanel() {
  const res = await fetch("/api/wishlist");
  const data = await res.json();
  const el = document.getElementById("plan-wishlist-items");
  const items = data.wishlist || [];
  if (!items.length) {
    el.innerHTML = `<p class="hint">Nothing on your wishlist yet — add courses from <a href="/browse">Browse &amp; Wishlist</a>.</p>`;
    return;
  }
  const statusLabel = { ok: "ready", blocked: "needs prereq", not_offered: "not offered" };
  el.innerHTML = "";
  items.forEach((w) => {
    const row = document.createElement("div");
    row.className = "wl-item";
    const d = w.demand && w.demand.others
      ? `<br><span class="demand-badge demand-${w.demand.level}">${w.demand.others === 1 ? "1 other student" : w.demand.others + " other students"} wishlisted${w.demand.level === "high" ? " · High demand" : w.demand.level === "popular" ? " · Popular" : ""}</span>`
      : "";
    row.innerHTML = `<span>${w.code} <span class="wl-status ${w.status}">${statusLabel[w.status] || w.status}</span>${d}</span>`;
    const removeBtn = document.createElement("button");
    removeBtn.textContent = "Remove";
    removeBtn.className = "secondary";
    removeBtn.onclick = async () => {
      await fetch(`/api/wishlist/${encodeURIComponent(w.code)}`, { method: "DELETE" });
      await loadWishlistPanel();
      await loadPlans();
    };
    row.appendChild(removeBtn);
    el.appendChild(row);
  });
}

async function loadAlternates(plan) {
  const list = document.getElementById("alternates-list");
  const mine = ++alternatesRequest;
  list.innerHTML = `<p class="hint">Checking backups…</p>`;
  let alternates = {};
  try {
    const res = await fetch("/api/plan/alternates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sections: plan.sections.map((s) => ({ code: s.code, section: s.section })) }),
    });
    alternates = (await res.json()).alternates || {};
  } catch (e) {
    list.innerHTML = `<p class="hint">Couldn't load backups.</p>`;
    return;
  }
  if (mine !== alternatesRequest) return; // a newer plan was selected meanwhile
  list.innerHTML = "";
  const withBackups = Object.entries(alternates).filter(([, backups]) => backups && backups.length);
  if (!withBackups.length) {
    list.innerHTML = `<p class="hint">No flagged backups for this plan.</p>`;
    return;
  }
  withBackups.forEach(([from, backups]) => {
    const row = document.createElement("div");
    row.className = "alt-row";
    const backupText = backups.map((b) => `${b.code}-${b.section}`).join(" or ");
    row.innerHTML = `<span class="from">${from}</span> full? try <span class="to">${backupText}</span>`;
    list.appendChild(row);
  });
}

// ---------------------------------------------------------------------------
// Plan options (earliest start time, ignore prerequisites). They apply the
// moment you change them -- no separate save button.
// ---------------------------------------------------------------------------

async function loadPreferences() {
  const res = await fetch("/api/curriculum");
  const data = await res.json();
  const prefs = data.preferences || {};
  const sel = document.getElementById("p-avoid-before");
  const saved = prefs.avoid_before || "";
  if (saved && ![...sel.options].some((o) => o.value === saved)) {
    sel.add(new Option(saved, saved));
  }
  sel.value = saved;
  document.getElementById("p-ignore-prereqs").checked = !!prefs.ignore_prereqs;
}

async function savePreferences() {
  const statusEl = document.getElementById("p-save-status");
  statusEl.textContent = "Updating…";
  const cur = await (await fetch("/api/curriculum")).json();
  cur.preferences = cur.preferences || {};
  cur.preferences.avoid_before = document.getElementById("p-avoid-before").value;
  cur.preferences.ignore_prereqs = document.getElementById("p-ignore-prereqs").checked;
  const res = await fetch("/api/curriculum", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cur),
  });
  if (!res.ok) {
    statusEl.textContent = "Something went wrong saving.";
    return;
  }
  await loadPlans();
  await loadWishlistPanel();
  statusEl.textContent = "Plan updated.";
}

document.getElementById("p-avoid-before").addEventListener("change", savePreferences);
document.getElementById("p-ignore-prereqs").addEventListener("change", savePreferences);

// ---------------------------------------------------------------------------
// Export the currently active plan. ICS still comes from the server (pure
// stdlib, no extra install needed). PDF is built entirely in the browser --
// we open a printable page and let the browser's own print-to-PDF handle
// it, so this never depends on a Python package being installed on your
// machine.
// ---------------------------------------------------------------------------

function escapeHtml(str) {
  return String(str == null ? "" : str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function buildPrintableHtml(plan, program) {
  const rows = (plan.sections || [])
    .map((s) => `
      <tr>
        <td>${escapeHtml(s.code)}</td>
        <td>${escapeHtml(s.section || "")}</td>
        <td>${escapeHtml(s.title || "")}</td>
        <td>${escapeHtml((s.days || []).join(""))}</td>
        <td>${s.start && s.end ? `${escapeHtml(s.start)}–${escapeHtml(s.end)}` : "Online / TBA"}</td>
        <td>${escapeHtml(s.credits != null ? s.credits : "")}</td>
        <td>${escapeHtml(s.location || "")}</td>
        <td>${escapeHtml(s.instructor || "")}</td>
      </tr>`)
    .join("");

  const notes = [];
  if (plan.unmet_wishlist && plan.unmet_wishlist.length) {
    notes.push(`<p><strong>Wishlist not in this plan:</strong> ${escapeHtml(plan.unmet_wishlist.join(", "))}</p>`);
  }

  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Registration Plan ${escapeHtml(plan.label || "")}</title>
<link rel="stylesheet" href="${location.origin}/static/style.css">
<style>
  body { font-family: -apple-system, Helvetica, Arial, sans-serif; color: #1a1a1a; margin: 32px; background: #fff; }
  .tt { --row-h: 30px; margin-bottom: 20px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .subtitle { color: #555; margin: 0 0 20px; font-size: 13px; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 16px; }
  th, td { border: 1px solid #ccc; padding: 6px 8px; font-size: 12px; text-align: left; }
  th { background: #f2f2f2; }
  .notes p { font-size: 12px; margin: 4px 0; }
  .no-print { margin-top: 24px; }
  .no-print button {
    font-size: 14px; padding: 8px 16px; cursor: pointer;
    border: 1px solid #888; border-radius: 6px; background: #fff;
  }
  @media print { .no-print { display: none; } }
</style>
</head>
<body>
  <h1>Registration Plan ${escapeHtml(plan.label || "")}</h1>
  <p class="subtitle">${escapeHtml(program || "")} · Total credits: ${escapeHtml(plan.total_credits)}</p>
  ${timetableHtml(plan.sections, {})}
  <table>
    <thead><tr><th>Code</th><th>Sec</th><th>Title</th><th>Days</th><th>Time</th><th>Credits</th><th>Room</th><th>Instructor</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>
  <div class="notes">${notes.join("")}</div>
  <div class="no-print">
    <button onclick="window.print()">Print / Save as PDF</button>
  </div>
</body>
</html>`;
}

function printActivePlan() {
  const statusEl = document.getElementById("export-status");
  if (!planData || !planData.plans.length) {
    statusEl.textContent = "No plan to export yet.";
    return;
  }
  const plan = planData.plans[activeIndex];
  const html = buildPrintableHtml(plan, planData.program);
  const win = window.open("", "_blank");
  if (!win) {
    statusEl.textContent = "Your browser blocked the popup — allow popups for this page and try again.";
    return;
  }
  win.document.write(html);
  win.document.close();
  statusEl.textContent = "Opened a printable page in a new tab — use its Print button (or Ctrl/Cmd+P) and choose \"Save as PDF\".";
}

async function downloadActivePlan() {
  const statusEl = document.getElementById("export-status");
  if (!planData || !planData.plans.length) {
    statusEl.textContent = "No plan to export yet.";
    return;
  }
  statusEl.textContent = "Preparing download…";
  const plan = planData.plans[activeIndex];
  try {
    const incl = document.getElementById("ics-include-dates");
    statusEl.textContent = await downloadPlanIcs({ ...plan, program: planData.program, include_calendar: incl ? incl.checked : true }, plan.label);
  } catch (e) {
    statusEl.textContent = e.message;
  }
}

function fmtShortDate(iso) {
  return new Date(iso + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

async function loadCalendarNote() {
  const el = document.getElementById("calendar-note");
  if (!el) return;
  try {
    const data = await (await fetch("/api/academic-calendar")).json();
    const cal = data.calendar || {};
    if (cal.start && cal.end) {
      const brk = (cal.breaks || []).filter((b) => b.start <= cal.end && (b.end || b.start) >= cal.start).length;
      el.innerHTML = `Calendar export repeats each class weekly from <strong>${fmtShortDate(cal.start)}</strong> to <strong>${fmtShortDate(cal.end)}</strong>` +
        `${cal.term ? ` (${escapeHtml(cal.term)})` : ""}${brk ? `, skipping ${brk} break${brk === 1 ? "" : "s"}` : ""}. ` +
        `To import in Google Calendar: Settings → Import &amp; export.`;
    } else {
      el.innerHTML = `No academic calendar set yet, so exported classes repeat for 15 weeks from the next class day. ` +
        `${data.can_edit ? 'Set the term dates on the <a href="/import">Import page</a>.' : "The admin can set the term dates on the Import page."}`;
    }
  } catch (e) { el.textContent = ""; }
}

document.getElementById("export-pdf-btn").addEventListener("click", printActivePlan);
document.getElementById("export-ics-btn").addEventListener("click", downloadActivePlan);
document.getElementById("export-dates-btn").addEventListener("click", async () => {
  const statusEl = document.getElementById("export-status");
  statusEl.textContent = "Preparing download…";
  try { statusEl.textContent = await downloadPlanIcs({ dates_only: true, sections: [] }, "academic_dates"); }
  catch (e) { statusEl.textContent = e.message; }
});
document.getElementById("pin-btn").addEventListener("click", togglePin);
document.getElementById("view-week").addEventListener("click", () => setView("week"));
document.getElementById("view-list").addEventListener("click", () => setView("list"));
document.getElementById("active-btn").addEventListener("click", toggleActive);

document.addEventListener("advisor:changed", async () => {
  await loadPreferences();
  await loadWishlistPanel();
  await loadPlans();
});

loadCalendarNote();
loadPreferences();
loadWishlistPanel();
loadPlans();
