// Workload breakdown: items by source, by priority tier, and task due/overdue stats.

const SRC_LABEL = { teams: "Teams", outlook_email: "Email", calendar: "Calendar", notion: "Notion", tfs: "TFS" };
const TIER_COLOR = { now: "var(--tier-now)", soon: "var(--tier-soon)", later: "var(--tier-later)" };

function bars(entries, max, colorFor) {
  return entries
    .map(([label, val]) => {
      const pct = max > 0 ? (val / max) * 100 : 0;
      return `
      <div class="bd-row">
        <span class="bd-row-label">${label}</span>
        <span class="bd-bar-track"><span class="bd-bar" style="width:${pct}%;background:${colorFor(label)}"></span></span>
        <span class="bd-row-val">${val}</span>
      </div>`;
    })
    .join("");
}

function sparkline(history) {
  const pts = (history || []).filter((h) => Number.isFinite(h.now));
  if (pts.length < 2) {
    return '<div class="bd-block"><h3>Trend</h3><p class="item-why">Builds up as data is collected over time.</p></div>';
  }
  const W = 200, H = 54, pad = 4;
  const vals = pts.map((p) => p.now + p.soon);
  const max = Math.max(1, ...vals);
  const step = (W - pad * 2) / (vals.length - 1);
  const y = (v) => H - pad - (v / max) * (H - pad * 2);
  const line = vals.map((v, i) => `${pad + i * step},${y(v)}`).join(" ");
  const area = `${pad},${H - pad} ${line} ${pad + (vals.length - 1) * step},${H - pad}`;
  return `
    <div class="bd-block">
      <h3>Active items over time</h3>
      <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:54px">
        <polygon points="${area}" fill="rgba(243,162,58,0.12)"/>
        <polyline points="${line}" fill="none" stroke="var(--amber)" stroke-width="2" stroke-linejoin="round"/>
        <circle cx="${pad + (vals.length - 1) * step}" cy="${y(vals[vals.length - 1])}" r="3" fill="var(--amber)"/>
      </svg>
    </div>`;
}

function fmtTokens(n) {
  return n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n || 0);
}
function fmtCost(c) {
  c = c || 0;
  return "$" + (c >= 0.1 ? c.toFixed(2) : c.toFixed(3));
}

function collectorBlock(data, history) {
  const u = data.usage || {};
  const today = new Date().toDateString();
  let dayCost = 0, dayRuns = 0;
  (history || []).forEach((h) => {
    if (h.ts && new Date(h.ts).toDateString() === today && (h.cost_usd || h.total_tokens)) {
      dayCost += h.cost_usd || 0;
      dayRuns += 1;
    }
  });
  return `
    <div class="bd-block">
      <h3>Collector cost</h3>
      <div class="bd-stats">
        <div class="bd-stat">
          <div class="bd-stat-num">${fmtCost(u.cost_usd)}</div>
          <div class="bd-stat-label">this run · ${fmtTokens(u.total_tokens)} tok</div>
        </div>
        <div class="bd-stat">
          <div class="bd-stat-num">${fmtCost(dayCost)}</div>
          <div class="bd-stat-label">today · ${dayRuns} run${dayRuns === 1 ? "" : "s"}</div>
        </div>
      </div>
    </div>`;
}

export function render(data, history) {
  const el = document.getElementById("breakdown");
  const bd = data.breakdown || {};
  const bySource = Object.entries(bd.by_source || {}).map(([k, v]) => [SRC_LABEL[k] || k, v]);
  const maxSource = Math.max(1, ...bySource.map(([, v]) => v));

  const tierOrder = ["now", "soon", "later"];
  const byTier = tierOrder.map((t) => [t, (bd.by_tier || {})[t] || 0]);
  const maxTier = Math.max(1, ...byTier.map(([, v]) => v));

  const tasks = bd.tasks || { due_today: 0, overdue: 0 };

  el.innerHTML = `
    <div class="bd-block">
      <h3>By source</h3>
      ${bars(bySource, maxSource, () => "var(--amber)")}
    </div>
    <div class="bd-block">
      <h3>By priority</h3>
      ${bars(byTier, maxTier, (l) => TIER_COLOR[l] || "var(--amber)")}
    </div>
    <div class="bd-block">
      <h3>Tasks</h3>
      <div class="bd-stats">
        <div class="bd-stat">
          <div class="bd-stat-num">${tasks.due_today}</div>
          <div class="bd-stat-label">due today</div>
        </div>
        <div class="bd-stat">
          <div class="bd-stat-num ${tasks.overdue > 0 ? "is-alert" : ""}">${tasks.overdue}</div>
          <div class="bd-stat-label">overdue</div>
        </div>
      </div>
    </div>
    ${collectorBlock(data, history)}
    ${sparkline(history)}`;
}
