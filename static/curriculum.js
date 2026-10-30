let state = {
  program: "",
  year: "",
  semester: "",
  completed: [],
  completed_semesters: {},
  required_remaining: [],
  catalog: [],
  prereqs: {},
  target_credits: { min: 12, max: 17 },
  preferences: { avoid_before: "", avoid_days: [], priority_courses: [], ignore_prereqs: false },
};

let offeredCodes = null; // Set of codes offered this term, or null if nothing imported yet

// Group order mirrors how AUPP's own curriculum view separates these --
// required categories first, then electives, unrecognized categories last.
const _CATEGORY_ORDER = [
  "general education (required)",
  "major",
  "core/major",
  "major electives",
  "electives",
  "general education",
];

function categoryRank(category) {
  const idx = _CATEGORY_ORDER.indexOf((category || "").trim().toLowerCase());
  return idx === -1 ? _CATEGORY_ORDER.length : idx;
}

function categoryLabel(category) {
  return (category || "").trim() || "Uncategorized";
}

function statusBadge(text, kind) {
  return `<span class="status-badge status-${kind}">${text}</span>`;
}

function courseStatus(course) {
  if (state.completed.includes(course.code)) {
    return statusBadge("Completed", "ok");
  }
  if (!course.required) {
    const offered = offeredCodes === null || offeredCodes.has(course.code);
    return statusBadge(offered ? "Elective · offered" : "Elective · not offered", "muted");
  }
  const missing = (course.hard_prereqs || []).filter((p) => !state.completed.includes(p));
  if (missing.length) {
    return statusBadge(`Blocked — needs ${missing.join(", ")}`, "danger");
  }
  if (offeredCodes !== null && !offeredCodes.has(course.code)) {
    return statusBadge("Not offered this term", "warn");
  }
  return statusBadge("Available now", "ok");
}

// ---- Semesters (Spring / Summer / Fall, as AUPP runs them) ----
const _TERM_ORDER = { spring: 1, summer: 2, fall: 3 };

function termKey(label) {
  const m = /^(spring|summer|fall)\s+(\d{4})$/i.exec((label || "").trim());
  return m ? Number(m[2]) * 10 + _TERM_ORDER[m[1].toLowerCase()] : null;
}

function termOptionList(extra) {
  const year = new Date().getFullYear();
  const list = [];
  for (let y = year + 1; y >= year - 6; y--) {
    ["Fall", "Summer", "Spring"].forEach((t) => list.push(`${t} ${y}`));
  }
  if (extra && !list.includes(extra)) list.unshift(extra);
  return list;
}

function semesterSelectHtml(code) {
  const current = state.completed_semesters[code] || "";
  const opts = termOptionList(current)
    .map((t) => `<option value="${t}" ${t === current ? "selected" : ""}>${t}</option>`)
    .join("");
  return `<select class="sem-select" aria-label="Semester taken"><option value="">Pick semester…</option>${opts}</select>`;
}

function creditsOf(code) {
  const c = state.catalog.find((x) => x.code === code);
  return c ? Number(c.credits) || 0 : 0;
}

function renderCompletedBySemester() {
  const el = document.getElementById("completed-by-semester");
  if (!state.completed.length) {
    el.innerHTML = `<p class="hint">Nothing marked completed yet. Set a course to "Completed" in the table below, then pick the semester you took it.</p>`;
    return;
  }
  const UNSPEC = "No semester picked yet";
  const groups = {};
  state.completed.forEach((code) => {
    const label = state.completed_semesters[code] || UNSPEC;
    groups[label] = groups[label] || [];
    groups[label].push(code);
  });
  const order = Object.keys(groups).sort((a, b) => {
    if (a === UNSPEC) return 1;
    if (b === UNSPEC) return -1;
    const ka = termKey(a), kb = termKey(b);
    if (ka !== null && kb !== null) return ka - kb;
    return a.localeCompare(b);
  });
  let html = order
    .map((label) => {
      const codes = groups[label].slice().sort();
      const total = codes.reduce((sum, c) => sum + creditsOf(c), 0);
      const meta = label === UNSPEC ? "" : ` <span class="hint" style="display:inline;">${total} cr</span>`;
      return `<div class="semester-group"><span class="semester-label">${label}</span>${meta} ${codes.join(", ")}</div>`;
    })
    .join("");
  if (groups[UNSPEC]) {
    html += `<p class="hint" style="margin-top:var(--sp-2);">${groups[UNSPEC].length} completed course(s) still need a semester — pick one in the "Semester taken" column below.</p>`;
  }
  el.innerHTML = html;
}

const openGroups = new Set(); // category / term groups the student has expanded

function renderCurriculumGroups() {
  const empty = document.getElementById("curriculum-empty");
  const container = document.getElementById("curriculum-groups");
  if (!state.catalog.length) {
    empty.hidden = false;
    container.innerHTML = "";
    document.getElementById("curr-toolbar").hidden = false; // "+ Add a course" still works when empty
    document.getElementById("slots-note").hidden = true;
    return;
  }
  empty.hidden = true;
  document.getElementById("curr-toolbar").hidden = false;
  renderSlotsNote();

  const byPlan = groupByMode() === "plan";
  const groups = {};
  const q = (document.getElementById("curr-search").value || "").trim().toLowerCase();
  const mode = document.getElementById("curr-status").value;
  const shown = state.catalog.filter((c) => {
    if (q && !`${c.code} ${c.name || ""}`.toLowerCase().includes(q)) return false;
    const done = state.completed.includes(c.code);
    if (mode === "done") return done;
    if (mode === "todo") return !done;
    if (mode === "available") return !done && c.required && !(c.hard_prereqs || []).some((p) => !state.completed.includes(p)) && (offeredCodes === null || offeredCodes.has(c.code));
    return true;
  });
  renderSummary(shown.length);
  if (!shown.length) {
    container.innerHTML = `<p class="hint">No courses match. Clear the search or choose "All courses".</p>`;
    return;
  }
  shown.forEach((c) => {
    const label = byPlan ? planLabel(c) || "Not in the sample plan" : categoryLabel(c.category);
    groups[label] = groups[label] || [];
    groups[label].push(c);
  });

  const groupLabels = Object.keys(groups).sort((a, b) => {
    if (byPlan) return planRank(a) - planRank(b) || a.localeCompare(b);
    const ra = categoryRank(a === "Uncategorized" ? "\0" : a);
    const rb = categoryRank(b === "Uncategorized" ? "\0" : b);
    if (ra !== rb) return ra - rb;
    return a.localeCompare(b);
  });

  container.innerHTML = "";
  groupLabels.forEach((label) => {
    const courses = groups[label].sort((a, b) => a.code.localeCompare(b.code));
    const section = document.createElement("div");
    section.className = "curriculum-group";
    const filtering = !!q || mode !== "all";
    const isOpen = filtering || openGroups.has(label);
    const doneCr = courses.filter((c) => state.completed.includes(c.code)).reduce((a, c) => a + (Number(c.credits) || 0), 0);
    const totalCr = courses.reduce((a, c) => a + (Number(c.credits) || 0), 0);
    section.innerHTML = `
      <button type="button" class="group-toggle" aria-expanded="${isOpen}">
        <span class="group-icon" aria-hidden="true">${isOpen ? "−" : "+"}</span>
        <span class="group-name">${escapeHtml(label)}</span>
        <span class="curriculum-group-count">${courses.length}</span>
        <span class="group-credits">${doneCr} / ${totalCr} cr completed</span>
      </button>
      <div class="group-body" ${isOpen ? "" : "hidden"}>
      <div class="table-wrap"><table class="course-table curr-table">
        <thead><tr><th>Completion</th><th>Semester taken</th><th>Code</th><th>Title</th><th>Credits</th><th>Prereqs</th><th>Sample plan</th><th>Availability</th><th></th></tr></thead>
        <tbody></tbody>
      </table></div></div>
    `;
    section.querySelector(".group-toggle").addEventListener("click", () => {
      if (openGroups.has(label)) openGroups.delete(label); else openGroups.add(label);
      const open = openGroups.has(label);
      const btn = section.querySelector(".group-toggle");
      btn.setAttribute("aria-expanded", String(open));
      btn.querySelector(".group-icon").textContent = open ? "−" : "+";
      section.querySelector(".group-body").hidden = !open;
    });
    const tbody = section.querySelector("tbody");
    courses.forEach((course) => {
      const isDone = state.completed.includes(course.code);
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>
          <select class="status-select">
            <option value="not_done" ${isDone ? "" : "selected"}>Not yet</option>
            <option value="done" ${isDone ? "selected" : ""}>Completed</option>
          </select>
        </td>
        <td class="sem-cell">${isDone ? semesterSelectHtml(course.code) : '<span class="hint">—</span>'}</td>
        <td class="code-cell">${course.code}</td>
        <td>${course.name || ""}</td>
        <td class="num">${course.credits}</td>
        <td class="prereq-cell">${(course.hard_prereqs || []).map((p) => `<span class="nw">${escapeHtml(p)}</span>`).join(" ") || "—"}</td>
        <td class="nw">${planLabel(course) || '<span class="hint">—</span>'}</td>
        <td class="status-cell">${courseStatus(course)}</td>
        <td class="row-actions"></td>
      `;
      const actions = tr.querySelector(".row-actions");
      const editBtn = document.createElement("button");
      editBtn.className = "secondary";
      editBtn.textContent = "Edit";
      editBtn.onclick = () => openEditor(course);
      const delBtn = document.createElement("button");
      delBtn.className = "secondary";
      delBtn.textContent = "Remove";
      
      let armed = null;
      delBtn.onclick = () => {
        if (!armed) {
          delBtn.textContent = "Sure? Click again";
          armed = setTimeout(() => { armed = null; delBtn.textContent = "Remove"; }, 3000);
          return;
        }
        clearTimeout(armed);
        state.catalog = state.catalog.filter((c) => c.code !== course.code);
        state.completed = state.completed.filter((c) => c !== course.code);
        delete state.completed_semesters[course.code];
        renderAll();
        MS_STATUS("Removed " + course.code + ". Press Save curriculum to keep this.");
      };
      actions.append(editBtn, delBtn);
      const select = tr.querySelector(".status-select");
      select.addEventListener("change", () => {
        if (select.value === "done") {
          if (!state.completed.includes(course.code)) state.completed.push(course.code);
        } else {
          state.completed = state.completed.filter((c) => c !== course.code);
          delete state.completed_semesters[course.code];
        }
        renderCompletedBySemester();
        // A completion change can affect any course gated on this one as a
        // prereq, so re-render every group's availability column -- the
        // curriculum is small enough that this is instant.
        renderCurriculumGroups();
      });
      const semSelect = tr.querySelector(".sem-select");
      if (semSelect) {
        semSelect.addEventListener("change", () => {
          if (semSelect.value) state.completed_semesters[course.code] = semSelect.value;
          else delete state.completed_semesters[course.code];
          renderCompletedBySemester();
        });
      }
      tbody.appendChild(tr);
    });
    container.appendChild(section);
  });
}

function renderSummary(shownCount) {
  const done = state.catalog.filter((c) => state.completed.includes(c.code));
  const todoReq = state.catalog.filter((c) => c.required && !state.completed.includes(c.code));
  const cr = (list) => list.reduce((a, c) => a + (Number(c.credits) || 0), 0);
  document.getElementById("curr-summary").innerHTML =
    `<span><strong>${done.length}</strong> completed (${cr(done)} cr)</span><span><strong>${todoReq.length}</strong> required left (${cr(todoReq)} cr)</span>` +
    (shownCount !== state.catalog.length ? `<span>showing ${shownCount} of ${state.catalog.length}</span>` : "");
  const note = document.getElementById("plan-summary-note");
  if (note) note.textContent = state.program ? `· ${state.program}` : "";
  const card = document.getElementById("plan-card");
  if (card && !card.dataset.init) { card.dataset.init = "1"; card.open = !state.catalog.length; }
}

function renderAll() {
  // Nothing to save until a curriculum exists: hide the sticky Save bar.
  document.querySelector(".save-bar").hidden = !state.catalog.length;
  renderMarkThrough();
  document.getElementById("c-program").value = state.program || "";
  document.getElementById("c-year").value = state.year || "";
  document.getElementById("c-semester").value = state.semester || "";
  document.getElementById("c-min-credits").value = state.target_credits.min;
  document.getElementById("c-max-credits").value = state.target_credits.max;
  renderCompletedBySemester();
  renderCurriculumGroups();
}

async function loadCurriculum() {
  const [curRes, coursesRes] = await Promise.all([fetch("/api/curriculum"), fetch("/api/courses")]);
  const data = await curRes.json();
  const coursesData = await coursesRes.json();
  const offerings = coursesData.courses || [];
  offeredCodes = offerings.length ? new Set(offerings.map((c) => c.code)) : null;

  state = {
    ...data,
    program: data.program || "",
    year: data.year || "",
    semester: data.semester || "",
    completed: data.completed || [],
    completed_semesters: data.completed_semesters || {},
    required_remaining: data.required_remaining || [],
    catalog: data.catalog || [],
    prereqs: data.prereqs || {},
    target_credits: data.target_credits || { min: 12, max: 17 },
    preferences: data.preferences || { avoid_before: "", avoid_days: [], priority_courses: [], ignore_prereqs: false },
  };
  renderAll();
}

document.getElementById("save-btn").addEventListener("click", async () => {
  state.program = document.getElementById("c-program").value.trim();
  state.year = document.getElementById("c-year").value.trim();
  state.semester = document.getElementById("c-semester").value.trim();
  state.target_credits.min = parseInt(document.getElementById("c-min-credits").value, 10) || 12;
  state.target_credits.max = parseInt(document.getElementById("c-max-credits").value, 10) || 17;

  // required_remaining and prereqs are always derived from the catalog so
  // they can never drift from what the table actually shows (the server
  // re-derives required_remaining too, as a second safety net).
  if (state.catalog.length) {
    state.required_remaining = state.catalog
      .filter((c) => c.required && !state.completed.includes(c.code))
      .map((c) => c.code);
    const prereqs = {};
    state.catalog.forEach((c) => {
      if (c.hard_prereqs && c.hard_prereqs.length) prereqs[c.code] = c.hard_prereqs;
    });
    state.prereqs = prereqs;
  }

  const statusEl = document.getElementById("save-status");
  statusEl.textContent = "Saving…";
  const res = await fetch("/api/curriculum", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state),
  });
  statusEl.textContent = res.ok ? "Saved." : "Something went wrong saving.";
});

loadCurriculum();


// ---------------------------------------------------------------------------
// Sample course plans, plan labels, and editing your own copy
// ---------------------------------------------------------------------------

const _PLAN_TERM_RANK = { Fall: 0, Spring: 1, Summer: 2 };

function planLabel(c) {
  return c.plan_year && c.plan_term ? `Year ${c.plan_year} · ${c.plan_term}` : "";
}

function planRank(label) {
  const m = /^Year (\d) · (\w+)$/.exec(label);
  return m ? Number(m[1]) * 10 + (_PLAN_TERM_RANK[m[2]] ?? 5) : 999;
}

function groupByMode() {
  const el = document.getElementById("group-by");
  return el ? el.value : "category";
}

function MS_STATUS(text) {
  document.getElementById("save-status").textContent = text;
}

function renderSlotsNote() {
  const el = document.getElementById("slots-note");
  const slots = state.elective_slots || [];
  if (!slots.length) { el.hidden = true; return; }
  const credits = slots.reduce((sum, x) => sum + (Number(x.credits) || 0), 0);
  el.hidden = false;
  el.textContent = `Your sample plan also has ${slots.length} open elective slot${slots.length === 1 ? "" : "s"} (${credits} credits) — ` +
    `choose them from the Major Electives below, or add your own course.`;
}

let programList = [];
let selectedProgram = null;

async function loadPrograms() {
  const data = await (await fetch("/api/programs")).json();
  programList = data.programs || [];
  const select = document.getElementById("plan-select");
  const groups = { Single: [], Dual: [], "": [] };
  programList.forEach((p) => (groups[p.degree] || groups[""]).push(p));
  select.innerHTML = '<option value="">Choose your program…</option>';
  [["Single", "Single degree"], ["Dual", "Dual degree"], ["", "Other"]].forEach(([key, label]) => {
    if (!groups[key].length) return;
    const og = document.createElement("optgroup");
    og.label = label;
    groups[key].sort((a, b) => a.name.localeCompare(b.name)).forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = `${p.name} · ${p.credit_total || p.planned_credits} credits`;
      og.appendChild(opt);
    });
    select.appendChild(og);
  });
  if (data.current) select.value = data.current;
  if (!programList.length) {
    document.getElementById("plan-hint").textContent = "No sample plans have been published yet. The admin can add them on the Import page.";
  }
  await showPlanPreview();
}

function escapeHtml(str) {
  return String(str == null ? "" : str).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

async function showPlanPreview() {
  const id = document.getElementById("plan-select").value;
  const box = document.getElementById("plan-preview");
  const useBtn = document.getElementById("plan-use-btn");
  useBtn.disabled = !id;
  if (!id) { box.innerHTML = ""; selectedProgram = null; return; }
  const data = await (await fetch(`/api/programs/${encodeURIComponent(id)}`)).json();
  selectedProgram = data.program;
  const p = selectedProgram;
  const years = {};
  p.terms.forEach((t) => { (years[t.year] = years[t.year] || []).push(t); });
  let html = `<p class="hint" style="margin-top:var(--sp-3);">${escapeHtml(p.name)}${p.degree ? ` (${p.degree} degree)` : ""} — ` +
    `${p.credit_total || ""} credits total, ${p.electives.length} approved electives.${p.note ? " " + escapeHtml(p.note) : ""}</p><div class="plan-years">`;
  Object.keys(years).sort().forEach((y) => {
    html += `<div class="plan-year"><h4>Year ${y}</h4><div class="plan-terms">`;
    years[y].forEach((t) => {
      const cr = t.courses.reduce((a, c) => a + c.credits, 0);
      html += `<div class="plan-term"><div class="plan-term-title">${t.term} <span class="hint" style="display:inline;">${cr} cr</span></div><ul>` +
        t.courses.map((c) => `<li class="cat-${(c.category || "").split(" ")[0].toLowerCase()}">${c.code ? `<strong>${escapeHtml(c.code)}</strong> ` : ""}${escapeHtml(c.title || "")}${c.slot ? " (open slot)" : ""}</li>`).join("") +
        `</ul></div>`;
    });
    html += `</div></div>`;
  });
  html += `</div><p class="hint legend-row"><span class="swatch cat-general"></span> General education <span class="swatch cat-major"></span> Major <span class="swatch cat-elective"></span> Elective</p>`;
  box.innerHTML = html;
}

document.getElementById("plan-select").addEventListener("change", showPlanPreview);

document.getElementById("plan-use-btn").addEventListener("click", async () => {
  if (!selectedProgram) return;
  const status = document.getElementById("plan-status");
  if (state.catalog.length && !confirm(
    `Replace your current course list with the ${selectedProgram.name} sample plan?\n\n` +
    `Your completed courses and their semesters are kept. Courses you added or edited by hand in your current list will be replaced.`)) return;
  status.textContent = "Loading…";
  const res = await fetch("/api/curriculum/from-program", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ program_id: selectedProgram.id }),
  });
  const data = await res.json();
  if (!res.ok) { status.textContent = data.error || "Couldn't load that plan."; return; }
  // Anything the student already typed in Year / Semester wins over the suggested values.
  const typed = { year: document.getElementById("c-year").value.trim(), semester: document.getElementById("c-semester").value.trim() };
  await loadCurriculum();
  ["year", "semester"].forEach((k) => {
    if (typed[k]) { state[k] = typed[k]; document.getElementById("c-" + k).value = typed[k]; }
  });
  document.getElementById("group-by").value = "plan";
  renderCurriculumGroups();
  const filled = (data.filled || []).filter((k) => !typed[k]).map((k) => (k === "year" ? "Year" : "Semester"));
  status.textContent = `Loaded ${data.courses} courses. ` +
    (filled.length ? `Filled in ${filled.join(" and ")} for you (change it if it's wrong). ` : "") +
    `Mark what you've completed below, and edit anything that differs for you.`;
  MS_STATUS(status.textContent);   // the sample-plan card collapses after loading, so say it here too
});

document.getElementById("group-by").addEventListener("change", renderCurriculumGroups);
document.getElementById("curr-search").addEventListener("input", renderCurriculumGroups);
document.getElementById("curr-status").addEventListener("change", renderCurriculumGroups);

// ---- editor for one course (add or edit; applied to this page, saved with "Save curriculum") ----

let editingCode = null;

function openEditor(course) {
  editingCode = course ? course.code : null;
  const cats = [...new Set(state.catalog.map((c) => (c.category || "").trim()).filter(Boolean))];
  ["General Education (Required)", "Major", "Major Electives", "Electives"].forEach((c) => { if (!cats.includes(c)) cats.push(c); });
  document.getElementById("ce-category-list").innerHTML = cats.map((c) => `<option value="${escapeHtml(c)}"></option>`).join("");
  document.getElementById("ce-heading").textContent = course ? `Edit ${course.code}` : "Add a course";
  document.getElementById("ce-code").value = course ? course.code : "";
  document.getElementById("ce-name").value = course ? course.name || "" : "";
  document.getElementById("ce-category").value = course ? course.category || "" : "Major Electives";
  document.getElementById("ce-credits").value = course ? course.credits : 3;
  document.getElementById("ce-prereqs").value = course ? (course.hard_prereqs || []).join(", ") : "";
  document.getElementById("ce-year").value = course && course.plan_year ? String(course.plan_year) : "";
  document.getElementById("ce-term").value = course && course.plan_term ? course.plan_term : "";
  document.getElementById("ce-required").checked = course ? !!course.required : false;
  document.getElementById("ce-status").textContent = "";
  const card = document.getElementById("course-editor");
  card.hidden = false;
  card.scrollIntoView({ behavior: "smooth", block: "center" });
}

document.getElementById("add-course-btn").addEventListener("click", () => openEditor(null));
document.getElementById("ce-cancel-btn").addEventListener("click", () => { document.getElementById("course-editor").hidden = true; });

document.getElementById("ce-apply-btn").addEventListener("click", () => {
  const status = document.getElementById("ce-status");
  const m = /^([A-Za-z]{2,5})\s?(\d{3}[A-Za-z]?)$/.exec(document.getElementById("ce-code").value.trim());
  if (!m) { status.textContent = "Course code should look like 'COSC 121'."; return; }
  const code = `${m[1].toUpperCase()} ${m[2].toUpperCase()}`;
  const name = document.getElementById("ce-name").value.trim();
  if (!name) { status.textContent = "Course name is required."; return; }
  const credits = parseFloat(document.getElementById("ce-credits").value);
  if (!(credits > 0)) { status.textContent = "Credits must be more than 0."; return; }
  if (code !== editingCode && state.catalog.some((c) => c.code === code)) {
    status.textContent = `${code} is already in your curriculum — edit that one instead.`;
    return;
  }
  const prereqs = document.getElementById("ce-prereqs").value
    .split(/[,;]/).map((p) => p.trim().toUpperCase().replace(/^([A-Z]{2,5})\s?(\d{3}[A-Z]?)$/, "$1 $2")).filter(Boolean);
  const year = parseInt(document.getElementById("ce-year").value, 10) || null;
  const term = document.getElementById("ce-term").value || null;

  const old = state.catalog.find((c) => c.code === editingCode);
  const entry = {
    ...(old || {}),
    code, name,
    category: document.getElementById("ce-category").value.trim() || "Electives",
    credits,
    required: document.getElementById("ce-required").checked,
    hard_prereqs: prereqs,
    soft_prereqs: old ? old.soft_prereqs || [] : [],
    sub_category: old ? old.sub_category || "" : "",
  };
  if (year && term) { entry.plan_year = year; entry.plan_term = term; } else { delete entry.plan_year; delete entry.plan_term; }
  if (old) {
    state.catalog[state.catalog.indexOf(old)] = entry;
    if (old.code !== code) {
      const i = state.completed.indexOf(old.code);
      if (i >= 0) state.completed[i] = code;
      if (state.completed_semesters[old.code]) {
        state.completed_semesters[code] = state.completed_semesters[old.code];
        delete state.completed_semesters[old.code];
      }
    }
  } else {
    state.catalog.push(entry);
  }
  document.getElementById("course-editor").hidden = true;
  renderAll();
  MS_STATUS(`${old ? "Updated" : "Added"} ${code}. Press Save curriculum to keep this.`);
});

loadPrograms();


// ---- "Mark everything up to here as completed" ----
const _MT_ORDER = { Fall: 0, Spring: 1, Summer: 2 };

function renderMarkThrough() {
  const box = document.getElementById("mark-through");
  const sems = [...new Set(state.catalog.filter((c) => c.plan_year && c.plan_term).map((c) => `${c.plan_year}|${c.plan_term}`))]
    .map((k) => k.split("|")).sort((a, b) => a[0] * 10 + (_MT_ORDER[a[1]] ?? 5) - (b[0] * 10 + (_MT_ORDER[b[1]] ?? 5)));
  box.hidden = !sems.length;
  const sel = document.getElementById("mt-select");
  const keep = sel.value;
  sel.innerHTML = '<option value="">Choose the last semester you finished…</option>' + sems.map(([y, t]) => `<option value="${y}|${t}">Year ${y} · ${t}</option>`).join("");
  sel.value = keep;
  document.getElementById("mt-btn").disabled = !sel.value;
}

document.getElementById("mt-select").addEventListener("change", () => { document.getElementById("mt-btn").disabled = !document.getElementById("mt-select").value; });
document.getElementById("mt-btn").addEventListener("click", async () => {
  const [year, term] = document.getElementById("mt-select").value.split("|");
  const status = document.getElementById("mt-status");
  const res = await fetch("/api/curriculum/through", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ year: Number(year), term }) });
  const data = await res.json();
  if (!res.ok) { status.textContent = data.error || "Couldn't do that."; return; }
  const inPage = new Set(state.catalog.map((c) => c.code));
  const fresh = data.codes.filter((c) => inPage.has(c) && !state.completed.includes(c));
  if (!fresh.length) { status.textContent = `Nothing new: everything up to Year ${year} · ${term} is already marked completed.`; return; }
  const credits = fresh.reduce((a, c) => a + creditsOf(c), 0);
  if (!confirm(`Mark ${fresh.length} course${fresh.length === 1 ? "" : "s"} (${credits} credits) as completed, everything in the sample plan up to Year ${year} · ${term}?\n\nCourses you already completed stay as they are. You can undo any of them in the table, and nothing is saved until you press Save curriculum.`)) return;
  state.completed.push(...fresh);
  renderAll();
  MS_STATUS(`Marked ${fresh.length} course${fresh.length === 1 ? "" : "s"} completed. Pick their semesters if you like, then press Save curriculum.`);
  status.textContent = `Marked ${fresh.length} course${fresh.length === 1 ? "" : "s"} (${credits} cr).`;
});
