"""Orchestration between the rules store, scoring engine and collector.

Route handlers stay thin; this module owns the read/rescore/refresh flow and the
on-disk status/history side effects. The actual data collection is injected via
``collector_run`` so the backend is fully usable over fixtures before the
headless-Claude collector exists (Phase 4 wires the real one in).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from app import config, lock
from app.rules_store import load_rules
from scoring import engine

# Injected by the collector layer (Phase 4+). Signature: (trigger) -> raw_data dict.
# When None, refresh() reuses the last cached raw_data (or the sample fixture),
# which lets the whole UI run without MCP.
collector_run: Optional[Callable[[str], dict[str, Any]]] = None


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_raw() -> dict[str, Any]:
    """Return cached raw_data.json, seeding from the sample fixture on first run."""
    config.ensure_data_dir()
    if not config.RAW_DATA_PATH.exists():
        shutil.copyfile(config.SAMPLE_RAW_PATH, config.RAW_DATA_PATH)
    return json.loads(config.RAW_DATA_PATH.read_text())


def load_overrides() -> dict[str, float]:
    """Per-item manual priority adjustments (id -> score delta)."""
    if not config.OVERRIDES_PATH.exists():
        return {}
    try:
        return json.loads(config.OVERRIDES_PATH.read_text())
    except (ValueError, OSError):
        return {}


def adjust_override(item_id: str, delta: float) -> dict[str, Any]:
    """Add ``delta`` to an item's manual adjustment (0 clears it), then rescore."""
    overrides = load_overrides()
    new_value = round(float(overrides.get(item_id, 0)) + float(delta), 1)
    if new_value == 0:
        overrides.pop(item_id, None)
    else:
        overrides[item_id] = new_value
    _atomic_write_json(config.OVERRIDES_PATH, overrides)
    return rescore()


def rescore() -> dict[str, Any]:
    """Re-run scoring over cached raw_data with current rules; write data.json."""
    rules = load_rules()
    raw = load_raw()
    data = engine.score(raw, rules, overrides=load_overrides())
    _atomic_write_json(config.DATA_PATH, data)
    return data


def get_data() -> dict[str, Any]:
    if config.DATA_PATH.exists():
        return json.loads(config.DATA_PATH.read_text())
    return rescore()


def get_status() -> dict[str, Any]:
    if config.STATUS_PATH.exists():
        return json.loads(config.STATUS_PATH.read_text())
    return {"ok": None, "last_run_finished": None, "trigger": None, "error": None}


def _append_history(data: dict[str, Any]) -> None:
    bd = data.get("breakdown", {})
    tiers = bd.get("by_tier", {})
    tasks = bd.get("tasks", {})
    line = {
        "ts": data.get("generated_at"),
        "now": tiers.get("now", 0),
        "soon": tiers.get("soon", 0),
        "later": tiers.get("later", 0),
        "overdue": tasks.get("overdue", 0),
        "due_today": tasks.get("due_today", 0),
        "items_total": len(data.get("ranked", [])),
    }
    config.ensure_data_dir()
    with open(config.HISTORY_PATH, "a") as fh:
        fh.write(json.dumps(line) + "\n")


def refresh(trigger: str = "manual") -> dict[str, Any]:
    """Collect fresh data (if a collector is wired), rescore, and record status.

    Returns a small status dict. If a run is already in progress, returns
    ``{"status": "already_running", ...}`` without spawning a second run.
    """
    if not lock.acquire(trigger):
        info = lock.read_lock() or {}
        return {"status": "already_running", "since": info.get("started")}

    started = datetime.now(timezone.utc).isoformat()
    status: dict[str, Any] = {
        "last_run_started": started,
        "last_run_finished": None,
        "ok": False,
        "trigger": trigger,
        "error": None,
    }
    try:
        if collector_run is not None:
            raw = collector_run(trigger)
            _atomic_write_json(config.RAW_DATA_PATH, raw)
        data = rescore()
        _append_history(data)
        status["ok"] = True
        status["sources_health"] = data.get("sources_health", {})
    except Exception as exc:  # keep last-good data.json untouched on failure
        status["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        status["last_run_finished"] = datetime.now(timezone.utc).isoformat()
        try:
            _atomic_write_json(config.STATUS_PATH, status)
        finally:
            lock.release()

    return {"status": "ok" if status["ok"] else "error", **status}


def get_history(limit: int = 96) -> list[dict[str, Any]]:
    """Return the most recent history snapshots (oldest-first) for trend charts."""
    if not config.HISTORY_PATH.exists():
        return []
    lines = config.HISTORY_PATH.read_text().splitlines()[-limit:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def health() -> dict[str, Any]:
    """Lightweight health snapshot for the frontend badge."""
    data = get_data() if config.DATA_PATH.exists() else None
    return {
        "running": lock.is_locked(),
        "sources_health": (data or {}).get("sources_health", {}),
        "raw_collected_at": (data or {}).get("raw_collected_at"),
        "last_status": get_status(),
    }
