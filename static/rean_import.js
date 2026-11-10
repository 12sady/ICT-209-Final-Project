// Curriculum page: optional "add prerequisites from Rean" (paste a Rean curriculum table).
// Previews first; Apply merges the ticked courses into the saved curriculum, then reloads this page's data.

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
    byCode[c.code] = { ...(byCode[c.code] || {}), ...entry };         // keep what we already know (sample-plan order, ...)
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
    ? `Saved — ${addedCount} new course(s), ${updatedCount} updated.`
    : "Something went wrong saving.";
  if (res.ok && typeof loadCurriculum === "function") {
    const done = statusEl.textContent;
    await loadCurriculum();                                           // show the result on this page
    document.getElementById("curr-parse-preview").innerHTML = `<p class="hint" role="status">${done} It now shows in your curriculum below.</p>`;
  }
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
