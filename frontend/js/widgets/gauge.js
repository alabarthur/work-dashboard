// Workday time-remaining gauge: a ring that fills as the day elapses, with the
// remaining time live-counted from the client clock and a color that warms
// (teal -> amber -> red) as the day drains.

let workday = null;

function fmt(mins) {
  if (mins <= 0) return "0m";
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

function fmtClock(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function compute(now) {
  const start = new Date(workday.start_at).getTime();
  const end = new Date(workday.end_at).getTime();
  const total = workday.minutes_total;
  const t = now.getTime();
  let remaining;
  if (t <= start) remaining = total;
  else if (t >= end) remaining = 0;
  else remaining = Math.round((end - t) / 60000);
  const elapsedPct = total > 0 ? (1 - remaining / total) * 100 : 100;
  return { remaining, elapsedPct: Math.max(0, Math.min(100, elapsedPct)) };
}

function color(remaining, total) {
  const frac = total > 0 ? remaining / total : 0;
  if (frac > 0.5) return "var(--teal)";
  if (frac > 0.2) return "var(--amber)";
  return "var(--red)";
}

export function render(data) {
  workday = data.workday;
  draw();
}

export function tick() {
  if (workday) draw();
}

function draw() {
  const el = document.getElementById("gauge");
  if (!workday) {
    el.innerHTML = '<p class="skeleton">No workday data.</p>';
    return;
  }
  const now = new Date();
  const { remaining, elapsedPct } = compute(now);
  const stroke = color(remaining, workday.minutes_total);
  const r = 84;
  const c = 2 * Math.PI * r;

  el.innerHTML = `
    <svg viewBox="0 0 200 200" role="img" aria-label="workday remaining">
      <circle cx="100" cy="100" r="${r}" fill="none" stroke="var(--line)" stroke-width="12" opacity="0.6"/>
      <circle cx="100" cy="100" r="${r}" fill="none" stroke="${stroke}" stroke-width="12"
        stroke-linecap="round" transform="rotate(-90 100 100)"
        stroke-dasharray="${(elapsedPct / 100) * c} ${c}"
        style="transition: stroke-dasharray 0.8s cubic-bezier(0.2,0.7,0.2,1), stroke 0.6s ease;"/>
      <text class="g-remaining" x="100" y="98" text-anchor="middle" dominant-baseline="middle">${fmt(remaining)}</text>
      <text class="g-label" x="100" y="126" text-anchor="middle">remaining</text>
    </svg>
    <div class="gauge-foot">
      <span>start <b>${fmtClock(workday.start_at)}</b></span>
      <span>end <b>${fmtClock(workday.end_at)}</b></span>
      <span><b>${Math.round(elapsedPct)}%</b> elapsed</span>
    </div>`;
}
