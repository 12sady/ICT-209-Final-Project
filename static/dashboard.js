// Dashboard: everything comes from one call (/api/dashboard); numbers are computed on the server.
const $ = (id) => document.getElementById(id);
const cr = (x) => (Math.round(Number(x) * 10) / 10).toString();

function ringSvg(pct) {
  const r = 52, c = 2 * Math.PI * r, off = c * (1 - Math.min(100, Math.max(0, pct)) / 100);
  return `<svg viewBox="0 0 120 120" width="132" height="132" role="img" aria-label="${pct}% of degree credits completed">
    <circle cx="60" cy="60" r="${r}" fill="none" stroke="var(--border)" stroke-width="12"/>
    <circle cx="60" cy="60" r="${r}" fill="none" stroke="var(--accent)" stroke-width="12" stroke-linecap="round"
      stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}" transform="rotate(-90 60 60)"/>
    <text x="60" y="66" text-anchor="middle" font-size="24" font-weight="700" fill="var(--text)">${Math.round(pct)}%</text></svg>`;
}

function setupSteps(d) {
  return [
    [d.has_curriculum, "Choose your program's sample plan", "/curriculum", "Curriculum", "Loads your courses and prerequisites."],
    [d.completed_count > 0, "Mark the courses you've already completed", "/curriculum", "Curriculum", "So the app knows what's left."],
    [d.offerings_count > 0, "Check this term's courses are loaded", "/import", "Import", "The admin account imports the registrar's sheet."],
    [d.wishlist_count > 0, "Add courses you want to take", "/browse", "Browse & Wishlist", "Your schedule is built from your wishlist."],
  ];
}

function renderSetup(d) {
  const steps = setupSteps(d);
  $("dash-steps").innerHTML = steps.map(([done, text, href, label, sub]) =>
    `<li class="${done ? "done" : ""}"><span class="check" aria-hidden="true">${done ? "✓" : ""}</span><div><strong>${text}</strong>${done ? ' <span class="status-badge status-ok">Done</span>' : ""}<div class="hint">${sub} <a href="${href}">${label}</a></div></div></li>`).join("");
}

function renderMain(d) {
  const p = d.progress;
  $("dash-ring").innerHTML = ringSvg(p.percent);
  $("dash-credits").innerHTML = `${cr(p.done)} <span class="stat-of">of ${cr(p.total)} credits</span>`;
  $("dash-credits-sub").textContent = `${cr(p.remaining)} credits left · ${d.remaining_required} required course${d.remaining_required === 1 ? "" : "s"} to go`;
  if (d.structure) {
    const nc = (p.not_counted || []).map((g) => `${g.group.replace(/ \(not counted\)$/, "")}: ${g.courses.join(", ")}`);
    const extra = p.extra_credits ? [`${cr(p.extra_credits)} cr above a category's requirement`] : [];
    $("dash-extra").textContent = [...extra, ...nc].length ? `Not counted toward ${cr(p.total)}: ${[...extra, ...nc].join(" · ")}.` : "";
  } else {
    $("dash-extra").textContent = p.extra_electives ? `${p.extra_electives} extra elective${p.extra_electives === 1 ? "" : "s"} completed beyond the plan's slots (not counted).` : "";
  }

  const g = d.graduation;
  const tile = (label, value, sub, href) => `<a class="stat stat-link" href="${href}"><div class="stat-label">${label}</div><div class="stat-value">${value}</div><div class="stat-sub">${sub}</div></a>`;
  $("dash-stats").innerHTML =
    tile("Estimated graduation", g.term ? escapeHtml(g.term) : "—", g.term ? `${g.terms} term${g.terms === 1 ? "" : "s"} to go · ${g.real_offerings_term ? "first term from real offerings, rest projected" : "projected"}` : (g.remaining_courses ? "Some courses can't be placed" : "All required courses done"), "/roadmap") +
    tile("Current GPA", d.gpa.value == null ? "—" : d.gpa.value.toFixed(2), d.gpa.value == null ? (d.gpa.completed ? "Enter your grades" : "No completed courses yet") : `${d.gpa.graded} of ${d.gpa.completed} courses graded`, "/gpa") +
    tile("This term's plan", `${cr(d.planned.credits)}<span class="stat-of"> cr</span>`, d.planned.courses ? `${d.planned.courses} courses · ${d.planned.source === "active" ? "your active plan" : "best-ranked plan"} (limit ${d.max_credits})` : "No plan yet — add wishlist courses", "/plan");

  $("dash-risks").innerHTML = g.risks.map((t) => `<div class="banner warn">${escapeHtml(t)}</div>`).join("");

  $("dash-cats").innerHTML = p.rows.map((r) => {
    const pct = r.total ? Math.round((100 * r.done) / r.total) : 0;
    return `<div class="bar-row"><div class="bar-label"><span>${escapeHtml(r.category)}</span><span class="num-inline">${cr(r.done)} / ${cr(r.total)} cr${r.extra ? ` (+${cr(r.extra)} extra)` : ""}</span></div>
      <div class="bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100" aria-label="${escapeHtml(r.category)}"><span style="width:${pct}%"></span></div></div>`;
  }).join("");

  $("dash-available").innerHTML = d.available.length
    ? `<ul class="plain-list">` + d.available.slice(0, 10).map((c) =>
      `<li><span><strong>${escapeHtml(c.code)}</strong> ${escapeHtml(c.name)} <span class="hint-inline">${cr(c.credits)} cr${c.plan ? " · " + escapeHtml(c.plan) : ""}</span></span>` +
      (c.offered === true ? '<span class="status-badge status-ok">Offered now</span>' : c.offered === false ? '<span class="status-badge status-muted">Not offered this term</span>' : "") + `</li>`).join("") +
      `</ul>` + (d.available.length > 10 ? `<p class="hint">+ ${d.available.length - 10} more on the <a href="/curriculum">Curriculum</a> page.</p>` : "")
    : `<p class="hint">${d.remaining_required ? "Nothing is unlocked yet — finish a prerequisite first (see the bottleneck list)." : "You've completed every required course."}</p>`;

  $("dash-bottlenecks").innerHTML = d.bottlenecks.length
    ? `<thead><tr><th>Course</th><th class="num">Unlocks</th><th>Status</th><th>Waiting on it</th></tr></thead><tbody>` + d.bottlenecks.map((b) =>
      `<tr><td class="wrap"><strong>${escapeHtml(b.code)}</strong> ${escapeHtml(b.name)}</td><td class="num">${b.unlocks}</td>` +
      `<td>${b.available_now ? '<span class="status-badge status-ok">Can take now</span>' : '<span class="status-badge status-muted">Needs a prerequisite</span>'}</td>` +
      `<td class="wrap hint-inline">${escapeHtml(b.examples.join(", "))}${b.unlocks > b.examples.length ? "…" : ""}</td></tr>`).join("") + `</tbody>`
    : `<tbody><tr><td class="hint">No remaining required course is waiting on another one.</td></tr></tbody>`;
}

(async () => {
  const d = await (await fetch("/api/dashboard")).json();
  $("dash-program").textContent = d.program ? `${d.username} · ${d.program}` : `Welcome, ${d.username}.`;
  // All done: hide. 3 of 4 done: one line under the progress cards. Fewer: the full checklist.
  const steps = setupSteps(d), left = steps.filter((st) => !st[0]);
  $("dash-start").hidden = left.length < 2;
  if (left.length >= 2) renderSetup(d);
  const line = $("dash-setup-line");
  line.hidden = left.length !== 1;
  if (left.length === 1) {
    const [, text, href] = left[0];
    line.innerHTML = `Finish setup: <strong>1 step left</strong> — <a href="${href}">${escapeHtml(text)}</a>`;
  }
  $("dash-main").hidden = !d.has_curriculum;
  if (d.has_curriculum) renderMain(d);
})();
