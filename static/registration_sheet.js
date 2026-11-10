// Registration-day sheet: renders /api/registration-sheet; the print button uses the browser's print dialog.
const $ = (id) => document.getElementById(id);
const crd = (x) => (Math.round(Number(x) * 10) / 10).toString();
const RISK = { low: "Plenty of seats", medium: "Medium", "fills fast": "Fills fast", full: "Full", unknown: "No seat data" };

function render(d) {
  const cd = $("sheet-countdown");
  if (d.countdown) {
    cd.hidden = false;
    cd.className = `countdown countdown-${d.countdown.state}`;
    cd.innerHTML = `<span class="countdown-num">${d.countdown.state === "future" ? d.countdown.days : d.countdown.state === "today" ? "Today" : "✓"}</span><span>${escapeHtml(d.countdown.label)}</span>`;
    $("sheet-countdown-print").textContent = d.countdown.label;
  } else {
    cd.hidden = false;
    cd.className = "countdown countdown-none";
    cd.textContent = "No registration date is set. The admin can add one under Academic calendar on the Admin page and a countdown will appear here.";
    $("sheet-countdown-print").textContent = "";
  }

  if (!d.plan) {
    $("sheet").hidden = true; $("sheet-print").hidden = true; $("sheet-empty").hidden = false;
    $("sheet-empty-title").textContent = d.missing ? "Your active plan's sections aren't offered any more." : "You haven't chosen an active plan yet.";
    $("sheet-empty-body").innerHTML = `Open the <a href="/plan">Plan</a> page and press “Make this my active plan” (or do it from <a href="/compare">Compare</a>), then come back for your sheet.`;
    return;
  }
  $("sheet-empty").hidden = true; $("sheet").hidden = false; $("sheet-print").hidden = false;
  $("sheet-sub").textContent = [d.student, d.program, d.term, `printed ${d.generated}`].filter(Boolean).join(" · ");
  $("sheet-total").innerHTML = `<strong>${crd(d.plan.total_credits)}</strong> credits<br>${d.plan.rows.length} courses`;

  let html = `<thead><tr><th class="tick"></th><th>Course</th><th>Sec</th><th>When</th><th>Room</th><th>Instructor</th><th class="num">Cr</th><th>Seats</th></tr></thead><tbody>`;
  d.plan.rows.forEach((r) => {
    html += `<tr class="main"><td class="tick"><span class="box" aria-label="Registered"></span></td>
      <td><strong>${escapeHtml(r.code)}</strong><div class="sub">${escapeHtml(r.title)}</div></td>
      <td class="nw big">${escapeHtml(r.section)}</td><td class="nw">${escapeHtml(r.when)}</td><td>${escapeHtml(r.room || "—")}</td>
      <td>${escapeHtml(r.instructor || "—")}</td><td class="num">${escapeHtml(r.credits ?? "")}</td><td class="nw">${escapeHtml(RISK[r.risk] || r.risk)}</td></tr>`;
    html += `<tr class="backup"><td></td><td colspan="7">${r.backups.length
      ? `Backup if full: ` + r.backups.map((b) => `<strong>section ${escapeHtml(b.section)}</strong> (${escapeHtml(b.when)}${b.room ? ", " + escapeHtml(b.room) : ""})`).join("; ")
      : `<span class="sub">No other section fits around the rest of this plan.</span>`}</td></tr>`;
  });
  $("sheet-table").innerHTML = html + "</tbody>";
  $("sheet-tt").innerHTML = timetableHtml(d.plan.sections, { compact: true, legend: true });
  $("sheet-missing").textContent = d.plan.missing.length ? `No longer offered, left off this sheet: ${d.plan.missing.join(", ")}.` : "";
}

$("sheet-print").addEventListener("click", () => window.print());
(async () => { render(await (await fetch("/api/registration-sheet")).json()); })();
