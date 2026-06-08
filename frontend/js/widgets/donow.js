// Ranked list. Two modes:
//   "now" — the top-N actionable items (default view)
//   "all" — every ranked item, grouped by tier, for verifying prioritization.

const SRC_LABEL = {
  teams: "Teams",
  outlook_email: "Email",
  calendar: "Calendar",
  notion: "Notion",
};

const TIER_LABEL = { now: "Now", soon: "Soon", later: "Later" };

function escapeHtml(s) {
  return (s || "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
  );
}

// Only allow http(s) links — the URL comes from the AI collector, so guard
// against javascript:/data: schemes that escapeHtml would let through.
function isSafeUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:";
  } catch {
    return false;
  }
}

const DEFAULT_STEP = 10; // fallback manual-priority step if rules unavailable

function itemHtml(it, rank, step) {
  const safe = it.url && isSafeUrl(it.url);
  const tag = safe ? "a" : "div";
  const href = safe ? ` href="${escapeHtml(it.url)}" target="_blank" rel="noopener"` : "";
  const rankCell = rank == null ? "" : `<span class="item-rank">${rank}</span>`;
  const id = escapeHtml(it.id);
  const manual = (it.factors && it.factors.manual) || 0;
  const reset = manual
    ? `<button class="ctrl-reset" data-bump="${id}" data-delta="${-manual}" title="reset manual priority (${manual > 0 ? "+" : ""}${manual})">↺</button>`
    : "";
  return `
    <li>
      <div class="item item--${it.tier}">
        ${rankCell}
        <${tag}${href} class="item-main">
          <div class="item-title">${escapeHtml(it.title)}</div>
          <div class="item-why"><span class="item-src">${SRC_LABEL[it.source] || it.source}</span>${escapeHtml(it.why)}</div>
        </${tag}>
        <span class="item-score">${it.score}</span>
        <span class="item-ctrl">
          <button class="ctrl-up" data-bump="${id}" data-delta="${step}" title="raise priority (+${step})">▲</button>
          ${reset}
          <button class="ctrl-dn" data-bump="${id}" data-delta="${-step}" title="lower priority (-${step})">▼</button>
        </span>
      </div>
    </li>`;
}

export function render(data, mode = "now", step = DEFAULT_STEP) {
  const list = document.getElementById("donow");
  const countEl = document.getElementById("donow-count");
  const all = data.ranked || [];

  if (!all.length) {
    countEl.textContent = "0";
    list.innerHTML = '<li class="skeleton">Nothing queued — enjoy the quiet.</li>';
    return;
  }

  if (mode === "all") {
    countEl.textContent = `${all.length}`;
    const groups = { now: [], soon: [], later: [] };
    all.forEach((it) => (groups[it.tier] || groups.later).push(it));
    let html = "";
    for (const tier of ["now", "soon", "later"]) {
      const items = groups[tier];
      if (!items.length) continue;
      html += `<div class="tier-head tier-head--${tier}"><span class="dot"></span>${TIER_LABEL[tier]} · ${items.length}</div>`;
      html += items.map((it) => itemHtml(it, null, step)).join("");
    }
    list.innerHTML = html;
    return;
  }

  // "now" mode — top-N with ranks.
  const limit = data.do_now_limit || 12;
  const items = all.slice(0, limit);
  countEl.textContent = `${items.length} / ${all.length}`;
  list.innerHTML = items.map((it, i) => itemHtml(it, i + 1, step)).join("");
}
