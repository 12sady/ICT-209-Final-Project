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
      const label = G.non_gpa[g] ? `${g} (${G.non_gpa[g]})` : `${g} · ${Number(G.scale[g]).toFixed(1)}`;
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

function renderSemesters() {
  const rows = G.semesters.map((r) =>
    `<tr><td>${escapeHtml(r.semester)}</td><td class="num">${fmtGpa(r.gpa)}</td>` +
    `<td class="num">${fmtNum(r.gpa_credits)}</td><td class="num">${fmtNum(r.attempted)} / ${fmtNum(r.earned)}</td>` +
    `<td class="num">${fmtGpa(r.cumulative_gpa)}</td></tr>`).join("");
  const onlyUnassigned = G.semesters.length === 1 && G.semesters[0].semester === "No semester picked";
  $("semester-note").hidden = !onlyUnassigned;
  $("semester-table").innerHTML =
    `<thead><tr><th>Semester</th><th class="num">GPA</th><th class="num">GPA credits</th><th class="num">Attempted / earned</th><th class="num">Cumulative after</th></tr></thead><tbody>${rows}</tbody>`;
}

function renderGrades() {
  const bySem = {};
  G.entries.forEach((e) => { (bySem[e.semester || ""] = bySem[e.semester || ""] || []).push(e); });
  const order = G.semesters.map((r) => (r.semester === "No semester picked" ? "" : r.semester));
  $("grades-by-semester").innerHTML = order.filter((s) => bySem[s]).map((sem) => {
    const rows = bySem[sem].sort((a, b) => a.code.localeCompare(b.code)).map((e) =>
      `<tr data-code="${escapeHtml(e.code)}"><td class="code-cell">${escapeHtml(e.code)}</td>` +
      `<td class="wrap">${escapeHtml(e.name)}</td><td class="num">${fmtNum(e.credits)}</td><td>${gradeSelect(e.grade, "grade-select")}</td></tr>`).join("");
    return `<h3 class="group-title">${sem ? escapeHtml(sem) : "No semester picked yet"}</h3>` +
      `<div class="table-wrap"><table class="course-table"><thead><tr><th>Code</th><th>Course</th><th class="num">Credits</th><th>Grade</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }).join("");
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
  $("scale-box").innerHTML = Object.entries(G.scale).map(([g, p]) => `<span><strong>${g}</strong> ${Number(p).toFixed(1)}</span>`).join("") +
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

["target-gpa", "target-credits"].forEach((id) => $(id).addEventListener("input", () => {
  clearTimeout(whatifTimer); whatifTimer = setTimeout(runTarget, 200);
}));
init();
