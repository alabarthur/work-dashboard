"""Deterministic scoring tests over the recorded fixture (no MCP, fixed now)."""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scoring import engine

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "collector" / "fixtures" / "raw_data.sample.json"
DEGRADED = ROOT / "collector" / "fixtures" / "raw_data.degraded.json"
DEFAULT_RULES = ROOT / "collector" / "default_rules.json"

# 13:05 Prague on the fixture day — Release sync (13:15) is 10m away.
NOW = datetime(2026, 6, 8, 13, 5, tzinfo=ZoneInfo("Europe/Prague"))


@pytest.fixture
def raw():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def rules():
    return json.loads(DEFAULT_RULES.read_text())


def _by_id(result):
    return {r["id"]: r for r in result["ranked"]}


def test_full_payload_shape(raw, rules):
    result = engine.score(raw, rules, now=NOW)
    for key in [
        "generated_at", "raw_collected_at", "stale", "sources_health",
        "ranked", "meetings", "gaps", "breakdown", "workday",
    ]:
        assert key in result
    assert len(result["ranked"]) == len(raw["items"])


def test_imminent_meeting_gets_imminence_boost(raw, rules):
    scored = _by_id(engine.score(raw, rules, now=NOW))
    meeting = scored["cal:event:AAMk100"]  # Release sync 10 min away (lead 15)
    # 50 * (1 - 10/15) = 16.7
    assert meeting["factors"]["imminence"] == 16.7
    assert "starts in 10m" in meeting["why"]
    assert engine.score(raw, rules, now=NOW)["meetings"][0]["minutes_until"] == 10


def test_p0_task_is_top_priority(raw, rules):
    # base 25 + tag 25 + due-today 25 + dependency 10 = 85, the highest score.
    top = engine.score(raw, rules, now=NOW)["ranked"][0]
    assert top["id"] == "notion:task:abc100"
    assert top["score"] == 85.0


def test_vip_and_keyword_stack(raw, rules):
    scored = _by_id(engine.score(raw, rules, now=NOW))
    mention = scored["teams:msg:AAQk001"]  # Jane (VIP) + "blocker" keyword
    assert mention["factors"]["vip"] == 20
    assert mention["factors"]["keyword"] == 20
    assert "VIP sender" in mention["why"] and "blocker" in mention["why"]


def test_overdue_task_outranks_future_task(raw, rules):
    scored = _by_id(engine.score(raw, rules, now=NOW))
    overdue = scored["notion:task:abc101"]   # due 2026-06-06 (overdue), P2
    future = scored["notion:task:abc102"]    # due 2026-06-12, P1
    assert overdue["factors"]["urgency"] == 40
    assert overdue["score"] > future["score"]


def test_p0_task_due_today_with_dependency(raw, rules):
    scored = _by_id(engine.score(raw, rules, now=NOW))
    task = scored["notion:task:abc100"]  # P0 + due today + dependency
    assert task["factors"]["tag"] == 25
    assert task["factors"]["urgency"] == 25
    assert task["factors"]["dependency"] == 10
    assert task["tier"] == "now"


def test_newsletter_is_lowest(raw, rules):
    result = engine.score(raw, rules, now=NOW)
    assert result["ranked"][-1]["id"] == "outlook:mail:AAMk011"
    assert result["ranked"][-1]["tier"] == "later"


def test_rules_change_rerank(raw, rules):
    """Zeroing the VIP boost must demote Jane's items relative to before."""
    before = _by_id(engine.score(raw, rules, now=NOW))["teams:msg:AAQk001"]["score"]
    rules["vip_people"] = []
    after = _by_id(engine.score(raw, rules, now=NOW))["teams:msg:AAQk001"]["score"]
    assert after == before - 20


def test_workday_remaining(raw, rules):
    result = engine.score(raw, rules, now=NOW)
    wd = result["workday"]
    assert wd["minutes_total"] == 540          # 09:00-18:00
    assert wd["minutes_remaining"] == 295       # 18:00 - 13:05


def test_breakdown_counts(raw, rules):
    bd = engine.score(raw, rules, now=NOW)["breakdown"]
    assert bd["by_source"] == {"teams": 2, "outlook_email": 2, "calendar": 2, "notion": 3}
    assert bd["tasks"]["overdue"] == 1
    assert bd["tasks"]["due_today"] == 1
    assert sum(bd["by_tier"].values()) == len(raw["items"])


def test_gaps_between_meetings(raw, rules):
    gaps = engine.score(raw, rules, now=NOW)["gaps"]
    # workday 09:00-18:00, meetings 13:15-13:45 and 16:00-16:30
    assert any(g["minutes"] == 135 for g in gaps)   # 13:45 -> 16:00
    assert all(g["minutes"] > 0 for g in gaps)


def test_degraded_source_health(rules):
    raw = json.loads(DEGRADED.read_text())
    result = engine.score(raw, rules, now=NOW)
    assert result["sources_health"]["notion"] == "auth_required"
    assert result["sources_health"]["teams"] == "ok"


def test_cancelled_meetings_excluded(rules):
    raw = {
        "collected_at": "2026-06-08T13:00:00+02:00",
        "sources": {k: {"ok": True, "error": None} for k in ("teams", "calendar", "email", "notion")},
        "items": [
            {"id": "cal:1", "source": "calendar", "type": "meeting", "title": "Canceled: Ask Polina",
             "tags": [], "has_dependency": False,
             "meeting": {"start": "2026-06-08T15:00:00+02:00", "end": "2026-06-08T15:30:00+02:00"}},
            {"id": "cal:2", "source": "calendar", "type": "meeting", "title": "Real sync",
             "tags": [], "has_dependency": False,
             "meeting": {"start": "2026-06-08T16:00:00+02:00", "end": "2026-06-08T16:30:00+02:00"}},
        ],
    }
    result = engine.score(raw, rules, now=NOW)
    ids = [r["id"] for r in result["ranked"]]
    assert "cal:1" not in ids and "cal:2" in ids
    assert all(m["title"] != "Canceled: Ask Polina" for m in result["meetings"])


def test_past_meetings_excluded(rules):
    # NOW is 13:05. Past meeting ended at 10:30; in-progress 13:00-13:30; future 15:00.
    raw = {
        "collected_at": "2026-06-08T13:00:00+02:00",
        "sources": {k: {"ok": True, "error": None} for k in ("teams", "calendar", "email", "notion")},
        "items": [
            {"id": "past", "source": "calendar", "type": "meeting", "title": "Morning standup",
             "tags": [], "has_dependency": False,
             "meeting": {"start": "2026-06-08T10:00:00+02:00", "end": "2026-06-08T10:30:00+02:00"}},
            {"id": "live", "source": "calendar", "type": "meeting", "title": "In progress",
             "tags": [], "has_dependency": False,
             "meeting": {"start": "2026-06-08T13:00:00+02:00", "end": "2026-06-08T13:30:00+02:00"}},
            {"id": "future", "source": "calendar", "type": "meeting", "title": "Later sync",
             "tags": [], "has_dependency": False,
             "meeting": {"start": "2026-06-08T15:00:00+02:00", "end": "2026-06-08T15:30:00+02:00"}},
        ],
    }
    result = engine.score(raw, rules, now=NOW)
    ids = {r["id"] for r in result["ranked"]}
    assert ids == {"live", "future"}
    assert "past" not in ids
    assert {m["title"] for m in result["meetings"]} == {"In progress", "Later sync"}


def test_thread_dedup_keeps_highest(rules):
    raw = {
        "collected_at": "2026-06-08T13:00:00+02:00",
        "sources": {k: {"ok": True, "error": None} for k in ("teams", "calendar", "email", "notion", "tfs")},
        "items": [
            {"id": "t-low", "source": "teams", "type": "dm", "title": "ok thanks",
             "thread_id": "chat1", "from": {"name": "Bob"}, "tags": [], "has_dependency": False},
            {"id": "t-high", "source": "teams", "type": "mention", "title": "urgent blocker please",
             "thread_id": "chat1", "from": {"email": "jane.manager@company.com"}, "tags": [], "has_dependency": False},
            {"id": "t-other", "source": "teams", "type": "dm", "title": "different chat",
             "thread_id": "chat2", "from": {"name": "Sue"}, "tags": [], "has_dependency": False},
            {"id": "m-a", "source": "outlook_email", "type": "email", "title": "re: spec",
             "thread_id": "thread-x", "from": {"name": "A"}, "tags": [], "has_dependency": False},
            {"id": "m-b", "source": "outlook_email", "type": "email", "title": "re: spec urgent",
             "thread_id": "thread-x", "from": {"name": "A"}, "tags": [], "has_dependency": False},
        ],
    }
    ids = [r["id"] for r in engine.score(raw, rules, now=NOW)["ranked"]]
    assert "t-high" in ids and "t-low" not in ids   # one per chat (the top)
    assert "t-other" in ids                          # different chat survives
    assert ids.count("m-a") + ids.count("m-b") == 1   # one per email thread
    assert "m-b" in ids                               # the "urgent" one wins


def test_items_without_thread_id_not_deduped(raw, rules):
    # Notion tasks have no thread_id — none should be collapsed.
    result = engine.score(raw, rules, now=NOW)
    notion_ids = [r["id"] for r in result["ranked"] if r["source"] == "notion"]
    assert len(notion_ids) == 3


def test_tfs_item_scores_base_only(rules):
    raw = {
        "collected_at": "2026-06-08T13:00:00+02:00",
        "sources": {k: {"ok": True, "error": None} for k in ("teams", "calendar", "email", "notion", "tfs")},
        "items": [
            {"id": "tfs:12345", "source": "tfs", "type": "task", "title": "Fix login bug",
             "snippet": "Bug · Active", "from": {"name": "Me", "email": None},
             "url": "https://tfs/_workitems/edit/12345", "due_at": None,
             "tags": ["Bug", "Active"], "has_dependency": False},
        ],
    }
    item = _by_id(engine.score(raw, rules, now=NOW))["tfs:12345"]
    # base only: 25 * source_weights.tfs (1.0) = 25, no urgency (due_at null)
    assert item["factors"]["base"] == 25.0
    assert item["factors"]["urgency"] == 0
    assert item["score"] == 25.0


def test_disabled_source_filtered_out(raw, rules):
    rules["sources_enabled"] = {"teams": False, "calendar": True, "email": True, "notion": True, "tfs": True}
    result = engine.score(raw, rules, now=NOW)
    assert all(r["source"] != "teams" for r in result["ranked"])
    # other sources still present
    assert any(r["source"] == "notion" for r in result["ranked"])


def test_teams_default_weight_bumped(raw, rules):
    scored = _by_id(engine.score(raw, rules, now=NOW))
    # default teams weight is 1.3 → base 25 * 1.3 = 32.5
    assert scored["teams:dm:AAQk002"]["factors"]["base"] == 32.5


def test_manual_override_factor(raw, rules):
    base = _by_id(engine.score(raw, rules, now=NOW))["teams:dm:AAQk002"]["score"]
    bumped = _by_id(engine.score(raw, rules, now=NOW, overrides={"teams:dm:AAQk002": 50}))
    item = bumped["teams:dm:AAQk002"]
    assert item["score"] == base + 50
    assert item["factors"]["manual"] == 50
    assert "manual +50" in item["why"]


def test_manual_override_can_demote(raw, rules):
    demoted = _by_id(engine.score(raw, rules, now=NOW, overrides={"notion:task:abc100": -60}))
    # P0 task base 85 - 60 = 25
    assert demoted["notion:task:abc100"]["score"] == 25.0
    assert "manual -60" in demoted["notion:task:abc100"]["why"]


def test_usage_totaled_in_output(rules):
    raw = {
        "collected_at": "2026-06-08T13:00:00+02:00",
        "sources": {
            "teams": {"ok": True, "error": None, "usage": {"input_tokens": 1000, "output_tokens": 100, "cost_usd": 0.02}},
            "calendar": {"ok": True, "error": None, "usage": {"input_tokens": 500, "output_tokens": 50, "cost_usd": 0.01}},
            "email": {"ok": True, "error": None},
            "notion": {"ok": True, "error": None, "usage": {"input_tokens": 2000, "output_tokens": 200, "cost_usd": 0.05}},
            "tfs": {"ok": True, "error": None},
        },
        "items": [],
    }
    u = engine.score(raw, rules, now=NOW)["usage"]
    assert u["input_tokens"] == 3500
    assert u["output_tokens"] == 350
    assert u["cost_usd"] == 0.08
    assert u["total_tokens"] == 3850


def test_stale_detection(raw, rules):
    later = datetime(2026, 6, 8, 13, 30, tzinfo=ZoneInfo("Europe/Prague"))
    assert engine.score(raw, rules, now=later)["stale"] is True
    assert engine.score(raw, rules, now=NOW)["stale"] is False
