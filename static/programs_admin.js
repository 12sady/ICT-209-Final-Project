// Admin editor for the shared sample course plans (Import page).
(function () {
  const $ = (id) => document.getElementById(id);
  const CATS = ["General Education", "Major", "Elective", "Dual Degree"];
  const TERMS = ["Fall", "Spring", "Summer"];
  let canEdit = false;
  let current = null; // the program object being edited (client copy)

  function esc(str) {
    return String(str == null ? "" : str).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  async function loadList(selectId) {
    const data = await (await fetch("/api/programs")).json();
    canEdit = !!data.can_edit;
    const sel = $("pe-select");
    sel.innerHTML = '<option value="">Choose a plan to edit…</option>' +
      data.programs.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}${p.degree ? " (" + p.degree + ")" : ""}</option>`).join("");
    if (selectId) sel.value = selectId;
    $("pe-readonly").hidden = canEdit;
    ["pe-new-btn", "pe-dup-btn", "pe-del-btn", "pe-save-btn", "pe-add-term"].forEach((id) => { $(id).disabled = !canEdit; });
    await openSelected();
  }

  async function openSelected() {
    const id = $("pe-select").value;
    if (!id) { current = null; $("pe-editor").hidden = true; return; }
    const data = await (await fetch(`/api/programs/${encodeURIComponent(id)}`)).json();
    current = data.program;
    render();
  }

  function render() {
    $("pe-editor").hidden = !current;
    if (!current) return;
    $("pe-name").value = current.name || "";
    $("pe-degree").value = current.degree || "";
    $("pe-total").value = current.credit_total ?? "";
    $("pe-electives").value = (current.electives || [])
      .map((e) => `${e.code} | ${e.title || ""} | ${(e.prereqs || []).join(", ")}`).join("\n");
    renderTerms();
    ["pe-name", "pe-degree", "pe-total", "pe-electives"].forEach((id) => { $(id).disabled = !canEdit; });
  }

  function termBlock(t, ti) {
    const div = document.createElement("div");
    div.className = "pe-term";
    const credits = t.courses.reduce((a, c) => a + (Number(c.credits) || 0), 0);
    div.innerHTML = `
      <div class="pe-term-head">
        <strong>Year</strong> <select class="pe-year">${[1, 2, 3, 4, 5, 6].map((y) => `<option ${y === t.year ? "selected" : ""}>${y}</option>`).join("")}</select>
        <select class="pe-term">${TERMS.map((n) => `<option ${n === t.term ? "selected" : ""}>${n}</option>`).join("")}</select>
        <span class="hint" style="margin:0;">${credits} credits</span>
        <button class="secondary pe-rm-term" type="button">Remove semester</button>
      </div>
      <table class="pe-table"><thead><tr><th>Code</th><th>Title</th><th>Credits</th><th>Category</th><th>Prerequisites</th><th></th></tr></thead><tbody></tbody></table>
      <button class="secondary pe-add-course" type="button" style="margin-top:var(--sp-2);">+ Add a course</button>`;
    const tbody = div.querySelector("tbody");
    t.courses.forEach((c, ci) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><input class="pe-code" type="text" value="${esc(c.code || "")}" placeholder="(slot)" /></td>
        <td><input type="text" class="pe-title" value="${esc(c.title || "")}" /></td>
        <td><input class="pe-cr" type="number" min="0" step="0.5" value="${esc(c.credits)}" /></td>
        <td><select class="pe-cat">${CATS.map((k) => `<option ${k === c.category ? "selected" : ""}>${k}</option>`).join("")}</select></td>
        <td><input type="text" class="pe-pre" value="${esc((c.prereqs || []).join(", "))}" /></td>
        <td><button class="secondary pe-rm" type="button" title="Remove this course">×</button></td>`;
      tr.querySelector(".pe-code").oninput = (e) => { c.code = e.target.value; };
      tr.querySelector(".pe-title").oninput = (e) => { c.title = e.target.value; };
      tr.querySelector(".pe-cr").oninput = (e) => { c.credits = e.target.value; };
      tr.querySelector(".pe-cat").onchange = (e) => { c.category = e.target.value; };
      tr.querySelector(".pe-pre").oninput = (e) => { c.prereqs = e.target.value; };
      tr.querySelector(".pe-rm").onclick = () => { t.courses.splice(ci, 1); renderTerms(); };
      tbody.appendChild(tr);
    });
    div.querySelector(".pe-year").onchange = (e) => { t.year = Number(e.target.value); };
    div.querySelector(".pe-term").onchange = (e) => { t.term = e.target.value; };
    div.querySelector(".pe-rm-term").onclick = () => { current.terms.splice(ti, 1); renderTerms(); };
    div.querySelector(".pe-add-course").onclick = () => {
      t.courses.push({ code: "", title: "", credits: 3, category: "Major", prereqs: "" });
      renderTerms();
    };
    if (!canEdit) div.querySelectorAll("input, select, button").forEach((el) => { el.disabled = true; });
    return div;
  }

  function renderTerms() {
    const wrap = $("pe-terms");
    wrap.innerHTML = "";
    current.terms.forEach((t, ti) => wrap.appendChild(termBlock(t, ti)));
  }

  function collect() {
    const electives = $("pe-electives").value.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
      const [code, title, pre] = line.split("|").map((x) => (x || "").trim());
      return { code, title, prereqs: pre || "" };
    });
    return {
      name: $("pe-name").value,
      degree: $("pe-degree").value,
      credit_total: $("pe-total").value,
      terms: current.terms.map((t) => ({
        year: t.year, term: t.term,
        courses: t.courses.map((c) => ({
          code: c.code, title: c.title, credits: c.credits, category: c.category,
          prereqs: c.prereqs, taught_by: c.taught_by,
        })),
      })),
      electives,
      note: current.note || "",
    };
  }

  $("pe-select").addEventListener("change", openSelected);

  $("pe-add-term").addEventListener("click", () => {
    const last = current.terms[current.terms.length - 1];
    current.terms.push({ year: last ? last.year : 1, term: "Fall", courses: [{ code: "", title: "", credits: 3, category: "Major", prereqs: "" }] });
    renderTerms();
  });

  $("pe-save-btn").addEventListener("click", async () => {
    const status = $("pe-status");
    status.textContent = "Saving…";
    const res = await fetch(`/api/programs/${encodeURIComponent(current.id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collect()),
    });
    const data = await res.json();
    if (!res.ok) { status.textContent = data.error || "Couldn't save."; return; }
    status.textContent = "Saved. Students who pick this plan from now on get these courses.";
    await loadList(current.id);
  });

  async function createFrom(payload, okText) {
    const res = await fetch("/api/programs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await res.json();
    if (!res.ok) { $("pe-status").textContent = data.error || "Couldn't create."; return; }
    await loadList(data.program.id);
    $("pe-status").textContent = okText;
  }

  $("pe-new-btn").addEventListener("click", () => {
    const name = prompt("Name of the new plan (e.g. Data Science):");
    if (!name || !name.trim()) return;
    createFrom({ name: name.trim(), degree: "Single", credit_total: 120, terms: [{ year: 1, term: "Fall", courses: [] }] }, "Created. Add semesters and courses, then Save plan.");
  });

  $("pe-dup-btn").addEventListener("click", () => {
    if (!current) return;
    const payload = collect();
    payload.name = payload.name + " (copy)";
    createFrom(payload, "Duplicated — this is the copy.");
  });

  $("pe-del-btn").addEventListener("click", async () => {
    if (!current) return;
    if (!confirm(`Delete the "${current.name}" plan? Students who already started from it keep their own copy.`)) return;
    const res = await fetch(`/api/programs/${encodeURIComponent(current.id)}`, { method: "DELETE" });
    if (res.ok) { current = null; await loadList(""); $("pe-status").textContent = "Deleted."; }
  });

  loadList("");
})();
