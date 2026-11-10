let currentFields = {};
let currentMapping = {};
let currentSheet = null;

// ---------------------------------------------------------------------------
// Curriculum paste-and-parse (moved here from the Curriculum page so all
// importing happens in one place -- Curriculum just displays the result).
// ---------------------------------------------------------------------------

let lastCurrParseResult = null;

function renderCurrParsePreview(result) {
  lastCurrParseResult = result;
  const el = document.getElementById("curr-parse-preview");

  if (!result.courses.length) {
    el.innerHTML = `<p class="hint">Nothing recognizable in that paste. Make sure each course is on its own line, in the order Code / Name / Category / Sub-Category / Credits / Requisites.</p>`;
    return;
  }

  const required = result.courses.filter((c) => c.required);
  const elective = result.courses.filter((c) => !c.required);

  let html = `<p class="hint">Found <strong>${result.courses.length}</strong> courses: <strong>${required.length}</strong> required, ${elective.length} elective. Uncheck any you don't want added/updated.</p>`;
  html += `<div class="parse-course-list">`;
  html += result.courses
    .map(
      (c) =>
        `<label class="parse-course-row"><input type="checkbox" class="curr-course-check" data-code="${c.code}" checked> <strong>${c.code}</strong> — ${c.name}${c.required ? "" : ` <span class="hint">(elective)</span>`}${c.hard_prereqs.length ? ` <span class="hint">(needs ${c.hard_prereqs.join(", ")})</span>` : ""}</label>`
    )
    .join("");
  html += `</div>`;

  if (result.unparsed.length) {
    html += `<p class="hint">Couldn't read ${result.unparsed.length} line(s):</p><pre class="parse-unparsed">${result.unparsed.map((l) => l.replace(/</g, "&lt;")).join("\n")}</pre>`;
  }

  html += `<button id="curr-apply-btn" class="save-btn">Apply checked courses to your curriculum</button>
           <p id="curr-apply-status" class="hint"></p>`;

  el.innerHTML = html;
  document.getElementById("curr-apply-btn").addEventListener("click", applyCurrParsedCourses);
}

async function applyCurrParsedCourses() {
  if (!lastCurrParseResult) return;
  const checked = new Set(
    Array.from(document.querySelectorAll(".curr-course-check:checked")).map((cb) => cb.dataset.code)
  );
  const statusEl = document.getElementById("curr-apply-status");
  statusEl.textContent = "Applying…";

  const curRes = await fetch("/api/curriculum");
  const cur = await curRes.json();
  const catalog = cur.catalog || [];
  const byCode = {};
  catalog.forEach((c) => {
    byCode[c.code] = c;
  });

  let addedCount = 0;
  let updatedCount = 0;
  lastCurrParseResult.courses.forEach((c) => {
    if (!checked.has(c.code)) return;
    const entry = {
      code: c.code,
      name: c.name,
      category: c.category,
      sub_category: c.sub_category || "",
      credits: c.credits,
      required: c.required,
      hard_prereqs: c.hard_prereqs,
      soft_prereqs: c.soft_prereqs,
    };
    if (byCode[c.code]) updatedCount += 1;
    else addedCount += 1;
    byCode[c.code] = entry;
  });

  const mergedCatalog = Object.values(byCode);
  const completed = new Set(cur.completed || []);
  cur.catalog = mergedCatalog;
  cur.required_remaining = mergedCatalog.filter((c) => c.required && !completed.has(c.code)).map((c) => c.code);
  const prereqs = {};
  mergedCatalog.forEach((c) => {
    if (c.hard_prereqs && c.hard_prereqs.length) prereqs[c.code] = c.hard_prereqs;
  });
  cur.prereqs = prereqs;

  const res = await fetch("/api/curriculum", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cur),
  });
  statusEl.textContent = res.ok
    ? `Saved — ${addedCount} new course(s), ${updatedCount} updated. Check the Curriculum page.`
    : "Something went wrong saving.";
}

document.getElementById("curr-parse-btn").addEventListener("click", async () => {
  const text = document.getElementById("curr-paste-input").value;
  const previewEl = document.getElementById("curr-parse-preview");
  if (!text.trim()) {
    previewEl.innerHTML = `<p class="hint">Paste something first.</p>`;
    return;
  }
  previewEl.innerHTML = `<p class="hint">Parsing…</p>`;
  try {
    const res = await fetch("/api/curriculum/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();
    renderCurrParsePreview(data);
  } catch (e) {
    previewEl.innerHTML = `<p class="hint">Something went wrong parsing that.</p>`;
  }
});

document.getElementById("upload-btn").addEventListener("click", async () => {
  const fileInput = document.getElementById("file-input");
  const status = document.getElementById("upload-status");
  if (!fileInput.files.length) {
    status.textContent = "Choose a file first.";
    return;
  }
  status.textContent = "Uploading…";
  document.getElementById("sheet-section").hidden = true;
  document.getElementById("mapping-section").hidden = true;
  document.getElementById("preview-section").hidden = true;

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  const res = await fetch("/api/import/upload", { method: "POST", body: formData });
  const data = await res.json();

  if (!res.ok) {
    status.textContent = data.error || "Upload failed.";
    return;
  }

  if (data.needs_sheet_choice) {
    status.textContent = `Found ${data.sheets.length} sheets in this workbook — pick the right one.`;
    renderSheetChoices(data.sheets);
    document.getElementById("sheet-section").hidden = false;
    return;
  }

  status.textContent = `Found ${data.headers.length} columns.`;
  applySheetResponse(data);
});

function renderSheetChoices(sheets) {
  const select = document.getElementById("sheet-select");
  select.innerHTML = "";

  // Don't auto-pick a sheet -- workbooks commonly keep old terms in the
  // same file (e.g. "F'24 ...", "F'26 ..."), and silently loading
  // whichever sheet happens to be first is how you end up mapping the
  // WRONG term's data without noticing. Force a deliberate choice.
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "— choose a sheet —";
  select.appendChild(placeholder);

  sheets.forEach((s) => {
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = s;
    select.appendChild(opt);
  });
  select.value = "";
  select.onchange = () => {
    if (select.value) chooseSheet(select.value);
  };
}

async function chooseSheet(sheetName) {
  const status = document.getElementById("upload-status");
  status.textContent = `Reading sheet "${sheetName}"…`;
  const res = await fetch("/api/import/sheet", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sheet_name: sheetName }),
  });
  const data = await res.json();
  if (!res.ok) {
    status.textContent = data.error || "Couldn't read that sheet.";
    return;
  }
  status.textContent = `Found ${data.headers.length} columns in "${sheetName}".`;
  applySheetResponse(data);
}

function applySheetResponse(data) {
  currentSheet = data.chosen_sheet || 0;
  currentFields = data.fields;
  currentMapping = data.guessed_mapping;
  renderMappingTable(data.headers);
  document.getElementById("mapping-section").hidden = false;
  document.getElementById("preview-section").hidden = true;
}

function renderMappingTable(headers) {
  const table = document.getElementById("mapping-table");
  table.innerHTML = "";
  const headerRow = document.createElement("tr");
  headerRow.innerHTML = "<th>Field we need</th><th>Your column</th>";
  table.appendChild(headerRow);

  Object.entries(currentFields).forEach(([field, description]) => {
    const row = document.createElement("tr");
    const select = document.createElement("select");
    const blankOpt = document.createElement("option");
    blankOpt.value = "";
    blankOpt.textContent = "— not in this sheet —";
    select.appendChild(blankOpt);
    headers.forEach((h) => {
      const opt = document.createElement("option");
      opt.value = h;
      opt.textContent = h;
      if (currentMapping[field] === h) opt.selected = true;
      select.appendChild(opt);
    });
    select.addEventListener("change", () => {
      if (select.value) currentMapping[field] = select.value;
      else delete currentMapping[field];
    });

    const fieldCell = document.createElement("td");
    fieldCell.textContent = description;
    const selectCell = document.createElement("td");
    selectCell.appendChild(select);
    row.appendChild(fieldCell);
    row.appendChild(selectCell);
    table.appendChild(row);
  });
}

document.getElementById("preview-btn").addEventListener("click", async () => {
  const res = await fetch("/api/import/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mapping: currentMapping, sheet_name: currentSheet }),
  });
  const data = await res.json();
  document.getElementById("preview-section").hidden = false;
  const tbody0 = document.getElementById("preview-table-body");
  const errEl0 = document.getElementById("preview-errors");

  if (!res.ok) {
    tbody0.innerHTML = "";
    document.getElementById("preview-summary").textContent = "";
    errEl0.innerHTML = `<div class="banner warn"><strong>Couldn't preview this sheet:</strong><br>${data.error || "Unknown error."}<br><span class="hint">Double check the sheet you picked above is really this term's course list, and that every required field in the mapping table has a column chosen.</span></div>`;
    return;
  }

  document.getElementById("preview-summary").textContent =
    `${data.total_rows} rows parsed OK` + (data.total_errors ? `, ${data.total_errors} rows had problems (shown below).` : ".");

  const tbody = document.getElementById("preview-table-body");
  tbody.innerHTML = "";
  data.rows.forEach((r) => {
    const tr = document.createElement("tr");
    const timeText = r.online ? "Online / no fixed time" : `${r.days.join("/")} ${r.start}-${r.end}`;
    tr.innerHTML = `<td>${r.code}</td><td>${r.section}</td><td>${r.title}</td><td colspan="2">${timeText}</td><td>${r.credits}</td><td>${r.instructor}</td>`;
    tbody.appendChild(tr);
  });

  const errEl = document.getElementById("preview-errors");
  errEl.innerHTML = "";
  if (data.errors.length) {
    const list = document.createElement("div");
    list.className = "banner warn";
    list.innerHTML = "<strong>Rows that need a closer look:</strong><br>" +
      data.errors.map((e) => `Row ${e.row}: ${e.reason}`).join("<br>");
    errEl.appendChild(list);
  }
});

document.getElementById("commit-btn").addEventListener("click", async () => {
  const status = document.getElementById("commit-status");
  status.textContent = "Importing…";
  const res = await fetch("/api/import/commit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mapping: currentMapping, sheet_name: currentSheet, mode: applyMode() }),
  });
  const data = await res.json();
  status.textContent = res.ok
    ? `${describeApply(data)} Go to Browse or Plan to see them.`
    : (data.error || "Import failed.");
});

document.getElementById("parse-btn").addEventListener("click", async () => {
  const text = document.getElementById("paste-input").value;
  const out = document.getElementById("parse-output");
  if (!text.trim()) {
    out.innerHTML = `<p class="hint">Paste something first.</p>`;
    return;
  }
  out.innerHTML = `<p class="hint">Parsing…</p>`;

  const res = await fetch("/api/import/parse-text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  const data = await res.json();

  if (!res.ok) {
    out.innerHTML = `<p class="hint">${data.error || "Something went wrong parsing that."}</p>`;
    return;
  }

  lastPastedRows = data.parsed;
  document.getElementById("parse-apply-row").hidden = !data.parsed.length;
  document.getElementById("parse-apply-status").textContent = "";

  if (!data.parsed.length) {
    out.innerHTML = `<p class="hint">Nothing recognizable in that paste. Each line should have a course code, a meeting time, and (ideally) credits and an instructor -- copy straight from the on-screen table rather than retyping it.</p>`;
    return;
  }

  let html = `<p class="hint">Parsed <strong>${data.parsed.length}</strong> section(s)${data.unparsed.length ? `, couldn't read ${data.unparsed.length} line(s)` : ""}.</p>`;
  html += `<div class="table-wrap"><table class="course-table"><thead><tr><th>Code</th><th>Sec</th><th>Title</th><th colspan="2">Time</th><th>Credits</th><th>Instructor</th></tr></thead><tbody>`;
  html += data.parsed
    .map((r) => {
      const timeText = r.online ? "Online / no fixed time" : `${r.days.join("/")} ${r.start}-${r.end}`;
      return `<tr><td>${r.code}</td><td>${r.section}</td><td>${r.title}</td><td colspan="2">${timeText}</td><td>${r.credits}</td><td>${r.instructor}</td></tr>`;
    })
    .join("");
  html += `</tbody></table></div>`;

  if (data.unparsed.length) {
    html += `<div class="banner warn"><strong>Couldn't read these line(s):</strong><br>${data.unparsed
      .map((l) => l.replace(/</g, "&lt;"))
      .join("<br>")}</div>`;
  }

  out.innerHTML = html;
});


// ---------------------------------------------------------------------------
// Applying updates: merge vs replace, pasted rows, and manual entry
// ---------------------------------------------------------------------------

let lastPastedRows = [];

function applyMode() {
  const checked = document.querySelector("input[name=apply-mode]:checked");
  return checked ? checked.value : "merge";
}

function describeApply(r) {
  const parts = [`${r.added} new`, `${r.updated} updated`];
  if (r.removed) parts.push(`${r.removed} removed`);
  return `Done — ${parts.join(", ")} (${r.total} sections now loaded).`;
}

document.getElementById("parse-apply-btn").addEventListener("click", async () => {
  const status = document.getElementById("parse-apply-status");
  status.textContent = "Saving…";
  const res = await fetch("/api/offerings/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rows: lastPastedRows, mode: applyMode() }),
  });
  const data = await res.json();
  status.textContent = res.ok ? describeApply(data) : (data.error || "Couldn't save.");
  if (res.ok) loadOfferingsTable();
});

// ---- Manual section form + current offerings table ----

let allOfferings = [];
let editingOriginal = null; // {code, section} while editing an existing row
const MS = (id) => document.getElementById(id);

function readSectionForm() {
  return {
    code: MS("ms-code").value,
    section: MS("ms-section").value,
    title: MS("ms-title").value,
    credits: MS("ms-credits").value,
    department: MS("ms-department").value,
    instructor: MS("ms-instructor").value,
    start: MS("ms-start").value,
    end: MS("ms-end").value,
    location: MS("ms-location").value,
    start_date: MS("ms-start-date").value,
    end_date: MS("ms-end-date").value,
    prerequisites: MS("ms-prereq").value,
    seats_total: MS("ms-seats-total").value,
    seats_available: MS("ms-seats-available").value,
    online: MS("ms-online").checked,
    days: Array.from(document.querySelectorAll("#ms-days input[value]:checked")).map((cb) => cb.value),
  };
}

function syncOnlineToggle() {
  const online = MS("ms-online").checked;
  ["ms-start", "ms-end"].forEach((id) => { MS(id).disabled = online; });
  document.querySelectorAll("#ms-days input[value]").forEach((cb) => { cb.disabled = online; });
}

function clearSectionForm() {
  editingOriginal = null;
  ["ms-code", "ms-section", "ms-title", "ms-department", "ms-instructor", "ms-start", "ms-end", "ms-seats-total", "ms-seats-available", "ms-location", "ms-start-date", "ms-end-date", "ms-prereq"]
    .forEach((id) => { MS(id).value = ""; });
  MS("ms-credits").value = "3";
  MS("ms-online").checked = false;
  document.querySelectorAll("#ms-days input[value]").forEach((cb) => { cb.checked = false; });
  MS("ms-heading").textContent = "Add a section";
  syncOnlineToggle();
}

function editSection(row) {
  editingOriginal = { code: row.code, section: row.section };
  MS("ms-code").value = row.code;
  MS("ms-section").value = row.section;
  MS("ms-title").value = row.title || "";
  MS("ms-credits").value = row.credits;
  MS("ms-department").value = row.department || "";
  MS("ms-instructor").value = row.instructor || "";
  MS("ms-start").value = row.start || "";
  MS("ms-end").value = row.end || "";
  MS("ms-location").value = row.location || "";
  MS("ms-start-date").value = row.start_date || "";
  MS("ms-end-date").value = row.end_date || "";
  MS("ms-prereq").value = (row.prerequisites || []).join(", ");
  MS("ms-seats-total").value = row.seats_total ?? "";
  MS("ms-seats-available").value = row.seats_available ?? "";
  MS("ms-online").checked = !!row.online;
  document.querySelectorAll("#ms-days input[value]").forEach((cb) => { cb.checked = (row.days || []).includes(cb.value); });
  MS("ms-heading").textContent = `Edit ${row.code} section ${row.section}`;
  MS("manual-section-card").open = true;
  MS("ms-status").textContent = "";
  syncOnlineToggle();
  MS("manual-section-card").scrollIntoView({ behavior: "smooth", block: "start" });
}

MS("ms-online").addEventListener("change", syncOnlineToggle);
MS("ms-clear-btn").addEventListener("click", () => { clearSectionForm(); MS("ms-status").textContent = ""; });

MS("ms-save-btn").addEventListener("click", async () => {
  const status = MS("ms-status");
  status.textContent = "Saving…";
  const res = await fetch("/api/offerings/section", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ section: readSectionForm(), original: editingOriginal }),
  });
  const data = await res.json();
  if (!res.ok) {
    status.textContent = data.error || "Couldn't save.";
    return;
  }
  status.textContent = `${data.updated ? "Updated" : "Added"} ${data.section.code} section ${data.section.section}.`;
  clearSectionForm();
  await loadOfferingsTable();
});

function seatText(r) {
  if (r.seats_available == null || r.seats_total == null) return "—";
  return `${r.seats_available}/${r.seats_total}`;
}

function renderOfferingsTable() {
  const q = MS("mo-search").value.trim().toLowerCase();
  const matches = allOfferings.filter((r) =>
    !q || `${r.code} ${r.title} ${r.instructor || ""}`.toLowerCase().includes(q)
  );
  const SHOW = 15;
  MS("mo-count").textContent = !allOfferings.length
    ? "No offerings loaded yet — import a file above or add a section by hand."
    : matches.length > SHOW
      ? `Showing ${SHOW} of ${matches.length} matches — keep typing to narrow it down.`
      : `${matches.length} section(s)`;
  MS("mo-table").hidden = !matches.length;
  const body = MS("mo-body");
  body.innerHTML = "";
  matches.slice(0, SHOW).forEach((r) => {
    const tr = document.createElement("tr");
    const time = r.online || !r.start ? "Online / no fixed time" : `${(r.days || []).join("/")} ${r.start}-${r.end}`;
    tr.innerHTML = `<td>${r.code}</td><td>${r.section}</td><td>${r.title}</td><td>${time}</td><td>${r.location || "—"}</td><td>${seatText(r)}</td><td></td>`;
    const cell = tr.lastElementChild;
    const edit = document.createElement("button");
    edit.className = "secondary";
    edit.textContent = "Edit";
    edit.onclick = () => editSection(r);
    const del = document.createElement("button");
    del.className = "secondary";
    del.textContent = "Delete";
    del.style.marginLeft = "6px";
    let armed = null;
    del.onclick = async () => {
      if (!armed) {
        del.textContent = "Sure? Click again";
        armed = setTimeout(() => { armed = null; del.textContent = "Delete"; }, 3000);
        return;
      }
      clearTimeout(armed);
      await fetch("/api/offerings/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: r.code, section: r.section }),
      });
      await loadOfferingsTable();
    };
    cell.append(edit, del);
    body.appendChild(tr);
  });
}

async function loadOfferingsTable() {
  const res = await fetch("/api/courses");
  allOfferings = (await res.json()).courses || [];
  renderOfferingsTable();
}

MS("mo-search").addEventListener("input", renderOfferingsTable);

// ---- Manual curriculum course ----

async function loadCategorySuggestions() {
  const cur = await (await fetch("/api/curriculum")).json();
  const cats = [...new Set((cur.catalog || []).map((c) => (c.category || "").trim()).filter(Boolean))];
  MS("mc-category-list").innerHTML = cats.map((c) => `<option value="${c}"></option>`).join("");
}

MS("mc-save-btn").addEventListener("click", async () => {
  const status = MS("mc-status");
  const m = /^([A-Za-z]{2,6})\s?(\d{3}[A-Za-z]?)$/.exec(MS("mc-code").value.trim());
  if (!m) { status.textContent = "Course code should look like 'COSC 121'."; return; }
  const code = `${m[1].toUpperCase()} ${m[2].toUpperCase()}`;
  const name = MS("mc-name").value.trim();
  if (!name) { status.textContent = "Course name is required."; return; }
  const credits = parseFloat(MS("mc-credits").value);
  if (!(credits > 0)) { status.textContent = "Credits must be more than 0."; return; }
  const prereqs = MS("mc-prereqs").value
    .split(/[,;]/).map((p) => p.trim().toUpperCase().replace(/^([A-Z]{2,6})\s?(\d{3}[A-Z]?)$/, "$1 $2")).filter(Boolean);

  status.textContent = "Saving…";
  const cur = await (await fetch("/api/curriculum")).json();
  const catalog = cur.catalog || [];
  const existing = catalog.findIndex((c) => c.code === code);
  const entry = {
    code, name,
    category: MS("mc-category").value.trim(),
    sub_category: existing >= 0 ? (catalog[existing].sub_category || "") : "",
    credits,
    required: MS("mc-required").checked,
    hard_prereqs: prereqs,
    soft_prereqs: existing >= 0 ? (catalog[existing].soft_prereqs || []) : [],
  };
  if (existing >= 0) catalog[existing] = entry; else catalog.push(entry);

  const completed = new Set(cur.completed || []);
  cur.catalog = catalog;
  cur.required_remaining = catalog.filter((c) => c.required && !completed.has(c.code)).map((c) => c.code);
  cur.prereqs = {};
  catalog.forEach((c) => { if (c.hard_prereqs && c.hard_prereqs.length) cur.prereqs[c.code] = c.hard_prereqs; });

  const res = await fetch("/api/curriculum", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cur),
  });
  status.textContent = res.ok ? `${existing >= 0 ? "Updated" : "Added"} ${code}. See it on the Curriculum page.` : "Something went wrong saving.";
  if (res.ok) { ["mc-code", "mc-name", "mc-prereqs"].forEach((id) => { MS(id).value = ""; }); loadCategorySuggestions(); }
});

loadOfferingsTable();
loadCategorySuggestions();


// ---- Academic calendar (admin edits; everyone can read) ----

let calDetected = null;

function breakRow(b) {
  const row = document.createElement("div");
  row.className = "cal-break manual-grid";
  row.innerHTML = `
    <label class="wide">Name<input type="text" class="cb-name" placeholder="Pchum Ben" /></label>
    <label>From<input type="date" class="cb-start" /></label>
    <label>To<input type="date" class="cb-end" /></label>
    <button class="secondary cb-remove" type="button" style="align-self:end;">Remove</button>`;
  row.querySelector(".cb-name").value = b.name || "";
  row.querySelector(".cb-start").value = b.start || "";
  row.querySelector(".cb-end").value = b.end || "";
  row.querySelector(".cb-remove").onclick = () => row.remove();
  return row;
}

function eventRow(e) {
  const row = document.createElement("div");
  row.className = "cal-event manual-grid";
  const kinds = [["holiday", "Holiday (campus closed, no classes)"], ["break", "Break (no classes)"], ["deadline", "Deadline"], ["exam", "Exams"], ["term", "Term start / end"], ["other", "Other"]];
  row.innerHTML = `
    <label class="wide">Name<input type="text" class="ce-name" placeholder="Last day to WITHDRAW" /></label>
    <label>From<input type="date" class="ce-start" /></label>
    <label>To (optional)<input type="date" class="ce-end" /></label>
    <label>Type<select class="ce-kind">${kinds.map(([v, t]) => `<option value="${v}">${t}</option>`).join("")}</select></label>
    <button class="secondary ce-remove" type="button" style="align-self:end;">Remove</button>`;
  row.querySelector(".ce-name").value = e.name || "";
  row.querySelector(".ce-start").value = e.start || "";
  row.querySelector(".ce-end").value = e.end && e.end !== e.start ? e.end : "";
  row.querySelector(".ce-kind").value = e.kind || "other";
  row.querySelector(".ce-remove").onclick = () => row.remove();
  return row;
}

function setCalendarEditable(can) {
  MS("cal-readonly").hidden = can;
  document.querySelectorAll("#cal-card input, #cal-card button, #cal-card select").forEach((el) => { el.disabled = !can; });
}

function fmtDate(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}

async function loadCalendar() {
  const data = await (await fetch("/api/academic-calendar")).json();
  const cal = data.calendar || {};
  MS("cal-term").value = cal.term || "";
  MS("cal-start").value = cal.start || "";
  MS("cal-end").value = cal.end || "";
  MS("cal-registration").value = cal.registration_date || "";
  const evWrap = MS("cal-events");
  evWrap.innerHTML = "";
  // Older calendars kept breaks in a separate list: show any that aren't among the important dates yet.
  const events = (cal.events || []).slice();
  const have = new Set(events.map((e) => `${e.start}|${e.end || e.start}`));
  (cal.breaks || []).forEach((b) => { if (!have.has(`${b.start}|${b.end || b.start}`)) events.push({ name: b.name, start: b.start, end: b.end, kind: "break" }); });
  events.sort((a, b) => (a.start || "").localeCompare(b.start || ""));
  events.forEach((e) => evWrap.appendChild(eventRow(e)));

  calDetected = data.detected;
  const det = MS("cal-detected");
  if (calDetected && (calDetected.start !== cal.start || calDetected.end !== cal.end)) {
    det.hidden = false;
    det.innerHTML = `Your imported sections mostly run <strong>${fmtDate(calDetected.start)}</strong> to <strong>${fmtDate(calDetected.end)}</strong> (${calDetected.sections} sections). `;
    if (data.can_edit) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "secondary";
      btn.textContent = "Use these dates";
      btn.onclick = () => { MS("cal-start").value = calDetected.start; MS("cal-end").value = calDetected.end; };
      det.appendChild(btn);
    }
  } else {
    det.hidden = true;
  }
  setCalendarEditable(!!data.can_edit);
}

MS("cal-add-event").addEventListener("click", () => MS("cal-events").appendChild(eventRow({})));

MS("cal-save-btn").addEventListener("click", async () => {
  const status = MS("cal-status");
  status.textContent = "Saving…";
  const events = Array.from(document.querySelectorAll("#cal-events .cal-event"))
    .map((r) => ({
      name: r.querySelector(".ce-name").value,
      start: r.querySelector(".ce-start").value,
      end: r.querySelector(".ce-end").value,
      kind: r.querySelector(".ce-kind").value,
    }))
    .filter((e) => e.name || e.start);
  const res = await fetch("/api/academic-calendar", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ term: MS("cal-term").value, start: MS("cal-start").value, end: MS("cal-end").value, registration_date: MS("cal-registration").value, events }),
  });
  const data = await res.json();
  status.textContent = res.ok ? "Saved. New calendar exports will use these dates." : (data.error || "Couldn't save.");
  if (res.ok) loadCalendar();
});

loadCalendar();


// ---- Demo student (admin) ----
(function () {
  const btn = document.getElementById("demo-btn");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const status = document.getElementById("demo-status"), box = document.getElementById("demo-result");
    btn.disabled = true;
    status.textContent = "Creating…";
    try {
      const res = await fetch("/api/admin/demo-student", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = await res.json();
      if (!res.ok) { status.textContent = data.error || "Couldn't create the demo student."; return; }
      const sm = data.summary;
      status.textContent = "Created.";
      box.hidden = false;
      box.innerHTML = `<p><strong>Username:</strong> <code>${escapeHtml(data.username)}</code><br><strong>Password:</strong> <code>${escapeHtml(data.password)}</code></p>
        <p class="hint">Save the password now: it isn't shown again. Log out, then sign in as this student. ${escapeHtml(data.program)} · ${sm.completed} courses completed (${sm.credits} credits, GPA ${sm.gpa == null ? "—" : sm.gpa.toFixed(2)}) · wishlist: ${escapeHtml(sm.wishlist.join(", ") || "none")} · ${sm.pins} pinned plan${sm.pins === 1 ? "" : "s"}.</p>`;
    } catch (e) {
      status.textContent = "Couldn't reach the server.";
    } finally {
      btn.disabled = false;
    }
  });
})();
