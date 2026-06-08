// Today's schedule: a horizontal band across the workday with meeting blocks,
// free gaps and a live "now" marker.

let state = null;

function fmtClock(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function render(data) {
  state = { workday: data.workday, meetings: data.meetings || [], gaps: data.gaps || [] };
  draw();
}

export function tick() {
  if (state) draw();
}

function draw() {
  const el = document.getElementById("timeline");
  const { workday, meetings, gaps } = state;
  const start = new Date(workday.start_at).getTime();
  const end = new Date(workday.end_at).getTime();
  const span = end - start;
  if (span <= 0) {
    el.innerHTML = '<p class="skeleton">No workday window.</p>';
    return;
  }

  const W = 1000, padX = 14, innerW = W - padX * 2;
  const bandY = 60, bandH = 70, H = bandY + bandH + 30;
  const x = (t) => padX + ((t - start) / span) * innerW;

  const hourTicks = [];
  const first = new Date(start);
  first.setMinutes(0, 0, 0);
  for (let h = new Date(first).getTime(); h <= end; h += 3600000) {
    if (h < start) continue;
    hourTicks.push(
      `<line x1="${x(h)}" y1="${bandY}" x2="${x(h)}" y2="${bandY + bandH}" stroke="var(--line)" stroke-width="1"/>` +
      `<text class="tl-hour" x="${x(h)}" y="${bandY + bandH + 20}" text-anchor="middle">${new Date(h).getHours()}:00</text>`
    );
  }

  const gapRects = gaps
    .map((g) => {
      const gx = x(new Date(g.start).getTime());
      const gw = x(new Date(g.end).getTime()) - gx;
      return `<rect class="tl-gap" x="${gx}" y="${bandY}" width="${Math.max(0, gw)}" height="${bandH}" rx="5"/>`;
    })
    .join("");

  const meetingRects = meetings
    .filter((m) => m.end)
    .map((m) => {
      const ms = new Date(m.start).getTime();
      const me = new Date(m.end).getTime();
      const mx = x(ms);
      const mw = Math.max(7, x(me) - mx);
      const cls = m.is_now ? "tl-meeting tl-meeting--now" : "tl-meeting";
      let labels = "";
      if (mw > 60) {
        const title = escapeHtml(trunc(m.title, Math.floor(mw / 7)));
        labels =
          `<text class="tl-label" x="${mx + 8}" y="${bandY + 28}">${title}</text>` +
          `<text class="tl-time" x="${mx + 8}" y="${bandY + 48}">${fmtClock(m.start)}–${fmtClock(m.end)}</text>`;
      }
      const block =
        `<rect class="${cls}" x="${mx}" y="${bandY}" width="${mw}" height="${bandH}" rx="7">` +
        `<title>${escapeHtml(m.title)} · ${fmtClock(m.start)}–${fmtClock(m.end)}</title></rect>${labels}`;
      // Clickable when the event has a usable link.
      return isSafeUrl(m.url)
        ? `<a href="${escapeHtml(m.url)}" target="_blank" rel="noopener" class="tl-link">${block}</a>`
        : `<g>${block}</g>`;
    })
    .join("");

  const now = Date.now();
  let nowMarker = "";
  if (now >= start && now <= end) {
    const nx = x(now);
    nowMarker = `<line class="tl-now" x1="${nx}" y1="${bandY - 10}" x2="${nx}" y2="${bandY + bandH + 10}"/>` +
      `<circle class="tl-now-dot" cx="${nx}" cy="${bandY - 10}" r="5"/>`;
  }

  const next = meetings.find((m) => m.minutes_until >= 0);
  const caption = next
    ? `Next: <b>${escapeHtml(next.title)}</b> in ${next.minutes_until}m`
    : meetings.length
    ? "No more meetings today."
    : "No meetings today.";

  // A clickable list of every meeting — readable even for tiny timeline blocks.
  const list = meetings
    .map((m) => {
      const safe = isSafeUrl(m.url);
      const tag = safe ? "a" : "span";
      const attrs = safe ? ` href="${escapeHtml(m.url)}" target="_blank" rel="noopener"` : "";
      const cls = "tl-item" + (m.is_now ? " tl-item--now" : "");
      const time = m.end ? `${fmtClock(m.start)}–${fmtClock(m.end)}` : fmtClock(m.start);
      return `<${tag}${attrs} class="${cls}"><span class="tl-item-time">${time}</span><span class="tl-item-title">${escapeHtml(m.title)}</span></${tag}>`;
    })
    .join("");

  el.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}">
      <rect class="tl-track" x="${padX}" y="${bandY}" width="${innerW}" height="${bandH}" rx="8"/>
      ${gapRects}${hourTicks.join("")}${meetingRects}${nowMarker}
    </svg>
    <p class="item-why" style="margin:12px 0 10px">${caption}</p>
    <div class="tl-list">${list}</div>`;
}

function isSafeUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:";
  } catch {
    return false;
  }
}

function trunc(s, n) {
  s = s || "";
  return s.length > n ? s.slice(0, Math.max(1, n - 1)) + "…" : s;
}
function escapeHtml(s) {
  return (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
