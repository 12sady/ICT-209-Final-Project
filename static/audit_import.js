// Curriculum page: build my curriculum from an AUPP SIS degree audit PDF.
// Uses escapeHtml / statusBadge / loadCurriculum from curriculum.js (loaded first).
// Preview saves nothing. Apply sends the same file again, so the server re-reads it.

(() => {
  const fileEl = document.getElementById("da-file");
  const readBtn = document.getElementById("da-read-btn");
  const statusEl = document.getElementById("da-status");
  const box = document.getElementById("da-preview");

  const STATUS = {
    completed: ["Passed", "ok"],
    in_progress: ["In progress", "muted"],
    not_taken: ["Not taken yet", "muted"],
    not_passed: ["Not passed", "warn"],
    unknown_grade: ["Unknown grade", "warn"],
  };

  fileEl.addEventListener("change", () => {
    readBtn.disabled = !fileEl.files.length;
    box.innerHTML = "";
    statusEl.textContent = "";
  });

  readBtn.addEventListener("click", async () => {
    const fd = new FormData();
    fd.append("file", fileEl.files[0]);
    statusEl.textContent = "Reading…";
    readBtn.disabled = true;
    try {
      const res = await fetch("/api/degree-audit/preview", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) { statusEl.textContent = data.error || "Couldn't read that file."; return; }
      render(data);
      statusEl.textContent = "";
    } catch (e) {
      statusEl.textContent = "Couldn't reach the app. Is it still running?";
    } finally {
      readBtn.disabled = !fileEl.files.length;
    }
  });

  function render(d) {
    const c = d.counts;
    const warn = (d.warnings || []).length
      ? `<p class="banner warn">${d.warnings.map(escapeHtml).join("<br>")}</p>` : "";
    const cats = d.categories.map((k) => `<tr>
        <td><strong>${escapeHtml(k.name)}</strong></td>
        <td>${k.target}</td><td>${k.listed}</td><td>${k.courses}</td>
        <td>${k.passed_credits}${k.reported_completed != null && k.reported_completed !== k.passed_credits ? ` <span class="hint">(audit says ${k.reported_completed})</span>` : ""}</td>
      </tr>`).join("");
    const rows = d.courses.map((r) => {
      const [label, kind] = STATUS[r.status] || ["?", "muted"];
      return `<tr>
        <td><strong>${escapeHtml(r.code)}</strong><br><span class="hint">${escapeHtml(r.name)}</span></td>
        <td>${r.category ? escapeHtml(r.category) : '<span class="hint">- (not counted)</span>'}</td>
        <td>${r.credits}</td><td>${escapeHtml(r.term || "")}</td><td><strong>${escapeHtml(r.grade || "")}</strong></td>
        <td>${statusBadge(label, kind)}</td></tr>`;
    }).join("");

    box.innerHTML = `
      ${warn}
      <p class="hint"><strong>${escapeHtml(d.program || "Your degree")}</strong>${d.catalog_term ? `, catalog ${escapeHtml(d.catalog_term)}` : ""}.
        ${d.total_required != null ? `${d.total_required} credits to graduate, ${d.total_completed ?? 0} completed according to the audit. ` : ""}
        Found ${c.courses} courses: ${c.passed} passed, ${c.in_progress} in progress, ${c.not_taken} not taken yet, ${c.not_counted} shaded "-" (not counted).</p>
      <div class="table-wrap"><table class="course-table">
        <thead><tr><th>Category</th><th>Credits needed</th><th>Listed</th><th>Courses</th><th>Passed credits</th></tr></thead>
        <tbody>${cats}</tbody>
      </table></div>
      <details><summary class="hint">Show all ${c.courses} courses the audit lists</summary>
        <div class="table-wrap"><table class="course-table">
          <thead><tr><th>Course</th><th>Category</th><th>Credits</th><th>Semester</th><th>Grade</th><th>Status</th></tr></thead>
          <tbody>${rows}</tbody>
        </table></div>
      </details>
      <div class="plan-pick">
        <button type="button" id="da-apply-btn">Replace my curriculum with this audit</button>
        <button type="button" id="da-cancel-btn" class="secondary">Cancel</button>
        <span id="da-apply-status" class="hint" role="status"></span>
      </div>`;
    document.getElementById("da-cancel-btn").addEventListener("click", () => { box.innerHTML = ""; });
    document.getElementById("da-apply-btn").addEventListener("click", apply);
  }

  async function apply() {
    const out = document.getElementById("da-apply-status");
    if (!confirm("Replace your curriculum with the one from this audit? Your passed courses, semesters and grades come from the audit.")) return;
    out.textContent = "Saving…";
    const fd = new FormData();
    fd.append("file", fileEl.files[0]);
    const res = await fetch("/api/degree-audit/apply", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) { out.textContent = data.error || "Something went wrong."; return; }
    box.innerHTML = "";
    fileEl.value = "";
    readBtn.disabled = true;
    statusEl.textContent = `Imported: ${data.courses} courses, ${data.completed} passed`
      + (data.in_progress ? `, ${data.in_progress} in progress` : "")
      + (data.gpa != null ? `. GPA now ${data.gpa.toFixed(2)}.` : ".");
    await loadCurriculum();
  }
})();
