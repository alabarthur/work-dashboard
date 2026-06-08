"""Collector entrypoint.

As a module function (``collect_raw``) it is wired into the backend's refresh
flow. As a CLI (``python -m collector.run --trigger manual``) it performs a full
run — used both for manual refreshes and by the launchd scheduler.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import json

from app import config, services
from app.rules_store import load_rules
from collector import claude_runner, ids, sources

# Which item.source values belong to each per-source health key.
_SOURCE_ITEMS = {
    "teams": {"teams"},
    "calendar": {"calendar"},
    "email": {"outlook_email"},
    "notion": {"notion"},
    "tfs": {"tfs"},
}


def _merge_last_good(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep the previous run's items for any source that failed this run.

    A transient failure of one connector must not blank out that source's items
    on the dashboard — we carry them over (the failing source still shows up in
    the health badge so the staleness is visible).
    """
    if not config.RAW_DATA_PATH.exists():
        return raw
    try:
        prev = json.loads(config.RAW_DATA_PATH.read_text())
    except (ValueError, OSError):
        return raw
    for key, item_sources in _SOURCE_ITEMS.items():
        if raw["sources"].get(key, {}).get("ok"):
            continue
        carried = [i for i in prev.get("items", []) if i.get("source") in item_sources]
        if carried:
            raw["items"].extend(carried)
    return raw


def collect_raw(trigger: str = "manual") -> dict[str, Any]:
    """Collect all sources concurrently, preserve last-good, return validated raw."""
    rules = load_rules()
    raw = sources.collect_all(rules)
    raw = _merge_last_good(raw)
    ids.canonicalize_items(raw["items"])  # stable ids so manual overrides persist
    claude_runner.validate_raw(raw)
    return raw


def wire() -> None:
    """Install the real collector into the backend's refresh flow.

    Called from the server lifespan and the CLI — never at import time, so tests
    that hit /api/refresh don't accidentally invoke Claude.
    """
    services.collector_run = collect_raw


def _within_workday(rules: dict[str, Any]) -> bool:
    wd = rules.get("workday", {})
    tz = wd.get("timezone", "UTC")
    try:
        now = datetime.now(ZoneInfo(tz))
    except Exception:
        now = datetime.now()
    start = wd.get("start", "09:00")
    end = wd.get("end", "18:00")
    return start <= now.strftime("%H:%M") <= end


def main() -> int:
    parser = argparse.ArgumentParser(description="work-table data collector")
    parser.add_argument("--trigger", default="manual", choices=["manual", "scheduled"])
    args = parser.parse_args()

    wire()
    rules = load_rules()
    if (
        args.trigger == "scheduled"
        and rules.get("refresh", {}).get("only_during_workday", True)
        and not _within_workday(rules)
    ):
        print("outside workday; skipping scheduled collection")
        return 0

    result = services.refresh(trigger=args.trigger)
    status = result.get("status")
    print(f"collection {status}: {result.get('error') or result.get('sources_health', '')}")
    return 0 if status in ("ok", "already_running") else 1


if __name__ == "__main__":
    sys.exit(main())
