"""Collector parsing/validation and lock behavior — with a fake claude runner."""

import json
from pathlib import Path

import pytest

from app import config, lock, services
from collector import claude_runner, sources

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = json.loads((ROOT / "collector" / "fixtures" / "raw_data.sample.json").read_text())
DEFAULT_RULES = json.loads((ROOT / "collector" / "default_rules.json").read_text())


def _envelope(obj) -> str:
    """Mimic `claude -p --output-format json` stdout."""
    return json.dumps({"type": "result", "result": json.dumps(obj), "session_id": "x"})


def _items_for(key):
    src_map = {"teams": "teams", "calendar": "calendar", "email": "outlook_email", "notion": "notion"}
    return [i for i in SAMPLE["items"] if i["source"] == src_map[key]]


def _key_for_tools(allowed_tools):
    if "tfs-mcp" in allowed_tools:
        return "tfs"
    if "notion" in allowed_tools:
        return "notion"
    if "chat_message" in allowed_tools:
        return "teams"
    if "calendar_search" in allowed_tools:
        return "calendar"
    return "email"


# ---- extract_json parsing ----

def test_extract_from_envelope_string_result():
    obj = {"ok": True, "items": [{"id": "x"}]}
    assert claude_runner.extract_json(_envelope(obj))["items"][0]["id"] == "x"


def test_extract_from_envelope_object_result():
    out = json.dumps({"type": "result", "result": {"ok": True, "items": []}})
    assert claude_runner.extract_json(out)["ok"] is True


def test_extract_bare_json():
    assert claude_runner.extract_json('{"ok":true,"items":[]}')["ok"] is True


def test_extract_strips_markdown_fences():
    fenced = '```json\n{"ok":true,"items":[]}\n```'
    out = json.dumps({"type": "result", "result": fenced})
    assert claude_runner.extract_json(out)["ok"] is True


def test_extract_empty_raises():
    with pytest.raises(ValueError):
        claude_runner.extract_json("   ")


# ---- per-source collection + concurrent assembly ----

def _fake_runner(prompt, allowed_tools, mcp_config=None, strict=False, timeout=0):
    return _envelope({"ok": True, "error": None, "items": _items_for(_key_for_tools(allowed_tools))})


def test_collect_all_assembles_validatable_raw():
    raw = sources.collect_all(DEFAULT_RULES, runner=_fake_runner)
    claude_runner.validate_raw(raw)  # must not raise
    assert set(raw["sources"]) == {"teams", "calendar", "email", "notion", "tfs"}
    assert raw["sources"]["calendar"]["ok"] is True
    # tfs has no queries in defaults → skipped (ok, no run), so SAMPLE count holds
    assert len(raw["items"]) == len(SAMPLE["items"])


def test_tfs_skipped_without_queries_runs_with_queries():
    calls = []

    def runner(prompt, allowed_tools, mcp_config=None, strict=False, timeout=0):
        calls.append(_key_for_tools(allowed_tools))
        return _envelope({"ok": True, "items": []})

    # No queries → tfs never invoked.
    sources.collect_all(DEFAULT_RULES, runner=runner)
    assert "tfs" not in calls

    # With a query link → tfs is collected.
    calls.clear()
    rules = {**DEFAULT_RULES, "tfs": {"queries": ["https://tfs/_queries/query/abc/"], "project": "X"}}
    sources.collect_all(rules, runner=runner)
    assert "tfs" in calls


def test_disabled_source_is_skipped():
    calls = []

    def runner(prompt, allowed_tools, mcp_config=None, strict=False, timeout=0):
        calls.append(_key_for_tools(allowed_tools))
        return _envelope({"ok": True, "items": []})

    rules = {**DEFAULT_RULES, "sources_enabled": {"teams": False, "calendar": True, "email": True, "notion": True, "tfs": True}}
    raw = sources.collect_all(rules, runner=runner)
    assert "teams" not in calls          # toggled off → not invoked
    assert raw["sources"]["teams"] == {"ok": True, "error": None}


def test_failing_source_degrades_independently():
    def runner(prompt, allowed_tools, mcp_config=None, strict=False, timeout=0):
        if "email_search" in allowed_tools:
            raise RuntimeError("timeout-ish")  # email lags
        return _envelope({"ok": True, "items": _items_for(_key_for_tools(allowed_tools))})

    raw = sources.collect_all(DEFAULT_RULES, runner=runner)
    claude_runner.validate_raw(raw)
    assert raw["sources"]["email"]["ok"] is False
    assert raw["sources"]["calendar"]["ok"] is True   # calendar still landed
    assert any(i["source"] == "calendar" for i in raw["items"])
    assert all(i["source"] != "outlook_email" for i in raw["items"])


def test_source_reporting_not_ok_yields_no_items():
    def runner(prompt, allowed_tools, mcp_config=None, strict=False, timeout=0):
        return _envelope({"ok": False, "error": "auth_required", "items": []})

    health, items = sources.collect_source(sources.SPECS[0], DEFAULT_RULES, runner=runner)
    assert health["ok"] is False and items == []


def test_classify_error_codes():
    import subprocess as sp
    assert sources._classify_error(sp.TimeoutExpired("claude", 1)) == "timeout"
    assert sources._classify_error(RuntimeError("hit rate limit")) == "rate_limited"
    assert sources._classify_error(RuntimeError("needs auth")) == "auth_required"


# ---- per-source last-good merge (collector preserves data on partial failure) ----

def test_merge_carries_over_failed_source_items(temp_data):
    from collector import run
    # Seed a previous good raw_data (has calendar + email items).
    config.RAW_DATA_PATH.write_text(json.dumps(SAMPLE))
    # New run: email timed out, everything else ok. Email items must survive;
    # calendar (which succeeded) must NOT be duplicated.
    new = {
        "collected_at": "2026-06-08T14:00:00+02:00",
        "sources": {
            "teams": {"ok": True, "error": None},
            "calendar": {"ok": True, "error": None},
            "email": {"ok": False, "error": "timeout"},
            "notion": {"ok": True, "error": None},
        },
        "items": [],
    }
    merged = run._merge_last_good(new)
    email_items = [i for i in merged["items"] if i["source"] == "outlook_email"]
    prev_email = [i for i in SAMPLE["items"] if i["source"] == "outlook_email"]
    assert len(email_items) == len(prev_email) > 0
    assert all(i["source"] != "calendar" for i in merged["items"])  # ok source not carried


def test_merge_no_previous_is_noop(temp_data):
    from collector import run
    new = {"collected_at": "x", "sources": {"teams": {"ok": False, "error": "timeout"},
            "calendar": {"ok": True, "error": None}, "email": {"ok": True, "error": None},
            "notion": {"ok": True, "error": None}}, "items": []}
    assert run._merge_last_good(new)["items"] == []


# ---- lock behavior ----

def test_lock_acquire_release(temp_data):
    assert lock.acquire("manual") is True
    assert lock.is_locked() is True
    assert lock.acquire("manual") is False  # already held
    lock.release()
    assert lock.is_locked() is False


def test_lock_reclaims_stale(temp_data):
    config.LOCK_PATH.write_text(json.dumps({"pid": 999999, "started": 0, "trigger": "x"}))
    assert lock.is_locked() is False           # dead pid + ancient start
    assert lock.acquire("manual") is True       # reclaimed


# ---- refresh wiring with a fake collector ----

def test_refresh_with_injected_collector(temp_data, monkeypatch):
    monkeypatch.setattr(services, "collector_run", lambda trigger: SAMPLE)
    result = services.refresh(trigger="manual")
    assert result["status"] == "ok"
    saved = json.loads(config.RAW_DATA_PATH.read_text())
    assert saved["items"][0]["id"] == SAMPLE["items"][0]["id"]
    data = json.loads(config.DATA_PATH.read_text())
    assert data["ranked"]


def test_refresh_collector_failure_keeps_last_good(temp_data, monkeypatch):
    # First, a good run to establish data.json.
    monkeypatch.setattr(services, "collector_run", lambda trigger: SAMPLE)
    services.refresh()
    good = config.DATA_PATH.read_text()
    # Now a failing collector must not clobber data.json.
    def boom(trigger):
        raise RuntimeError("auth_required")
    monkeypatch.setattr(services, "collector_run", boom)
    result = services.refresh()
    assert result["status"] == "error"
    assert "auth_required" in result["error"]
    assert config.DATA_PATH.read_text() == good
    status = json.loads(config.STATUS_PATH.read_text())
    assert status["ok"] is False


def test_refresh_already_running(temp_data):
    assert lock.acquire("manual") is True
    try:
        result = services.refresh(trigger="manual")
        assert result["status"] == "already_running"
    finally:
        lock.release()
