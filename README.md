# Work Table

An interactive "what should I do now" dashboard. It pulls your **Teams**, **Outlook**
(email + calendar) and **Notion** tasks, ranks them with configurable prioritization
rules, and visualizes the result — a ranked _Do Now_ list, a workday time-remaining
gauge, today's meeting timeline, and workload breakdown charts.

## How it works (hybrid architecture)

```
 Claude (headless `claude -p`)            Python                         Browser
 ───────────────────────────────   ──────────────────────────   ───────────────────
 MCP connectors: Notion +          scoring engine (deterministic)  static dashboard
 Microsoft 365  ──fetch+normalize→  raw_data.json ──score──→ data.json ──poll──→ widgets
                                    rules.json ←──── in-dashboard rules panel
```

* **Collector** — `claude -p` reuses your already-authenticated MCP connectors to
  fetch and *normalize* items into `data/raw_data.json`. It does no scoring. The five
  sources — **teams, calendar, email, notion, tfs** — are collected by separate concurrent
  runs, so today's meetings land fast even if the (slower) email search lags, and any
  source that fails keeps its last-good items instead of blanking the dashboard. Sources
  can be toggled on/off in the rules panel; **TFS** is driven by saved-query links you add
  to the rules (every work item a query returns becomes a task).
* **Scoring engine** — pure Python turns `raw_data.json` + `rules.json` into a ranked
  `data/data.json`. Deterministic and unit-tested; re-runs instantly when you edit rules.
* **Backend** — FastAPI serves the dashboard, the data, rules CRUD, and a lock-guarded
  refresh. Never touches MCP itself.
* **Frontend** — auto-refreshing dashboard with a live clock; edit rules in a side panel.

## Quick start

```bash
cd work-table
uv venv && uv pip install fastapi "uvicorn[standard]" pydantic jsonschema   # first time
./run.sh                       # → http://localhost:8787
```

The dashboard works immediately using a bundled sample fixture. Click **Refresh** (or run
the collector below) to pull your real data.

## Collecting real data

```bash
.venv/bin/python -m collector.run --trigger manual
```

This invokes `claude -p` with your Notion + Microsoft 365 connectors. Requirements:

* The **Notion** connector and the **Microsoft 365** connector must be authenticated in
  your Claude CLI. Notion is a standard MCP server; Microsoft 365 is a claude.ai-managed
  connector. If a connector's token has lapsed, the collector marks that source
  `auth_required` (the dashboard shows a red **re-auth** badge) and keeps your last-good
  data. To re-authenticate, run `claude` interactively once and reconnect the connector.

## Scheduling (every 15 min)

```bash
./scripts/install-schedule.sh        # installs a launchd agent
```

The collector self-gates on your workday window (`rules.json` → `workday`), so off-hours
ticks exit immediately. Manage it:

```bash
launchctl kickstart gui/$(id -u)/com.user.worktable.collector   # run now
launchctl bootout   gui/$(id -u)/com.user.worktable.collector   # uninstall
# logs: data/collector.out.log / data/collector.err.log
```

## Configuring rules

Click **Rules** in the dashboard. Adjust source weights, VIP people, keywords, Notion tag
boosts, due-date urgency, meeting imminence, tier thresholds and your workday window.
Saving re-ranks instantly (no new collection needed). Rules persist to `data/rules.json`;
defaults live in `collector/default_rules.json`.

To point at a specific Notion tasks database, set `notion.data_source_url` (and the
`due_property` / `tags_property` names) in the rules.

## Tests

```bash
.venv/bin/python -m pytest -q
```

Covers the scoring engine (golden ranking, re-rank on rule change, gaps, breakdown,
staleness), rules validation/atomic save, collector parsing, and lock behavior — all
without invoking MCP.

## Layout

| Path | Purpose |
|------|---------|
| `scoring/` | Deterministic scoring engine (`engine`, `factors`, `explain`) |
| `collector/` | Headless-Claude collector (`run`, `prompt`, `claude_runner`) + schema + fixtures |
| `app/` | FastAPI backend (`api`, `services`, `rules_store`, `lock`, `models`, `config`) |
| `frontend/` | Static dashboard (widgets: gauge, donow, timeline, breakdown, rules_panel) |
| `data/` | Runtime state (gitignored): rules, raw_data, data, status, history |
| `scripts/` | launchd plist + installer |
