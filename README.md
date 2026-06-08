# Work Table

An interactive "what should I do now" dashboard. It pulls your **Teams**, **Outlook**
(calendar + email), **Notion** tasks and **TFS** work items, ranks everything with
configurable prioritization rules, and visualizes the result — a ranked _Do Now_ list,
a workday time-remaining gauge, today's meeting timeline, and workload breakdown charts.

## Features

- **Five sources**, each independently collected and toggleable: Teams (@mentions + DMs),
  Outlook calendar (today's meetings), Outlook email (folder-scoped), Notion tasks, TFS
  work items.
- **Configurable scoring** — source weights, VIP people, keywords, Notion tag boosts,
  dependency boost, due-date urgency, meeting imminence, and tier thresholds. Edits
  re-rank instantly (no new collection needed).
- **Manual priority** — bump/lower any item with ▲/▼ controls; the adjustment persists
  across collections (keyed by a stable canonical id).
- **Conversation de-dup** — only the highest-priority item per Teams chat / email thread
  is shown.
- **Noise filtering** — cancelled and already-finished meetings are dropped; email is
  limited to the folders you choose; Notion reads your tasks database directly.
- **Graceful degradation** — a source that fails keeps its last-good items (with a red
  re-auth/retry banner) instead of blanking the board.
- **Views** — _Do Now_ (top-N) and _All_ (everything, grouped by tier).

## How it works (hybrid architecture)

```
 Claude (headless `claude -p`)             Python                         Browser
 ────────────────────────────────   ──────────────────────────   ───────────────────
 MCP connectors: Notion,            scoring engine (deterministic)  static dashboard
 Microsoft 365, TFS  ──fetch+norm→   raw_data.json ──score──→ data.json ──poll──→ widgets
                                     rules.json ←──── in-dashboard rules panel
```

* **Collector** — `claude -p` reuses your already-authenticated MCP connectors to fetch
  and *normalize* items into `data/raw_data.json`. It does no scoring. The five sources
  (teams, calendar, email, notion, tfs) run as **separate concurrent** headless runs, so
  today's meetings land fast even if the slower email search lags, and a failing source
  keeps its last-good items. Item ids are canonicalized so manual overrides stay attached.
* **Scoring engine** — pure Python turns `raw_data.json` + `rules.json` (+ `overrides.json`)
  into a ranked `data/data.json`. Deterministic and unit-tested; re-runs instantly on rule
  or override changes.
* **Backend** — FastAPI serves the dashboard, the data, rules/override CRUD, and a
  lock-guarded **async** refresh (collection runs in the background). Never touches MCP.
* **Frontend** — auto-refreshing dashboard (live clock, 60s poll) with an in-page rules
  panel and per-item priority controls.

## Quick start

```bash
cd work-table
uv venv && uv pip install fastapi "uvicorn[standard]" pydantic jsonschema   # first time
./run.sh                       # → http://localhost:8787
```

The dashboard works immediately from a bundled sample fixture. Click **Refresh** (or run
the collector below) to pull your real data. `run.sh` runs with `--reload`, so backend
code changes apply without a manual restart.

## Collecting real data

```bash
.venv/bin/python -m collector.run --trigger manual
```

This invokes `claude -p` with your connectors. A full collection takes a couple of
minutes; the in-dashboard **Refresh** button kicks it off in the background and shows a
"collecting…" state until it finishes.

**Connectors used:** `notion` (standard MCP server), `Microsoft 365` (claude.ai-managed
connector, for Teams + Outlook), and `tfs-mcp`. They must be authenticated in your Claude
CLI. If a connector's token lapses, the collector marks that source `auth_required`, keeps
your last-good data, and the dashboard shows a banner with a **Reconnect** link
(Settings → Connectors) and a **Retry** button. You can also reconnect via `/mcp` in an
interactive `claude` session.

## Scheduling

```bash
./scripts/install-schedule.sh        # installs a launchd agent
```

The launchd job ticks every 5 minutes. Each tick runs the collector, which **self-gates**:
it skips until `refresh.interval_minutes` has elapsed since the last run, and (when
`refresh.only_during_workday` is on) skips outside your workday window. So the rules
control the real cadence. Manage it:

```bash
launchctl kickstart gui/$(id -u)/com.user.worktable.collector   # run now
launchctl bootout   gui/$(id -u)/com.user.worktable.collector   # uninstall
# logs: data/collector.out.log / data/collector.err.log
```

## Configuring rules

Click **Rules** in the dashboard (or open `?rules=open`). Sections:

- **Sources** — checkboxes to turn each source on/off.
- **Workday** — start/end, timezone, refresh interval, and "only auto-collect during
  workday hours".
- **Source weights** + **base score**.
- **VIP people** / **Keywords** — boosts for matching senders / text.
- **Notion tasks** — paste your tasks **database/view URL** (read directly via its data
  source for the complete list) and set the **Date** and **Tags** property names.
- **Notion tag boosts** + dependency boost.
- **Mail folders** — the Outlook folders to read (non-recursive). Empty = whole mailbox.
- **TFS queries** — saved-query links (every returned work item becomes a task) + default
  project.
- **Due-date urgency**, **Meetings** (lead time / max boost), **Tiers & display**
  (thresholds, Do-now list size, manual ▲▼ step).

Saving re-ranks instantly. Rules persist to `data/rules.json`; defaults live in
`collector/default_rules.json`. Per-item manual adjustments live in `data/overrides.json`.

## Tests

```bash
.venv/bin/python -m pytest -q
```

Cover the scoring engine (golden ranking, re-rank on rule/override change, cancelled &
past-meeting filtering, conversation de-dup, source toggles, gaps, breakdown, staleness),
canonical ids, rules validation/atomic save, mail/TFS config, collector parsing &
per-source merge, lock behavior, the async refresh + interval gate, and the API — all
without invoking MCP.

## Layout

| Path | Purpose |
|------|---------|
| `scoring/` | Deterministic scoring engine (`engine`, `factors`, `explain`) |
| `collector/` | Headless-Claude collector (`run`, `prompt`, `claude_runner`, `sources`, `ids`) + `raw_schema.json`, `default_rules.json`, fixtures |
| `app/` | FastAPI backend (`main`, `api`, `services`, `rules_store`, `lock`, `models`, `config`) |
| `frontend/` | Static dashboard — `app.js` + widgets (gauge, donow, timeline, breakdown, rules_panel) |
| `data/` | Runtime state (gitignored): `rules`, `overrides`, `raw_data`, `data`, `status`, `history` |
| `scripts/` | launchd plist + installer |
