// Advisor summary page: renders /api/advisor-summary; Print uses the browser's print dialog (Save as PDF).
const $ = (id) => document.getElementById(id);
const cr = (x) => (Math.round(Number(x) * 10) / 10).toString();
const g2 = (x) => (x == null ? "—" : Number(x).toFixed(2));

function render(d) {
  if (!d.has_curriculum) { $("adv-empty").hidden = false; return; }
  $("adv-doc").hidden = false; $("adv-print").hidden = false;
  $("adv-sub").textContent = [d.student, d.program, d.term, `prepared ${d.generated}`].filter(Boolean).join(" · ");
  const road = d.roadmap, p = d.progress;
  $("adv-grad").innerHTML = road.graduation_term ? `Estimated graduation<br><strong>${escapeHtml(road.graduation_term)}</strong>` : `Estimated graduation<br><strong>—</strong>`;

  const fig = (label, value, sub) => `<div class="adv-fig"><div class="adv-fig-label">${label}</div><div class="adv-fig-value">${value}</div><div class="adv-fig-sub">${sub}</div></div>`;
  $("adv-figures").innerHTML =
    fig("Credits completed", `${cr(p.done)} <span>/ ${cr(p.total)}</span>`, `${p.percent}% of the plan · ${cr(p.remaining)} left`) +
    fig("Cumulative GPA", g2(d.gpa.value), `${d.gpa.graded} of ${d.gpa.completed} courses graded`) +
    fig("Required courses left", String(d.remaining_required), d.bottlenecks.length ? `Key prerequisites: ${escapeHtml(d.bottlenecks.slice(0, 3).map((b) => b.code).join(", "))}` : "No long prerequisite chains") +
    fig("Credits earned", cr(d.gpa.earned), `${cr(d.gpa.attempted)} attempted`);

  $("adv-cats").innerHTML = p.rows.map((r) => {
    const pct = r.total ? Math.round((100 * r.done) / r.total) : 0;
    return `<div class="adv-bar"><span class="adv-bar-label">${escapeHtml(r.category)}</span><span class="adv-bar-track"><span style="width:${pct}%"></span></span><span class="adv-bar-num">${cr(r.done)} / ${cr(r.total)} cr</span></div>`;
  }).join("");

  const sem = d.gpa.semesters;
  $("adv-gpa").innerHTML = sem.length
    ? `<thead><tr><th>Semester</th><th class="num">Credits</th><th class="num">GPA</th><th class="num">Cumulative</th></tr></thead><tbody>` +
      sem.map((r) => `<tr><td>${escapeHtml(r.semester)}</td><td class="num">${cr(r.credits)}</td><td class="num">${g2(r.gpa)}</td><td class="num">${g2(r.cumulative_gpa)}</td></tr>`).join("") + `</tbody>`
    : `<tbody><tr><td class="sub">No grades entered yet.</td></tr></tbody>`;
  $("adv-gpa-note").textContent = d.gpa.completed > d.gpa.graded ? `${d.gpa.completed - d.gpa.graded} completed course(s) have no grade entered and are left out of the GPA.` : "";

  $("adv-risks").innerHTML = road.risks.length ? `<ul class="adv-risks">${road.risks.map((t) => `<li>${escapeHtml(t)}</li>`).join("")}</ul>` : "";
  $("adv-roadmap").innerHTML = road.terms.length
    ? `<thead><tr><th>Term</th><th class="num">Credits</th><th>Planned courses</th></tr></thead><tbody>` +
      road.terms.map((t) => `<tr><td class="nw"><strong>${escapeHtml(t.label)}</strong></td><td class="num">${cr(t.credits)}</td><td>${escapeHtml(t.courses.join("; "))}</td></tr>`).join("") + `</tbody>`
    : `<tbody><tr><td class="sub">All required courses are completed.</td></tr></tbody>`;
  $("adv-road-note").textContent = road.real_offerings_term
    ? `${road.real_offerings_term} is checked against real offerings; later terms are projections (credit limit ${cr(road.max_credits)} per term).`
    : `Every term is a projection from the sample plan and prerequisites (credit limit ${cr(road.max_credits)} per term).`;

  $("adv-plan-credits").textContent = d.plan ? `${cr(d.plan_credits)} credits` : "";
  $("adv-plan").innerHTML = d.plan
    ? `<thead><tr><th>Course</th><th>Sec</th><th>When</th><th>Room</th><th class="num">Cr</th></tr></thead><tbody>` +
      d.plan.map((r) => `<tr><td><strong>${escapeHtml(r.code)}</strong> ${escapeHtml(r.title)}</td><td class="nw">${escapeHtml(r.section)}</td><td class="nw">${escapeHtml(r.when)}</td><td>${escapeHtml(r.room || "—")}</td><td class="num">${escapeHtml(r.credits ?? "")}</td></tr>`).join("") + `</tbody>`
    : `<tbody><tr><td class="sub">No active plan chosen yet (choose one on the Plan page).</td></tr></tbody>`;
}

$("adv-print").addEventListener("click", () => downloadServerPdf("/api/advisor-summary/pdf", "advisor_summary.pdf", $("adv-pdf-status")));
(async () => { render(await (await fetch("/api/advisor-summary")).json()); })();
