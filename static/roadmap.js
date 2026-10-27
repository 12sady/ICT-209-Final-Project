// Graduation roadmap page. The server (roadmap.py) does all planning and
// validation; this file shows it and sends moves.

const $ = (id) => document.getElementById(id);
const cr = (x) => (Math.round(Number(x) * 10) / 10).toString();
let R = null;
let dragId = null;

function startChoices(current) {
  const y = new Date().getFullYear(), list = [];
  for (let yr = y - 1; yr <= y + 3; yr++) ["Spring", "Summer", "Fall"].forEach((s) => list.push(`${s} ${yr}`));
  if (current && !list.includes(current)) list.push(current);
  return list;
}

async function api(url, method, body) {
  const res = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Something went wrong.");
  return data;
}

function renderStats() {
  const road = R.roadmap, st = R.settings;
  const grad = road.graduation_term;
  const stat = (label, value, sub) => `<div class="stat"><div class="stat-label">${label}</div><div class="stat-value">${value}</div><div class="stat-sub">${sub}</div></div>`;
  $("rm-stats").innerHTML =
    stat("Estimated graduation", grad ? escapeHtml(grad) : "—", grad ? `${road.terms.length} term${road.terms.length === 1 ? "" : "s"} from ${escapeHtml(road.start_term)}` : "Some courses couldn't be placed") +
    stat("Remaining", `${cr(road.remaining_credits)}<span class="stat-of"> credits</span>`, `${road.remaining_courses} required course${road.remaining_courses === 1 ? "" : "s"} and elective slots`) +
    stat("Completed", String(R.completed_count), `${cr(R.credit_check.completed_credits)} credits in your curriculum`) +
    stat("Credit limit", `${cr(st.max_credits)}<span class="stat-of"> / term</span>`, "Change it below");
}

function renderNotes() {
  const road = R.roadmap;
  $("rm-honesty").innerHTML = road.real_offerings_term
    ? `<strong>${escapeHtml(road.real_offerings_term)} is checked against this term's real course offerings.</strong> Every later term is a <em>projection</em> from your sample plan and prerequisites: AUPP may not offer a course in the term shown here.`
    : `<strong>Every term here is a projection.</strong> Your imported offerings don't match ${escapeHtml(road.start_term)}, so nothing is checked against real sections. Use it to see the order and the pace, then confirm each term when its offerings are published.`;
  $("rm-risks").innerHTML = road.risks.map((r) => `<div class="banner ${r.kind === "unplaced" ? "danger" : "warn"}">${escapeHtml(r.text)}</div>`).join("");
  const c = R.credit_check;
  const bits = [];
  if (c.program_total && Math.abs(c.planned_total - c.program_total) > 0.01) {
    bits.push(`Completed (${cr(c.completed_credits)}) plus remaining (${cr(road.remaining_credits)}) adds up to ${cr(c.planned_total)} credits, but your program lists ${cr(c.program_total)}. That's usually open electives or a data difference; check it with your advisor.`);
  }
  if (c.completed_not_in_curriculum.length) bits.push(`${c.completed_not_in_curriculum.join(", ")} ${c.completed_not_in_curriculum.length === 1 ? "is" : "are"} completed but not in your curriculum list, so ${c.completed_not_in_curriculum.length === 1 ? "its" : "their"} credits aren't counted above.`);
  $("rm-credit-note").textContent = bits.join(" ");
}

function renderSettings() {
  const st = R.settings;
  $("rm-start").innerHTML = startChoices(st.start_term).map((t) => `<option ${t === st.start_term ? "selected" : ""}>${t}</option>`).join("");
  $("rm-max").value = cr(st.max_credits);
  $("rm-summer").checked = st.include_summer;
  $("rm-season").checked = st.same_season;
  $("rm-reset").disabled = !R.overridden;
  $("rm-overridden").textContent = R.overridden ? `${R.overridden} course${R.overridden === 1 ? " is" : "s are"} placed by hand (📌).` : "Everything is placed automatically.";
}

function cardHtml(c, termLabel) {
  const opts = ['<option value="">Move to…</option>'].concat(R.term_options.filter((t) => t !== termLabel).map((t) => `<option>${t}</option>`));
  if (c.fixed) opts.push('<option value="__auto">Back to automatic</option>');
  return `<li class="rm-card ${c.slot ? "rm-slot" : ""} ${c.warnings.length ? "rm-warn" : ""}" draggable="true" data-id="${escapeHtml(c.id)}">
    <div class="rm-card-top"><span class="rm-code">${c.slot ? "Elective slot" : escapeHtml(c.code)}</span><span class="rm-cr">${cr(c.credits)} cr</span></div>
    <div class="rm-name">${c.slot ? (c.name && c.name !== "Elective" ? escapeHtml(c.name) : "Choose any approved elective") : escapeHtml(c.name)}</div>
    <div class="rm-meta">${c.fixed ? '<span title="You placed this course here">📌 placed by you</span>' : ""}${c.plan ? `<span>Sample plan: ${escapeHtml(c.plan)}</span>` : ""}</div>
    ${c.warnings.map((w) => `<div class="rm-w">⚠ ${c.slot ? "" : escapeHtml(c.code) + " "}${escapeHtml(w)}</div>`).join("")}
    <select class="rm-move" aria-label="Move ${escapeHtml(c.code || c.name)} to another term">${opts.join("")}</select>
  </li>`;
}

function renderBoard() {
  const road = R.roadmap, board = $("rm-board");
  board.innerHTML = road.terms.map((t, i) => `
    <section class="rm-term ${t.warnings.length ? "rm-term-warn" : ""}" data-term="${escapeHtml(t.label)}" aria-label="${escapeHtml(t.label)}">
      <header><h3>${escapeHtml(t.label)}${i === 0 && road.real_offerings_term ? ' <span class="rm-badge rm-real">real offerings</span>' : ' <span class="rm-badge">projected</span>'}</h3>
        <div class="rm-total ${t.credits > road.max_credits ? "over" : ""}">${cr(t.credits)} / ${cr(road.max_credits)} credits</div></header>
      ${t.warnings.map((w) => `<div class="rm-w">⚠ ${escapeHtml(w)}</div>`).join("")}
      <ul class="rm-list">${t.courses.map((c) => cardHtml(c, t.label)).join("") || '<li class="rm-empty">Nothing planned</li>'}</ul>
    </section>`).join("") +
    `<section class="rm-term rm-term-new" data-term="${escapeHtml(R.term_options[R.term_options.length - 1])}"><header><h3>${escapeHtml(R.term_options[R.term_options.length - 1])}</h3><div class="rm-total">Drop here to add a later term</div></header><ul class="rm-list"><li class="rm-empty">Drop a course here</li></ul></section>`;

  board.querySelectorAll(".rm-card").forEach((card) => {
    card.addEventListener("dragstart", (e) => { dragId = card.dataset.id; card.classList.add("dragging"); e.dataTransfer.setData("text/plain", dragId); e.dataTransfer.effectAllowed = "move"; });
    card.addEventListener("dragend", () => { card.classList.remove("dragging"); board.querySelectorAll(".rm-over").forEach((x) => x.classList.remove("rm-over")); });
    card.querySelector(".rm-move").addEventListener("change", (e) => {
      const v = e.target.value;
      if (v) move(card.dataset.id, v === "__auto" ? null : v);
    });
  });
  board.querySelectorAll(".rm-term").forEach((col) => {
    col.addEventListener("dragover", (e) => { e.preventDefault(); col.classList.add("rm-over"); });
    col.addEventListener("dragleave", () => col.classList.remove("rm-over"));
    col.addEventListener("drop", (e) => { e.preventDefault(); col.classList.remove("rm-over"); if (dragId) move(dragId, col.dataset.term); dragId = null; });
  });
}

async function move(id, term) {
  const card = R.roadmap.terms.flatMap((t) => t.courses).find((c) => c.id === id);
  const label = card ? (card.code || card.name) : id;
  try {
    R = await api("/api/roadmap/move", "POST", { id, term });
  } catch (e) { $("rm-status").textContent = e.message; return; }
  render();
  const moved = R.roadmap.terms.flatMap((t) => t.courses.map((c) => ({ c, t }))).find((x) => x.c.id === id);
  const w = moved ? moved.c.warnings.length : 0;
  const term_w = moved ? moved.t.warnings.length : 0;
  $("rm-status").textContent = term === null ? `${label} is back on automatic placement.` :
    `Moved ${label} to ${term}.` + (w || term_w ? ` ⚠ ${[...(moved ? moved.c.warnings : []), ...(moved ? moved.t.warnings : [])].join("; ")}` : " No problems found.");
}

function render() {
  const empty = !R.has_curriculum || !R.roadmap.terms.length && !R.roadmap.unplaced.length;
  $("rm-empty").hidden = !empty;
  $("rm-main").hidden = empty;
  if (empty) {
    if (!R.has_curriculum) {
      $("rm-empty-title").textContent = "No curriculum yet, so there's nothing to plan.";
      $("rm-empty-body").innerHTML = `Choose your major's sample plan on the <a href="/curriculum">Curriculum</a> page first. The roadmap is built from it.`;
    } else {
      $("rm-empty-title").textContent = "Every required course is marked completed.";
      $("rm-empty-body").innerHTML = `Nothing is left to schedule. If that's not right, check the <a href="/curriculum">Curriculum</a> page.`;
    }
    return;
  }
  renderStats(); renderNotes(); renderSettings(); renderBoard();
}

async function saveSettings() {
  try {
    R = await api("/api/roadmap/settings", "PUT", {
      start_term: $("rm-start").value, max_credits: $("rm-max").value,
      include_summer: $("rm-summer").checked, same_season: $("rm-season").checked,
    });
    $("rm-status").textContent = "Roadmap updated.";
  } catch (e) { $("rm-status").textContent = e.message; }
  render();
}

["rm-start", "rm-summer", "rm-season"].forEach((id) => $(id).addEventListener("change", saveSettings));
$("rm-max").addEventListener("change", saveSettings);
$("rm-reset").addEventListener("click", async () => { R = await api("/api/roadmap/reset", "POST"); $("rm-status").textContent = "Back to the automatic plan."; render(); });

(async () => { R = await (await fetch("/api/roadmap")).json(); render(); })();
