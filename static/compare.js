// Compare page: pinned plans in columns, best value per row highlighted.
// Metrics and "best" are computed on the server (compare.py).

const $ = (id) => document.getElementById(id);
const hm = (m) => (m == null ? "—" : `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`);
const dur = (m) => (!m ? "None" : m >= 60 ? `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}` : `${m} min`);
const RISK_LABEL = { low: "Low", medium: "Medium", "fills fast": "Fills fast", full: "Full" };

let D = null;
let shown = 0; // phone layout: which plan column is visible

const ROWS = [
  ["total_credits", "Total credits", (m) => `${m.total_credits % 1 ? m.total_credits.toFixed(1) : m.total_credits} credits`],
  ["courses", "Courses", (m) => String(m.courses)],
  ["days_on_campus", "Days on campus", (m) => (m.days_on_campus ? `${m.days_on_campus} · ${m.days.join(" ")}` : "None")],
  ["earliest_start", "Earliest start", (m) => hm(m.earliest_start)],
  ["latest_end", "Latest end", (m) => hm(m.latest_end)],
  ["longest_gap", "Longest gap", (m) => dur(m.longest_gap)],
  ["total_wait", "Total waiting", (m) => dur(m.total_wait)],
  ["left_out", "Wishlist left out", (m) => (m.left_out.length ? `${m.left_out.length}: ${escapeHtml(m.left_out.join(", "))}` : "None")],
  ["worst_risk", "Seat risk", seatCell],
];

function seatCell(m) {
  if (!m.has_seat_data) {
    const hot = m.seat_risk.filter((s) => s.demand === "high" || s.demand === "popular");
    return `<span class="hint-inline">No seat numbers imported</span>` +
      (hot.length ? `<br><span class="risk-badge risk-medium">${hot.length} in demand</span> <span class="hint-inline">${escapeHtml(hot.map((s) => s.code).join(", "))}</span>` : "");
  }
  const bad = m.seat_risk.filter((s) => s.risk !== "low" && s.risk !== "unknown");
  const head = `<span class="risk-badge risk-${m.worst_risk.replace(" ", "-")}">${RISK_LABEL[m.worst_risk]}</span>`;
  return head + (bad.length ? `<div class="hint-inline">${bad.map((s) => `${escapeHtml(s.code)}-${escapeHtml(s.section)}${s.seats ? ` (${s.seats} left)` : ""}`).join(", ")}</div>` : "");
}

function render() {
  const plans = D.plans;
  const empty = $("compare-empty"), main = $("compare-main");
  if (!plans.length) {
    empty.hidden = false; main.hidden = true;
    $("compare-empty-title").textContent = "No plans pinned yet.";
    $("compare-empty-body").innerHTML = `On the <a href="/plan">Plan</a> page, choose a schedule and press “Pin to compare”. Pin two or three, then come back here.`;
    return;
  }
  empty.hidden = true; main.hidden = false;
  const winners = (key) => (D.best[key] ? D.best[key].winners : []);

  let html = `<thead><tr><th class="row-label"></th>` + plans.map((p, i) => `
    <th class="plan-col" data-col="${i}"><div class="plan-name">Plan ${p.name}${p.is_active ? ` <span class="active-badge">Active</span>` : ""}</div>
      <div class="plan-actions">
        <button class="${p.is_active ? "" : "secondary"} act-use" data-id="${p.id}" ${p.is_active ? "disabled" : ""}>${p.is_active ? "Your active plan" : "Use as my active plan"}</button>
        <button class="secondary act-ics" data-id="${p.id}">Add to calendar (.ics)</button>
        <button class="linkish act-remove" data-id="${p.id}">Remove</button>
      </div></th>`).join("") + `</tr></thead><tbody>`;

  ROWS.forEach(([key, label, fmt]) => {
    if (key === "worst_risk" && !plans.some((p) => p.metrics.has_seat_data) && !plans.some((p) => p.metrics.seat_risk.some((s) => s.demand === "high" || s.demand === "popular"))) {
      html += `<tr><th class="row-label">${label}<span class="row-why">No seat or demand data to compare yet</span></th>` +
        plans.map((p, i) => `<td data-col="${i}"><span class="hint-inline">No seat numbers imported</span></td>`).join("") + `</tr>`;
      return;
    }
    const win = winners(key);
    const b = D.best[key];
    const why = b && b.winners.length ? `<span class="row-why">Best: ${escapeHtml(b.reason)}</span>`
      : b ? `<span class="row-why row-why-diff">Different courses</span>`
      : (plans.length > 1 ? `<span class="row-why">No difference</span>` : "");
    html += `<tr><th class="row-label">${label}${why}</th>` + plans.map((p, i) =>
      `<td data-col="${i}" class="${win.includes(i) ? "best" : ""}">${win.includes(i) ? `<span class="best-mark" title="${escapeHtml(D.best[key].reason)}">★ Best</span>` : ""}${fmt(p.metrics)}</td>`).join("") + `</tr>`;
  });

  html += `<tr class="tt-row"><th class="row-label">Week at a glance</th>` + plans.map((p, i) => `<td data-col="${i}">${timetableHtml(p.sections, { compact: true, legend: true })}</td>`).join("") + `</tr>`;
  html += `<tr><th class="row-label">Sections</th>` + plans.map((p, i) => `<td data-col="${i}" class="sec-list">` +
    p.sections.map((s) => `<div><strong>${escapeHtml(s.code)}-${escapeHtml(s.section)}</strong> <span class="hint-inline">${escapeHtml(s.title || "")}</span><br>` +
      `<span class="hint-inline">${s.online || !s.start ? "Online / no fixed time" : `${(s.days || []).join(" ")} ${escapeHtml(s.start)}–${escapeHtml(s.end)}`}${s.location ? " · " + escapeHtml(s.location) : ""}</span></div>`).join("") +
    (p.missing.length ? `<div class="banner danger">No longer offered: ${escapeHtml(p.missing.join(", "))}</div>` : "") + `</td>`).join("") + `</tr></tbody>`;
  $("compare-table").innerHTML = html;
  const tabs = $("compare-tabs");
  tabs.innerHTML = plans.map((p, i) => `<button type="button" role="tab" data-i="${i}" aria-selected="${i === shown}">Plan ${p.name}${p.is_active ? " ★" : ""}</button>`).join("");
  tabs.hidden = plans.length < 2;
  $("compare-table").dataset.show = String(Math.min(shown, plans.length - 1));
  tabs.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { shown = Number(b.dataset.i); render(); }));
  $("compare-table").style.setProperty("--plans", plans.length);

  $("compare-note").textContent = plans.length < 2
    ? "Pin at least one more plan on the Plan page to see which is best at what."
    : `Limits used: ${D.min_credits}–${D.max_credits} credits per term (change them on the Curriculum page). ★ marks the best value in a row; rows where all plans tie have no star.`;

  document.querySelectorAll(".act-use").forEach((b) => b.addEventListener("click", () => useAsActive(b.dataset.id)));
  document.querySelectorAll(".act-ics").forEach((b) => b.addEventListener("click", () => exportPlan(b.dataset.id)));
  document.querySelectorAll(".act-remove").forEach((b) => b.addEventListener("click", () => removePin(b.dataset.id)));
}

const keysOf = (p) => p.sections.map((s) => ({ code: s.code, section: s.section }));

async function useAsActive(id) {
  const p = D.plans.find((x) => x.id === id);
  const res = await fetch("/api/plan/active", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sections: keysOf(p) }) });
  const data = await res.json();
  $("compare-status").textContent = res.ok ? `Plan ${p.name} is now your active plan. The Plan page and GPA what-if use it.` : (data.error || "Couldn't set the active plan.");
  if (res.ok) await load(true);
}

async function exportPlan(id) {
  const p = D.plans.find((x) => x.id === id);
  $("compare-status").textContent = "Preparing download…";
  try {
    $("compare-status").textContent = `Plan ${p.name}: ` + await downloadPlanIcs({ sections: p.sections }, `plan_${p.name}`);
  } catch (e) { $("compare-status").textContent = e.message; }
}

async function removePin(id) {
  await fetch(`/api/plan/pins/${encodeURIComponent(id)}`, { method: "DELETE" });
  await load();
}

async function load(keepStatus) {
  D = await (await fetch("/api/plan/compare")).json();
  if (!keepStatus) $("compare-status").textContent = "";
  render();
}
load();
