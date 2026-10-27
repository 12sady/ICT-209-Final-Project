// Escapes text for safe use inside innerHTML.
function escapeHtml(str) {
  return String(str == null ? "" : str).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// Shared across every page (loaded from base.html) -- keeps a small,
// always-visible status strip in sync so it's never a mystery what data
// the app currently has loaded, without having to click into each page.
(async function () {
  const el = document.getElementById("status-strip");
  if (!el) return;

  try {
    const [coursesRes, curriculumRes, wishlistRes] = await Promise.all([
      fetch("/api/courses"),
      fetch("/api/curriculum"),
      fetch("/api/wishlist"),
    ]);
    const courses = await coursesRes.json();
    const curriculum = await curriculumRes.json();
    const wishlist = await wishlistRes.json();

    const courseCount = (courses.courses || []).length;
    const requiredCount = (curriculum.required_remaining || []).length;
    const wishlistCount = (wishlist.wishlist || []).length;
    const program = curriculum.program || "";

    if (!courseCount && !requiredCount) {
      el.innerHTML = `<span class="empty">No data loaded yet — head to <a href="/import" style="color:inherit;font-weight:700;">Import</a> to bring in your curriculum and this term's courses.</span>`;
      return;
    }

    const parts = [];
    if (program) parts.push(`<span>${program}</span>`);
    parts.push(`<span><strong>${courseCount}</strong> course section${courseCount === 1 ? "" : "s"} loaded</span>`);
    parts.push(`<span><strong>${requiredCount}</strong> required course${requiredCount === 1 ? "" : "s"} remaining</span>`);
    parts.push(`<span><strong>${wishlistCount}</strong> on wishlist</span>`);
    el.innerHTML = parts.join("<span style=\"opacity:0.4\">·</span>");
  } catch (e) {
    el.innerHTML = `<span class="empty">Couldn't load status.</span>`;
  }
})();


// ---------------------------------------------------------------------------
// Weekly timetable (days as columns, time as rows) drawn from section dicts.
// Used by the Plan page and the Compare page. Two sections at the same time
// are drawn side by side and outlined red instead of hiding one.
// ---------------------------------------------------------------------------
const TT_COLORS = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"];
const TT_ALL_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function _ttMinutes(hhmm) {
  const [h, m] = String(hhmm).split(":").map(Number);
  return h * 60 + m;
}

function timetableHtml(sections, opts) {
  const o = Object.assign({ compact: false, minHour: 8, maxHour: 18 }, opts || {});
  const timed = (sections || []).filter((s) => s.start && s.end && (s.days || []).length && !s.online);
  const online = (sections || []).filter((s) => !timed.includes(s));
  const days = TT_ALL_DAYS.filter((d, i) => i < 5 || timed.some((s) => s.days.includes(d)));
  let lo = o.minHour, hi = o.maxHour;
  timed.forEach((s) => {
    lo = Math.min(lo, Math.floor(_ttMinutes(s.start) / 60));
    hi = Math.max(hi, Math.ceil(_ttMinutes(s.end) / 60));
  });
  const hours = hi - lo, span = hours * 60;
  const codes = [...new Set((sections || []).map((s) => s.code))];

  const cols = days.map((day) => {
    const items = timed.filter((s) => s.days.includes(day))
      .map((s) => ({ s, a: _ttMinutes(s.start), b: _ttMinutes(s.end) })).sort((x, y) => x.a - y.a || x.b - y.b);
    // Group transitively-overlapping meetings into clusters, then give each a lane.
    const clusters = [];
    items.forEach((it) => {
      const last = clusters[clusters.length - 1];
      if (last && it.a < last.end) { last.items.push(it); last.end = Math.max(last.end, it.b); }
      else clusters.push({ items: [it], end: it.b });
    });
    let html = "";
    clusters.forEach((cl) => {
      const laneEnds = [];
      cl.items.forEach((it) => {
        let lane = laneEnds.findIndex((e) => e <= it.a);
        if (lane === -1) { lane = laneEnds.length; laneEnds.push(0); }
        laneEnds[lane] = it.b;
        it.lane = lane;
      });
      const n = laneEnds.length;
      cl.items.forEach((it) => {
        const s = it.s;
        const top = ((it.a - lo * 60) / span) * 100, height = ((it.b - it.a) / span) * 100;
        const tip = `${s.code}-${s.section} ${s.title || ""}\n${s.start}-${s.end}` + (s.location ? `\nRoom: ${s.location}` : "") + (s.instructor ? `\n${s.instructor}` : "");
        const meta = o.compact ? "" : `<span class="tt-meta">${escapeHtml(s.start)}–${escapeHtml(s.end)}</span>` + (s.location ? `<span class="tt-meta">${escapeHtml(s.location)}</span>` : "");
        html += `<div class="tt-block${n > 1 ? " tt-clash" : ""}" title="${escapeHtml(tip)}" style="top:${top}%;height:${height}%;left:${(it.lane / n) * 100}%;width:${100 / n}%;background:var(--${TT_COLORS[codes.indexOf(s.code) % TT_COLORS.length]})">` +
          `<span class="tt-code">${escapeHtml(s.code)}${o.compact ? "" : "-" + escapeHtml(s.section)}</span>${meta}</div>`;
      });
    });
    return `<div class="tt-day">${html}</div>`;
  }).join("");

  let times = "";
  for (let h = lo; h <= hi; h++) {
    if (h === lo || (o.compact && (h - lo) % 2) || h === hi) continue;
    times += `<span style="top:${((h - lo) / hours) * 100}%">${h}:00</span>`;
  }
  const onlineNote = online.length
    ? `<p class="tt-online">Online / no fixed time: ${online.map((s) => escapeHtml(`${s.code}-${s.section}`)).join(", ")}</p>` : "";
  return `<div class="tt${o.compact ? " tt-compact" : ""}" style="--days:${days.length};--hours:${hours}">` +
    `<div class="tt-head"><span></span>${days.map((d) => `<span>${d}</span>`).join("")}</div>` +
    `<div class="tt-body"><div class="tt-times">${times}</div>${cols}</div></div>${onlineNote}`;
}

// ---------------------------------------------------------------------------
// Calendar (.ics) download for a list of sections. Returns a sentence saying
// what was exported; throws an Error with a readable message on failure.
// ---------------------------------------------------------------------------
function describeIcsExport(info) {
  const n = info.exported || 0;
  let msg = `Downloaded — ${n} repeating class${n === 1 ? "" : "es"}, one per course (not one event per day).`;
  const src = info.dates_from || {};
  if (src.none) {
    msg += ` ${src.none} had no known term dates, so ${src.none === 1 ? "it repeats" : "they repeat"} for 15 weeks from the next class day.`;
  }
  if (info.breaks) msg += ` ${info.breaks} break${info.breaks === 1 ? "" : "s"} skipped.`;
  if (info.skipped && info.skipped.length) {
    msg += ` Not included (no fixed meeting time): ${info.skipped.join(", ")}.`;
  }
  return msg;
}

async function downloadPlanIcs(plan, label) {
  let res;
  try {
    res = await fetch("/api/plan/export/ics", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({}, plan, { label })),
    });
  } catch (e) {
    throw new Error(`Couldn't reach the server: ${e}`);
  }
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).error || ""; } catch (e) { detail = await res.text().catch(() => ""); }
    throw new Error(`Export failed (${res.status})${detail ? ": " + detail : ". Check the terminal running the app for the error."}`);
  }
  let info = {};
  try { info = JSON.parse(res.headers.get("X-Export-Info") || "{}"); } catch (e) { /* header is optional */ }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `registration_plan_${label}.ics`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return describeIcsExport(info);
}

function planKeyOf(sections) {
  return sections.map((s) => `${s.code}-${s.section}`).sort().join("|");
}


// Mobile navigation: the Menu button shows/hides the links below 960px.
(function () {
  const btn = document.getElementById("nav-toggle"), links = document.getElementById("nav-links");
  if (!btn || !links) return;
  btn.addEventListener("click", () => {
    const open = links.classList.toggle("open");
    btn.setAttribute("aria-expanded", String(open));
  });
})();
