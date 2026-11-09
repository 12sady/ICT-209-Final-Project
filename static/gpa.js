// Grade points as AUPP writes them: 4.0, 3.67, 3.33 (not rounded to 3.7 / 3.3).
function pts(p) {
  const n = Number(p);
  return Number.isInteger(n) ? n.toFixed(1) : String(Math.round(n * 100) / 100);
}

// GPA page: grade entry (autosaves), per-semester GPA, and two what-if tools.
// All GPA arithmetic happens on the server (gpa.py); this file only displays it.

let G = null;            // last /api/gpa response
let whatifTimer = null;

const $ = (id) => document.getElementById(id);
const fmtGpa = (x) => (x == null ? "—" : Number(x).toFixed(2));
const fmtNum = (x) => (Math.round(Number(x) * 100) / 100).toString();

function gradeSelect(current, extraClass) {
  const opts = ['<option value="">— no grade —</option>']
    .concat(G.grade_options.map((g) => {
      const label = G.non_gpa[g] ? `${g} (${G.non_gpa[g]})` : `${g} · ${pts(G.scale[g])}`;
      return `<option value="${g}" ${g === current ? "selected" : ""}>${label}</option>`;
    }));
  return `<select class="${extraClass || ""}" aria-label="Grade">${opts.join("")}</select>`;
}

function renderStats() {
  const s = G.summary;
  const stat = (label, value, sub) =>
    `<div class="stat"><div class="stat-label">${label}</div><div class="stat-value">${value}</div><div class="stat-sub">${sub || ""}</div></div>`;
  const graded = G.entries.filter((e) => e.grade).length;
  $("gpa-stats").innerHTML =
    stat("Cumulative GPA", fmtGpa(s.gpa), s.gpa == null ? "Enter a grade to start" : `${fmtNum(s.quality_points)} quality points ÷ ${fmtNum(s.gpa_credits)} credits`) +
    stat("Credits attempted", fmtNum(s.attempted), "Graded and pass/fail courses") +
    stat("Credits earned", fmtNum(s.earned), "Passed (D or better, or P)") +
    stat("Courses graded", `${graded}<span class="stat-of"> / ${G.entries.length}</span>`,
         G.ungraded.length ? `${G.ungraded.length} still need a grade` : "All entered");
}

// Which semester groups are open (by name). The newest one starts open.
let openSems = null;

function semesterRow(sem) {
  return G.semesters.find((r) => (r.semester === "No semester picked" ? "" : r.semester) === sem) || {};
}

// "15 cr · Term GPA 3.67 · Cumulative 3.52" on each semester's row.
function semesterMeta(sem) {
  const r = semesterRow(sem);
  const credits = G.entries.filter((e) => (e.semester || "") === sem).reduce((a, e) => a + Number(e.credits || 0), 0);
  const parts = [`${fmtNum(credits)} cr`, `Term GPA <strong>${fmtGpa(r.gpa)}</strong>`];
  if (sem) parts.push(`Cumulative <strong>${fmtGpa(r.cumulative_gpa)}</strong>`);
  return parts.join(" · ");
}

function renderSemesters() {
  // The semester table was merged into the group rows: just refresh their numbers.
  const onlyUnassigned = G.semesters.length === 1 && G.semesters[0].semester === "No semester picked";
  $("semester-note").hidden = !onlyUnassigned;
  document.querySelectorAll(".gpa-group").forEach((g) => {
    g.querySelector(".group-credits").innerHTML = semesterMeta(g.dataset.sem);
  });
}

function setGroupOpen(section, open) {
  const sem = section.dataset.sem;
  if (open) openSems.add(sem); else openSems.delete(sem);
  const btn = section.querySelector(".group-toggle");
  btn.setAttribute("aria-expanded", String(open));
  btn.querySelector(".group-icon").textContent = open ? "−" : "+";
  section.querySelector(".group-body").hidden = !open;
}

function renderGrades() {
  const bySem = {};
  G.entries.forEach((e) => { (bySem[e.semester || ""] = bySem[e.semester || ""] || []).push(e); });
  const order = G.semesters.map((r) => (r.semester === "No semester picked" ? "" : r.semester));
  const sems = order.filter((s) => bySem[s]);
  if (openSems === null) {
    const dated = sems.filter((s) => s);
    openSems = new Set(dated.length ? [dated[dated.length - 1]] : sems.slice(-1));
  }
  $("grades-by-semester").innerHTML = sems.map((sem) => {
    const list = bySem[sem];
    const rows = list.sort((a, b) => a.code.localeCompare(b.code)).map((e) =>
      `<tr data-code="${escapeHtml(e.code)}"><td class="code-cell">${escapeHtml(e.code)}</td>` +
      `<td class="wrap">${escapeHtml(e.name)}</td><td class="num">${fmtNum(e.credits)}</td><td>${gradeSelect(e.grade, "grade-select")}</td></tr>`).join("");
    const open = openSems.has(sem);
    const missing = list.filter((e) => !e.grade).length;
    return `<div class="curriculum-group gpa-group" data-sem="${escapeHtml(sem)}">
      <button type="button" class="group-toggle" aria-expanded="${open}">
        <span class="group-icon" aria-hidden="true">${open ? "−" : "+"}</span>
        <span class="group-name">${sem ? escapeHtml(sem) : "No semester picked yet"}</span>
        <span class="curriculum-group-count">${list.length}</span>
        ${missing ? `<span class="status-badge status-warn">${missing} without a grade</span>` : ""}
        <span class="group-credits">${semesterMeta(sem)}</span>
      </button>
      <div class="group-body" ${open ? "" : "hidden"}>
        <div class="table-wrap"><table class="course-table"><thead><tr><th>Code</th><th>Course</th><th class="num">Credits</th><th>Grade</th></tr></thead><tbody>${rows}</tbody></table></div>
      </div></div>`;
  }).join("");
  document.querySelectorAll(".gpa-group").forEach((section) => {
    section.querySelector(".group-toggle").addEventListener("click", () => setGroupOpen(section, !openSems.has(section.dataset.sem)));
  });
  document.querySelectorAll(".grade-select").forEach((sel) => {
    sel.addEventListener("change", () => saveGrade(sel.closest("tr").dataset.code, sel.value));
  });
  const unk = G.unknown_credits || [];
  $("unknown-note").hidden = !unk.length;
  if (unk.length) {
    $("unknown-note").textContent = `${unk.join(", ")} ${unk.length === 1 ? "is" : "are"} marked completed but ${unk.length === 1 ? "isn't" : "aren't"} in your curriculum list, so ${unk.length === 1 ? "its" : "their"} credits are unknown and left out. Add ${unk.length === 1 ? "it" : "them"} on the Curriculum page to include ${unk.length === 1 ? "it" : "them"}.`;
  }
}

async function saveGrade(code, value) {
  const status = $("grade-status");
  status.textContent = "Saving…";
  const res = await fetch("/api/grades", {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ grades: { [code]: value } }),
  });
  const data = await res.json();
  if (!res.ok) { status.textContent = data.error || "Couldn't save that grade."; return; }
  const e = G.entries.find((x) => x.code === code);
  if (e) e.grade = value;
  G.summary = data.summary; G.semesters = data.semesters; G.ungraded = data.ungraded;
  status.textContent = `Saved ${code}.`;
  renderStats(); renderSemesters(); runWhatIf(); runTarget();
}

function renderPlanned() {
  const box = $("whatif-planned");
  if (!G.planned.length) {
    box.innerHTML = `<p class="hint">You have no plan yet. Add courses on <a href="/browse">Browse &amp; Wishlist</a> and they'll show up here so you can try grades.</p>`;
    $("whatif-result").innerHTML = "";
    return;
  }
  box.innerHTML = `<div class="table-wrap"><table class="course-table"><tbody>` + G.planned.map((c) =>
    `<tr data-code="${escapeHtml(c.code)}"><td class="code-cell">${escapeHtml(c.code)}</td><td class="wrap">${escapeHtml(c.name)}</td>` +
    `<td class="num">${fmtNum(c.credits)} cr</td><td>${gradeSelect("", "planned-grade")}</td></tr>`).join("") + `</tbody></table></div>`;
  box.querySelectorAll(".planned-grade").forEach((s) => s.addEventListener("change", runWhatIf));
  runWhatIf();
}

async function runWhatIf() {
  const rows = [...document.querySelectorAll("#whatif-planned tr")];
  const out = $("whatif-result");
  if (!rows.length) return;
  const grades = {};
  rows.forEach((tr) => { const v = tr.querySelector("select").value; if (v) grades[tr.dataset.code] = v; });
  if (!Object.keys(grades).length) {
    out.innerHTML = `<p class="hint">Pick a grade for at least one course to see your new GPA.</p>`;
    return;
  }
  const data = await (await fetch("/api/gpa/whatif", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ grades }),
  })).json();
  const w = data.whatif;
  if (w.new_gpa == null) { out.innerHTML = `<p class="hint">None of those grades count toward GPA (pass/fail and withdrawals are excluded).</p>`; return; }
  const diff = w.change == null ? "" : ` (${w.change >= 0 ? "+" : ""}${w.change.toFixed(2)} from ${fmtGpa(w.current_gpa)})`;
  out.innerHTML = `<div class="math-big">${fmtGpa(w.new_gpa)}<span class="math-diff">${diff}</span></div>
    <div class="math-line">(${fmtNum(w.current_quality_points)} + ${fmtNum(w.added_quality_points)}) ÷ (${fmtNum(w.current_credits)} + ${fmtNum(w.added_credits)}) = ${fmtNum(w.new_quality_points)} ÷ ${fmtNum(w.new_credits)}</div>
    <div class="hint">quality points = grade points × credits</div>`;
}

async function runTarget() {
  const out = $("target-result");
  const target = $("target-gpa").value, credits = $("target-credits").value;
  if (target === "") { out.innerHTML = ""; return; }
  const data = await (await fetch("/api/gpa/whatif", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target, credits }),
  })).json();
  const t = data.target;
  if (t.needed == null) { out.innerHTML = `<p class="hint">${escapeHtml(t.message)}</p>`; return; }
  out.innerHTML = `<div class="math-big ${t.feasible ? "" : "math-bad"}">${t.feasible ? t.needed.toFixed(2) : "Not reachable"}</div>
    <p class="math-msg">${escapeHtml(t.message)}</p>
    <div class="math-line">needed = (${fmtNum(t.target)} × ${fmtNum(t.total_credits)} − ${fmtNum(t.current_quality_points)}) ÷ ${fmtNum(t.term_credits)} = ${fmtNum(t.needed_quality_points)} ÷ ${fmtNum(t.term_credits)}</div>
    <div class="hint">Best possible after this term: ${t.best_possible_gpa.toFixed(2)}</div>`;
}

function renderScale() {
  $("scale-box").innerHTML = Object.entries(G.scale).map(([g, p]) => `<span><strong>${g}</strong> ${pts(p)}</span>`).join("") +
    Object.entries(G.non_gpa).map(([g, n]) => `<span class="muted"><strong>${g}</strong> ${n} (not in GPA)</span>`).join("");
}

async function init() {
  G = await (await fetch("/api/gpa")).json();
  const empty = $("gpa-empty"), main = $("gpa-main");
  if (!G.entries.length) {
    empty.hidden = false; main.hidden = true;
    if (!G.has_curriculum) {
      $("gpa-empty-title").textContent = "No curriculum yet, so there are no completed courses to grade.";
      $("gpa-empty-body").innerHTML = `Start on the <a href="/curriculum">Curriculum</a> page: choose your major's sample plan and mark what you've completed.`;
    } else {
      $("gpa-empty-title").textContent = "No completed courses yet.";
      $("gpa-empty-body").innerHTML = `On the <a href="/curriculum">Curriculum</a> page, set each course you've finished to "Completed". They'll appear here so you can enter grades.`;
    }
    return;
  }
  empty.hidden = true; main.hidden = false;
  if (G.entries.every((e) => !e.grade)) {
    $("grades-hint").textContent = "No grades entered yet. Pick a grade next to each course below — it saves as you go and your GPA appears at the top. Pass/fail, withdrawn, incomplete and audit grades are kept out of the GPA.";
  }
  const planned = G.planned.reduce((a, c) => a + Number(c.credits || 0), 0);
  $("target-credits").value = planned || Math.min(15, G.max_credits);
  renderStats(); renderGrades(); renderSemesters(); renderPlanned(); renderScale(); runTarget();
}

$("open-all").addEventListener("click", () => document.querySelectorAll(".gpa-group").forEach((s) => setGroupOpen(s, true)));
$("close-all").addEventListener("click", () => document.querySelectorAll(".gpa-group").forEach((s) => setGroupOpen(s, false)));

["target-gpa", "target-credits"].forEach((id) => $(id).addEventListener("input", () => {
  clearTimeout(whatifTimer); whatifTimer = setTimeout(runTarget, 200);
}));
init();
