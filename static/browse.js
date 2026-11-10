let allCourses = [];
let allDepartments = [];
let currentWishlist = [];
let completedCodes = new Set();
let catalogByCode = {}; // code -> curriculum entry (empty if no curriculum loaded)
let currentPage = 1;
const PAGE_SIZE = 25;
const DEPT_PALETTE = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"];

// Best-effort default faculty filter based on the student's program name --
// still fully user-changeable, just saves a click for the common case.
const _PROGRAM_DEPT_HINTS = [
  [/artificial intelligence|computer|information tech|\bit\b|\bict\b/i, "IT"],
  [/business|entrepreneur/i, "BUSN"],
  [/international relations|\bir\b/i, "IR"],
  [/\blaw\b/i, "LAW"],
];

function guessDepartmentFromProgram(program) {
  if (!program) return null;
  for (const [pattern, dept] of _PROGRAM_DEPT_HINTS) {
    if (pattern.test(program)) return dept;
  }
  return null;
}

function deptColorVar(dept) {
  if (!dept) return null;
  const idx = allDepartments.indexOf(dept) % DEPT_PALETTE.length;
  return DEPT_PALETTE[idx];
}

function cssVarFor(varName) {
  return getComputedStyle(document.documentElement).getPropertyValue(`--${varName}`);
}

function riskClass(risk) {
  return "risk-" + (risk || "unknown").replace(" ", "-");
}

function timeBucket(start) {
  if (!start) return null;
  const [h] = start.split(":").map(Number);
  if (h < 12) return "morning";
  if (h < 17) return "afternoon";
  return "evening";
}

function timeText(c) {
  if (c.online || !c.start || !c.end) return '<span class="hint-inline">Online / no fixed time</span>';
  return `${c.days.join("/")} ${c.start}–${c.end}` + (c.location ? `<div class="hint-inline">${c.location}</div>` : "");
}

async function loadCourses() {
  const [coursesRes, curRes] = await Promise.all([fetch("/api/courses"), fetch("/api/curriculum")]);
  const data = await coursesRes.json();
  const cur = await curRes.json();
  allCourses = data.courses;
  allDepartments = [...new Set(allCourses.map((c) => c.department).filter(Boolean))].sort();
  completedCodes = new Set(cur.completed || []);
  catalogByCode = {};
  (cur.catalog || []).forEach((c) => { catalogByCode[c.code] = c; });
  const hasCurriculum = Object.keys(catalogByCode).length > 0;
  const curBox = document.getElementById("f-in-curriculum");
  if (curBox) {
    curBox.checked = hasCurriculum;
    curBox.closest("label").hidden = !hasCurriculum;
  }

  populateInstructorFilter();
  populateDepartmentFilter();

  // With a curriculum loaded, the "my curriculum" filter already narrows
  // things correctly (including gen-ed courses from other faculties), so the
  // faculty default is only a fallback for students with no curriculum yet.
  const guessedDept = hasCurriculum ? null : guessDepartmentFromProgram(cur.program || "");
  const deptSelect = document.getElementById("f-department");
  if (guessedDept && deptSelect && allDepartments.includes(guessedDept)) {
    deptSelect.value = guessedDept;
  }

  await loadWishlist();
  renderTable();
}

function populateInstructorFilter() {
  const select = document.getElementById("f-instructor");
  const instructors = [...new Set(allCourses.map((c) => c.instructor).filter(Boolean))].sort();
  instructors.forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    select.appendChild(opt);
  });
}

function populateDepartmentFilter() {
  const select = document.getElementById("f-department");
  if (!select) return;
  if (!allDepartments.length) {
    select.closest(".field").hidden = true;
    return;
  }
  allDepartments.forEach((dept) => {
    const opt = document.createElement("option");
    opt.value = dept;
    opt.textContent = dept;
    select.appendChild(opt);
  });
}

function currentFilters() {
  return {
    search: document.getElementById("f-search").value.trim().toLowerCase(),
    day: document.getElementById("f-day").value,
    time: document.getElementById("f-time").value,
    instructor: document.getElementById("f-instructor").value,
    risk: document.getElementById("f-risk").value,
    department: document.getElementById("f-department") ? document.getElementById("f-department").value : "",
    hideCompleted: document.getElementById("f-hide-completed") ? document.getElementById("f-hide-completed").checked : false,
    hideNotNeeded: document.getElementById("f-hide-notneeded") ? document.getElementById("f-hide-notneeded").checked : false,
    recommended: document.getElementById("f-recommended") ? document.getElementById("f-recommended").checked : false,
    inCurriculum: document.getElementById("f-in-curriculum") ? document.getElementById("f-in-curriculum").checked : false,
  };
}

function filteredCourses() {
  const f = currentFilters();
  const rows = allCourses.filter((c) => {
    if (f.search && !(`${c.code} ${c.title}`.toLowerCase().includes(f.search))) return false;
    if (f.day && !c.days.includes(f.day)) return false;
    if (f.time && (c.online || timeBucket(c.start) !== f.time)) return false;
    if (f.instructor && c.instructor !== f.instructor) return false;
    if (f.risk && (c.risk || "unknown") !== f.risk) return false;
    if (f.department && c.department !== f.department) return false;
    const st = c.mine && c.mine.status;
    if (f.hideCompleted && (completedCodes.has(c.code) || st === "completed" || st === "in_progress")) return false;
    if (f.hideNotNeeded && st === "not_needed") return false;
    if (f.recommended && !(c.mine && c.mine.recommended)) return false;
    if (f.inCurriculum && !catalogByCode[c.code]) return false;
    return true;
  });
  // Recommended view: what to take first (roadmap's next term, then required, then electives).
  if (f.recommended) rows.sort((a, b) => (a.mine.rank - b.mine.rank) || a.code.localeCompare(b.code) || String(a.section).localeCompare(String(b.section)));
  return rows;
}

// One short chip saying where this course stands for the student (from /api/courses -> c.mine).
function statusChip(c) {
  const m = c.mine;
  const chip = (cls, text, why) => `<div><span class="status-chip st-${cls}"${why ? ` title="${escapeHtml(why)}"` : ""}>${text}</span></div>`;
  if (!m || m.status === "not_in_curriculum") return "";
  if (m.status === "outside_ok") return chip("ok", "Can take now · outside your curriculum", m.reason);
  if (m.status === "outside_blocked") return chip("blocked", `Needs ${m.missing_prereqs.map(escapeHtml).join(", ")} · outside your curriculum`, m.reason);
  if (m.status === "completed") return chip("done", "Completed");
  if (m.status === "in_progress") return chip("progress", "In progress now", "You're taking this now. It counts as done for prerequisites and planning.");
  if (m.status === "blocked") return chip("blocked", `Needs ${m.missing_prereqs.map(escapeHtml).join(", ")}`);
  if (m.status === "not_needed") return chip("muted", "Not needed", m.reason);
  if (m.recommended) return chip("rec", "★ Recommended", m.reason) + `<div class="hint-inline">${escapeHtml(m.reason)}</div>`;
  return chip("ok", "Can take now");
}

function demandBadge(demand) {
  if (!demand || !demand.count) return `<span class="hint">—</span>`;
  const labels = { high: "High demand", popular: "Popular", some: "" };
  const who = demand.count === 1 ? "1 student" : `${demand.count} students`;
  const tag = labels[demand.level] ? ` · ${labels[demand.level]}` : "";
  return `<span class="demand-badge demand-${demand.level}">${who}${tag}</span>`;
}

// For items already on YOUR wishlist: show only how many OTHER students have
// it too (your own entry shouldn't count as "demand").
function othersBadge(demand) {
  if (!demand || !demand.others) return "";
  const who = demand.others === 1 ? "1 other student" : `${demand.others} other students`;
  const tag = demand.level === "high" ? " · High demand" : demand.level === "popular" ? " · Popular" : "";
  return `<br><span class="demand-badge demand-${demand.level}">${who}${tag}</span>`;
}

function curriculumTag(code) {
  const c = catalogByCode[code];
  if (!c) return "";
  const kind = c.required ? "Required" : "Elective";
  const cat = (c.category || "").trim();
  return `<div class="curr-tag">${kind}${cat ? " · " + cat : ""}</div>`;
}

function seatsText(c) {
  if (c.seats_available == null || c.seats_total == null) return "—";
  return `${Math.round(c.seats_available)}/${Math.round(c.seats_total)}`;
}

function renderTable() {
  const tbody = document.getElementById("course-table-body");
  const countEl = document.getElementById("course-count");
  tbody.innerHTML = "";

  if (!allCourses.length) {
    countEl.textContent = "";
    tbody.parentElement.hidden = true;
    document.getElementById("course-empty").hidden = false;
    return;
  }
  tbody.parentElement.hidden = false;
  document.getElementById("course-empty").hidden = true;

  const results = filteredCourses();
  countEl.textContent = results.length === allCourses.length
    ? `${allCourses.length} sections`
    : `${results.length} of ${allCourses.length} sections`;

  const totalPages = Math.max(1, Math.ceil(results.length / PAGE_SIZE));
  if (currentPage > totalPages) currentPage = totalPages;
  const pageStart = (currentPage - 1) * PAGE_SIZE;
  const pageResults = results.slice(pageStart, pageStart + PAGE_SIZE);

  pageResults.forEach((c) => {
    const tr = document.createElement("tr");
    const inWishlist = currentWishlist.some((w) => w.code === c.code);
    const deptVar = deptColorVar(c.department);
    const deptCell = c.department
      ? `<span class="dept-badge" style="background:${cssVarFor(deptVar)}">${c.department}</span>`
      : `<span class="hint">—</span>`;
    const seat = c.risk && c.risk !== "unknown"
      ? `<span class="risk-badge ${riskClass(c.risk)}">${seatsText(c)} · ${c.risk}</span>`
      : `<span class="hint-inline">No seat data</span>`;
    tr.innerHTML = `
      <td class="col-add"></td>
      <td class="course-cell"><span class="code-cell">${c.code}</span> <span class="hint-inline">sec ${c.section}</span><div>${deptCell}</div></td>
      <td class="wrap">${c.title}${curriculumTag(c.code)}${statusChip(c)}${(c.prerequisites || []).length ? `<div class="hint-inline">Prereq: ${c.prerequisites.map(escapeHtml).join(", ")}</div>` : ""}</td>
      <td class="when-cell">${timeText(c)}</td>
      <td class="num">${c.credits}</td>
      <td class="wrap">${c.instructor || "—"}</td>
      <td>${seat}</td>
      <td>${demandBadge(c.demand)}</td>
    `;
    const btnCell = tr.querySelector(".col-add");
    const btn = document.createElement("button");
    btn.setAttribute("aria-label", `${inWishlist ? "Already on wishlist:" : "Add to wishlist:"} ${c.code} section ${c.section}`);
    if (inWishlist) {
      btn.textContent = "✓ Added";
      btn.className = "secondary";
      btn.disabled = true;
    } else {
      btn.textContent = "+ Add";
      btn.onclick = () => addToWishlist(c.code);
    }
    btnCell.appendChild(btn);
    tbody.appendChild(tr);
  });

  renderPagination(totalPages);
}

function renderPagination(totalPages) {
  const el = document.getElementById("course-pagination");
  if (totalPages <= 1) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = `
    <button class="secondary" id="page-prev" ${currentPage <= 1 ? "disabled" : ""}>← Prev</button>
    <span class="hint" style="margin:0 4px;">Page ${currentPage} of ${totalPages}</span>
    <button class="secondary" id="page-next" ${currentPage >= totalPages ? "disabled" : ""}>Next →</button>
  `;
  document.getElementById("page-prev").onclick = () => {
    currentPage -= 1;
    renderTable();
    document.getElementById("course-table").scrollIntoView({ behavior: "smooth", block: "start" });
  };
  document.getElementById("page-next").onclick = () => {
    currentPage += 1;
    renderTable();
    document.getElementById("course-table").scrollIntoView({ behavior: "smooth", block: "start" });
  };
}

async function loadWishlist() {
  const res = await fetch("/api/wishlist");
  const data = await res.json();
  currentWishlist = data.wishlist;
  renderWishlist();
}

function renderWishlist() {
  const el = document.getElementById("wishlist-items");
  if (!currentWishlist.length) {
    el.innerHTML = '<p class="hint">Nothing yet — add courses from the table.</p>';
    return;
  }
  el.innerHTML = "";
  currentWishlist.forEach((w) => {
    const row = document.createElement("div");
    row.className = "wl-item";
    const statusLabel = { ok: "ready", blocked: "needs prereq", not_offered: "not offered" }[w.status] || w.status;
    row.innerHTML = `
      <span>${w.code} <span class="wl-status ${w.status}">${statusLabel}</span>${othersBadge(w.demand)}</span>
    `;
    const removeBtn = document.createElement("button");
    removeBtn.textContent = "Remove";
    removeBtn.className = "secondary";
    removeBtn.onclick = () => removeFromWishlist(w.code);
    row.appendChild(removeBtn);
    el.appendChild(row);
  });
}

async function addToWishlist(code) {
  await fetch("/api/wishlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  await loadWishlist();
  renderTable();
}

async function removeFromWishlist(code) {
  await fetch(`/api/wishlist/${encodeURIComponent(code)}`, { method: "DELETE" });
  await loadWishlist();
  renderTable();
}

// Phones: the filter panel hides behind a "Filters" button; the badge counts the active filters.
function updateFilterBadge() {
  const f = currentFilters();
  const n = [f.search, f.day, f.time, f.instructor, f.risk, f.department].filter(Boolean).length + (f.hideCompleted ? 1 : 0) + (f.hideNotNeeded ? 1 : 0) + (f.recommended ? 1 : 0) + (f.inCurriculum ? 1 : 0);
  const badge = document.getElementById("filters-badge");
  badge.hidden = n === 0;
  badge.textContent = String(n);
  document.getElementById("filters-toggle").setAttribute("aria-label", `Filters, ${n} active`);
}
document.getElementById("filters-toggle").addEventListener("click", () => {
  const panel = document.getElementById("filters-panel");
  const open = panel.classList.toggle("open");
  document.getElementById("filters-toggle").setAttribute("aria-expanded", String(open));
});

["f-search", "f-day", "f-time", "f-instructor", "f-risk", "f-department", "f-hide-completed", "f-hide-notneeded", "f-recommended", "f-in-curriculum"].forEach((id) => {
  const el = document.getElementById(id);
  if (!el) return;
  const handler = () => {
    currentPage = 1;
    updateFilterBadge();
    renderTable();
  };
  el.addEventListener("input", handler);
  el.addEventListener("change", handler);
});

document.addEventListener("advisor:changed", async () => {
  await loadWishlist();
  renderTable();
});

updateFilterBadge();
loadCourses();
