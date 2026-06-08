// Orchestrator: fetches data + rules, renders widgets, runs the live clock,
// computes the staleness badge, and wires the refresh button and rules drawer.

import * as gauge from "./widgets/gauge.js";
import * as donow from "./widgets/donow.js";
import * as timeline from "./widgets/timeline.js";
import * as breakdown from "./widgets/breakdown.js";
import * as rulesPanel from "./widgets/rules_panel.js";

const POLL_MS = 60_000;
const DEFAULT_RECONNECT_URL = "https://claude.ai/settings/connectors";
const CONNECTOR = { calendar: "Microsoft 365", email: "Microsoft 365", teams: "Microsoft 365", notion: "Notion" };
let latest = null;
let currentRules = null;
let donowMode = "now"; // "now" (top-N) | "all" (full ranked, grouped)

async function loadData() {
  try {
    const [dataR, histR] = await Promise.all([
      fetch("/api/data", { cache: "no-store" }),
      fetch("/api/history", { cache: "no-store" }),
    ]);
    latest = await dataR.json();
    const history = histR.ok ? await histR.json() : [];
    gauge.render(latest);
    renderDonow();
    timeline.render(latest);
    breakdown.render(latest, history);
    updateStaleness();
  } catch (e) {
    console.error("loadData failed", e);
  }
}

async function loadRules() {
  try {
    const r = await fetch("/api/rules", { cache: "no-store" });
    currentRules = await r.json();
  } catch (e) {
    console.error("loadRules failed", e);
  }
}

function updateStaleness() {
  const badge = document.getElementById("staleness");
  const text = document.getElementById("staleness-text");
  if (!latest) return;

  const health = latest.sources_health || {};
  const broken = Object.entries(health).filter(([, v]) => v !== "ok");
  const collected = latest.raw_collected_at ? new Date(latest.raw_collected_at) : null;
  const ageMin = collected ? Math.round((Date.now() - collected.getTime()) / 60000) : Infinity;

  badge.classList.remove("badge--fresh", "badge--stale", "badge--alert", "badge--unknown");
  if (broken.length) {
    const keys = broken.map(([k]) => k).join(", ");
    const needsAuth = broken.some(([, v]) => /auth/i.test(v));
    badge.classList.add("badge--alert");
    text.textContent = `${needsAuth ? "re-auth" : "retry"}: ${keys}`;
    badge.title = needsAuth
      ? `${keys} need re-authentication. Click to retry collection; if it persists, run \`claude\` in a terminal and reconnect the connector(s).`
      : `${keys} failed (${broken.map(([, v]) => v).join("; ")}). Click to retry collection.`;
  } else if (ageMin > 35) {
    badge.classList.add("badge--alert");
    text.textContent = `${ageMin}m old`;
  } else if (ageMin > 16) {
    badge.classList.add("badge--stale");
    text.textContent = `${ageMin}m old`;
  } else {
    badge.classList.add("badge--fresh");
    text.textContent = Number.isFinite(ageMin) ? `fresh · ${ageMin}m` : "fresh";
  }
  updateBanner();
}

function manualStep() {
  return (currentRules && currentRules.manual_step) || 10;
}

function renderDonow() {
  if (latest) donow.render(latest, donowMode, manualStep());
}

function cap(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function updateBanner() {
  const banner = document.getElementById("auth-banner");
  const health = (latest && latest.sources_health) || {};
  const authKeys = Object.entries(health)
    .filter(([, v]) => /auth/i.test(String(v)))
    .map(([k]) => k);

  if (!authKeys.length) {
    banner.hidden = true;
    return;
  }
  const connectors = [...new Set(authKeys.map((k) => CONNECTOR[k] || k))];
  document.getElementById("banner-title").textContent =
    `${connectors.join(" and ")} ${connectors.length > 1 ? "need" : "needs"} re-authentication`;
  document.getElementById("banner-detail").innerHTML =
    `${cap(authKeys.join(", "))} are showing cached data. Reconnect the connector, then click Retry — ` +
    `or in Claude Code run <code>/mcp</code>.`;
  document.getElementById("banner-link").href =
    (currentRules && currentRules.reconnect_url) || DEFAULT_RECONNECT_URL;
  banner.hidden = false;
}

function tickClock() {
  const now = new Date();
  document.getElementById("clock-time").textContent = now.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  document.getElementById("clock-date").textContent = now.toLocaleDateString([], {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  gauge.tick();
  timeline.tick();
  if (latest) updateStaleness();
}

async function refresh() {
  const btn = document.getElementById("refresh-btn");
  btn.classList.add("is-spinning");
  btn.disabled = true;
  try {
    await fetch("/api/refresh", { method: "POST" });
    await loadData();
  } finally {
    btn.classList.remove("is-spinning");
    btn.disabled = false;
  }
}

async function bumpPriority(id, delta) {
  try {
    const r = await fetch("/api/override", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, delta }),
    });
    if (!r.ok) return;
    latest = await r.json();
    renderDonow();
    breakdown.render(latest, await fetchHistory());
  } catch (e) {
    console.error("bumpPriority failed", e);
  }
}

async function fetchHistory() {
  try {
    const r = await fetch("/api/history", { cache: "no-store" });
    return r.ok ? await r.json() : [];
  } catch {
    return [];
  }
}

async function saveRules(updated) {
  const r = await fetch("/api/rules", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updated),
  });
  if (!r.ok) return false;
  currentRules = await r.json();
  await loadData();
  return true;
}

function wireControls() {
  document.getElementById("refresh-btn").addEventListener("click", refresh);
  document.getElementById("staleness").addEventListener("click", refresh);
  document.getElementById("banner-retry").addEventListener("click", refresh);
  document.getElementById("rules-btn").addEventListener("click", () => {
    if (currentRules) rulesPanel.open(currentRules, saveRules);
  });
  document.getElementById("rules-close").addEventListener("click", rulesPanel.close);
  document.getElementById("rules-overlay").addEventListener("click", rulesPanel.close);
  rulesPanel.bindControls();

  document.getElementById("donow").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-bump]");
    if (!btn) return;
    e.preventDefault();
    bumpPriority(btn.dataset.bump, Number(btn.dataset.delta));
  });

  document.getElementById("donow-toggle").addEventListener("click", (e) => {
    const btn = e.target.closest(".seg-btn");
    if (!btn) return;
    donowMode = btn.dataset.mode;
    document.querySelectorAll("#donow-toggle .seg-btn").forEach((b) =>
      b.classList.toggle("is-active", b === btn)
    );
    renderDonow();
  });
}

function applyInitialMode() {
  if (new URLSearchParams(location.search).get("view") === "all") {
    donowMode = "all";
    document.querySelectorAll("#donow-toggle .seg-btn").forEach((b) =>
      b.classList.toggle("is-active", b.dataset.mode === "all")
    );
  }
}

async function init() {
  wireControls();
  applyInitialMode();
  // Start the live timers FIRST so the clock/gauge always tick, even if an
  // initial fetch fails — otherwise an unhandled rejection would freeze them.
  tickClock();
  setInterval(tickClock, 1000);
  setInterval(loadData, POLL_MS);
  await Promise.allSettled([loadData(), loadRules()]);
}

init();
