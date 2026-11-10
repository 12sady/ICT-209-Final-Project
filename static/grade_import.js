// Curriculum page: import completed courses + grades from an AUPP grade report PDF.
// Uses escapeHtml / statusBadge / loadCurriculum from curriculum.js (loaded first).

(() => {
  const fileEl = document.getElementById("gr-file");
  const readBtn = document.getElementById("gr-read-btn");
  const statusEl = document.getElementById("gr-status");
  const box = document.getElementById("gr-preview");
  let rows = [];

  const STATUS = {
    completed: ["Passed", "ok"],
    in_progress: ["In progress (RG), skipped", "muted"],
    not_passed: ["Not passed, skipped", "warn"],
    unknown_grade: ["Unknown grade, skipped", "warn"],
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
      const res = await fetch("/api/grade-report/preview", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) { statusEl.textContent = data.error || "Couldn't read that file."; return; }
      rows = data.rows;
      render(data);
      statusEl.textContent = "";
    } catch (e) {
      statusEl.textContent = "Couldn't reach the app. Is it still running?";
    } finally {
      readBtn.disabled = !fileEl.files.length;
    }
  });

  function render(data) {
    const usable = rows.filter((r) => r.status === "completed");
    const extra = usable.filter((r) => !r.code).length;
    const g = data.gpa || {};
    let gpaLine = "";
    if (g.report != null && g.app != null) {
      gpaLine = g.differs
        ? `<p class="banner warn">Your report says cumulative GPA <strong>${g.report.toFixed(2)}</strong>, but after this import the app would calculate <strong>${g.app.toFixed(2)}</strong>. Check the rows below (a course left out, or a different credit value).</p>`
        : `<p class="hint">GPA check: report <strong>${g.report.toFixed(2)}</strong>, app after import <strong>${g.app.toFixed(2)}</strong>. They match.</p>`;
    }
    const warn = (data.warnings || []).length
      ? `<p class="banner warn">${data.warnings.map(escapeHtml).join("<br>")}</p>` : "";

    const body = rows.map((r, i) => {
      const [label, kind] = STATUS[r.status] || ["?", "muted"];
      const ok = r.status === "completed";
      let where;
      if (r.code && r.match === "exact") where = escapeHtml(r.code);
      else if (r.code) where = `${escapeHtml(r.code)} <span class="hint">(report says ${escapeHtml(r.report_code)})</span>`;
      else where = `<span class="hint">Not in your curriculum: will be added under "From grade report"</span>`;
      const change = r.already_completed
        ? (r.current_grade && r.current_grade !== r.grade ? `grade ${escapeHtml(r.current_grade)} → ${escapeHtml(r.grade)}` : "already completed")
        : (ok ? "new" : "");
      return `<tr>
        <td><input type="checkbox" data-i="${i}" ${ok ? "checked" : "disabled"} aria-label="Import ${escapeHtml(r.report_code)}"></td>
        <td>${escapeHtml(r.term)}</td>
        <td><strong>${escapeHtml(r.report_code)}</strong>${r.repeated ? " *" : ""}<br><span class="hint">${escapeHtml(r.name)}</span></td>
        <td>${where}</td>
        <td>${r.credits}</td>
        <td><strong>${escapeHtml(r.grade)}</strong></td>
        <td>${statusBadge(label, kind)}</td>
        <td class="hint">${change}</td>
      </tr>`;
    }).join("");

    box.innerHTML = `
      ${warn}${gpaLine}
      <p class="hint">Found ${rows.length} courses: ${usable.length} passed${extra ? `, ${extra} not in your curriculum yet` : ""}. Untick anything you don't want, then press Import.</p>
      <div class="table-wrap"><table class="course-table">
        <thead><tr><th></th><th>Term</th><th>On report</th><th>In your curriculum</th><th>Credits</th><th>Grade</th><th>Status</th><th>Change</th></tr></thead>
        <tbody>${body}</tbody>
      </table></div>
      <div class="plan-pick">
        <button type="button" id="gr-apply-btn">Import ticked courses</button>
        <button type="button" id="gr-cancel-btn" class="secondary">Cancel</button>
        <span id="gr-apply-status" class="hint" role="status"></span>
      </div>`;
    document.getElementById("gr-cancel-btn").addEventListener("click", () => { box.innerHTML = ""; });
    document.getElementById("gr-apply-btn").addEventListener("click", apply);
  }

  async function apply() {
    const out = document.getElementById("gr-apply-status");
    const picked = [...box.querySelectorAll("input[type=checkbox][data-i]:checked")].map((cb) => {
      const r = rows[Number(cb.dataset.i)];
      return {
        code: r.code || r.report_code, grade: r.grade, term: r.term,
        add: r.code ? null : { name: r.name, credits: r.credits },
      };
    });
    if (!picked.length) { out.textContent = "Tick at least one course."; return; }
    if (!(await askConfirm(`Mark ${picked.length} course${picked.length === 1 ? "" : "s"} completed and save their grades?`, "Import"))) return;
    out.textContent = "Saving…";
    const res = await fetch("/api/grade-report/apply", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ courses: picked, in_progress: rows.filter((r) => r.status === "in_progress" && r.code).map((r) => r.code) }),
    });
    const data = await res.json();
    if (!res.ok) { out.textContent = data.error || "Something went wrong."; return; }
    box.innerHTML = "";
    fileEl.value = "";
    readBtn.disabled = true;
    statusEl.textContent = `Imported: ${data.newly_completed} newly completed, ${data.grades_set} grades saved`
      + (data.added_to_curriculum ? `, ${data.added_to_curriculum} added to your curriculum` : "")
      + (data.gpa != null ? `. GPA now ${data.gpa.toFixed(2)}.` : ".");
    await loadCurriculum();
  }
})();
