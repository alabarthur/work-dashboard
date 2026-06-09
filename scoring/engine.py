"""Deterministic scoring engine: raw_data + rules + now -> ranked data.json.

This module is pure (no I/O). ``score()`` is the single entry point consumed by
the backend; it can be called repeatedly and cheaply whenever rules change,
without re-fetching data.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from scoring import factors
from scoring.explain import build_why, tier_for

STALE_AFTER_MINUTES = 16

_FACTOR_FNS = [
    ("base", factors.base_source),
    ("vip", factors.vip_boost),
    ("keyword", factors.keyword_boost),
    ("tag", factors.tag_boost),
    ("dependency", factors.dependency_boost),
]
_TIME_FACTOR_FNS = [
    ("urgency", factors.due_urgency),
    ("imminence", factors.meeting_imminence),
]

_INF = datetime.max.replace(tzinfo=ZoneInfo("UTC"))

# Map an item's `source` to its on/off toggle key in rules.sources_enabled.
_ITEM_SOURCE_TOGGLE = {
    "teams": "teams",
    "outlook_email": "email",
    "calendar": "calendar",
    "notion": "notion",
    "tfs": "tfs",
}


def _source_enabled(item: dict[str, Any], rules: dict[str, Any]) -> bool:
    enabled = rules.get("sources_enabled") or {}
    key = _ITEM_SOURCE_TOGGLE.get(item.get("source"), item.get("source"))
    return enabled.get(key, True)  # default on when unspecified


def _tz(rules: dict[str, Any]) -> ZoneInfo:
    name = rules.get("workday", {}).get("timezone") or "UTC"
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def score_item(
    item: dict[str, Any],
    rules: dict[str, Any],
    now: datetime,
    overrides: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """Score a single normalized item, returning score/tier/why/factors."""
    factor_values: dict[str, float] = {}
    reasons: list[str] = []
    for name, fn in _FACTOR_FNS:
        value, reason = fn(item, rules)
        factor_values[name] = round(value, 1)
        if value and reason:
            reasons.append(reason)
    for name, fn in _TIME_FACTOR_FNS:
        value, reason = fn(item, rules, now)
        factor_values[name] = round(value, 1)
        if value and reason:
            reasons.append(reason)
    manual = float((overrides or {}).get(item.get("id"), 0))
    factor_values["manual"] = round(manual, 1)
    if manual:
        reasons.append(f"manual {'+' if manual > 0 else ''}{manual:g}")
    total = round(sum(factor_values.values()), 1)
    return {
        "id": item.get("id"),
        "source": item.get("source"),
        "type": item.get("type"),
        "title": item.get("title"),
        "url": item.get("url"),
        "score": total,
        "tier": tier_for(total, rules),
        "why": build_why(reasons),
        "factors": factor_values,
    }


def _sort_key(item: dict[str, Any], scored: dict[str, Any]):
    due = factors.parse_dt(item.get("due_at")) or _INF
    created = factors.parse_dt(item.get("created_at")) or _INF
    return (-scored["score"], due, created, str(scored.get("id") or ""))


def _workday_window(rules: dict[str, Any], now: datetime) -> dict[str, Any]:
    wd = rules.get("workday", {})
    start_t = _parse_time(wd.get("start"), time(9, 0))
    end_t = _parse_time(wd.get("end"), time(18, 0))
    start_at = now.replace(hour=start_t.hour, minute=start_t.minute, second=0, microsecond=0)
    end_at = now.replace(hour=end_t.hour, minute=end_t.minute, second=0, microsecond=0)
    total = max(0, int((end_at - start_at).total_seconds() // 60))
    if now <= start_at:
        remaining = total
    elif now >= end_at:
        remaining = 0
    else:
        remaining = int((end_at - now).total_seconds() // 60)
    return {
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat(),
        "minutes_total": total,
        "minutes_remaining": remaining,
    }


def _parse_time(value: Optional[str], default: time) -> time:
    if not value:
        return default
    try:
        h, m = value.split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return default


def _meetings(items: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    out = []
    for it in items:
        if it.get("type") != "meeting":
            continue
        meeting = it.get("meeting") or {}
        start = factors.parse_dt(meeting.get("start"))
        end = factors.parse_dt(meeting.get("end"))
        if start is None:
            continue
        out.append(
            {
                "title": it.get("title"),
                "url": it.get("url"),
                "start": start.isoformat(),
                "end": end.isoformat() if end else None,
                "minutes_until": int((start - now).total_seconds() // 60),
                "is_now": bool(end and start <= now <= end),
            }
        )
    out.sort(key=lambda m: m["start"])
    return out


def _gaps(meetings: list[dict[str, Any]], window: dict[str, Any]) -> list[dict[str, Any]]:
    """Free intervals inside the workday not covered by a meeting."""
    day_start = factors.parse_dt(window["start_at"])
    day_end = factors.parse_dt(window["end_at"])
    busy = []
    for m in meetings:
        s = factors.parse_dt(m["start"])
        e = factors.parse_dt(m["end"]) or s
        if e <= day_start or s >= day_end:
            continue
        busy.append((max(s, day_start), min(e, day_end)))
    busy.sort()
    gaps = []
    cursor = day_start
    for s, e in busy:
        if s > cursor:
            gaps.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < day_end:
        gaps.append((cursor, day_end))
    return [
        {"start": s.isoformat(), "end": e.isoformat(), "minutes": int((e - s).total_seconds() // 60)}
        for s, e in gaps
        if (e - s).total_seconds() >= 60
    ]


def _breakdown(items, scored_all, now) -> dict[str, Any]:
    by_source: dict[str, int] = {}
    for it in items:
        by_source[it.get("source")] = by_source.get(it.get("source"), 0) + 1
    by_tier = {"now": 0, "soon": 0, "later": 0}
    for s in scored_all:
        by_tier[s["tier"]] = by_tier.get(s["tier"], 0) + 1
    due_today = overdue = 0
    for it in items:
        due = factors.parse_dt(it.get("due_at"))
        if due is None:
            continue
        due_local = due.astimezone(now.tzinfo)
        if due_local < now and (due_local.date() - now.date()).days <= 0:
            overdue += 1
        elif due_local.date() == now.date():
            due_today += 1
    return {
        "by_source": by_source,
        "by_tier": by_tier,
        "tasks": {"due_today": due_today, "overdue": overdue},
    }


def _is_cancelled(item: dict[str, Any]) -> bool:
    """Outlook prefixes cancelled meetings with 'Canceled:'/'Cancelled:'."""
    if item.get("type") != "meeting":
        return False
    title = (item.get("title") or "").strip().lower()
    return title.startswith("canceled") or title.startswith("cancelled")


def _is_past_meeting(item: dict[str, Any], now: datetime) -> bool:
    """A meeting that has already ended (in-progress meetings are kept)."""
    if item.get("type") != "meeting":
        return False
    meeting = item.get("meeting") or {}
    ref = factors.parse_dt(meeting.get("end")) or factors.parse_dt(meeting.get("start"))
    return ref is not None and ref <= now


def _total_usage(raw: dict[str, Any]) -> dict[str, Any]:
    """Sum per-source collector token usage + cost for this collection."""
    total = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    for health in (raw.get("sources") or {}).values():
        u = (health or {}).get("usage") or {}
        total["input_tokens"] += u.get("input_tokens", 0) or 0
        total["output_tokens"] += u.get("output_tokens", 0) or 0
        total["cost_usd"] += u.get("cost_usd", 0.0) or 0.0
    total["cost_usd"] = round(total["cost_usd"], 4)
    total["total_tokens"] = total["input_tokens"] + total["output_tokens"]
    return total


def _sources_health(raw: dict[str, Any]) -> dict[str, str]:
    health = {}
    for key, info in (raw.get("sources") or {}).items():
        if info.get("ok"):
            health[key] = "ok"
        else:
            health[key] = info.get("error") or "error"
    return health


def score(
    raw: dict[str, Any],
    rules: dict[str, Any],
    now: Optional[datetime] = None,
    overrides: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """Produce the full ranked dashboard payload from raw data + rules.

    ``overrides`` maps item id -> manual score adjustment (set by the user via
    the per-item ▲/▼ controls); it persists across collections.
    """
    tz = _tz(rules)
    if now is None:
        now = datetime.now(tz)
    else:
        now = now.astimezone(tz)

    items = [
        it
        for it in raw.get("items", [])
        if _source_enabled(it, rules) and not _is_cancelled(it) and not _is_past_meeting(it, now)
    ]
    scored_all = [score_item(it, rules, now, overrides) for it in items]
    order = sorted(
        zip(items, scored_all),
        key=lambda pair: _sort_key(pair[0], pair[1]),
    )
    # Collapse conversations: keep only the highest-priority item per Teams chat
    # / email thread (sorted desc, so the first seen for a thread_id is the top).
    seen_threads: set[str] = set()
    deduped = []
    for it, s in order:
        tid = it.get("thread_id")
        if tid:
            if tid in seen_threads:
                continue
            seen_threads.add(tid)
        deduped.append((it, s))

    items = [it for it, _ in deduped]
    scored_all = [s for _, s in deduped]
    ranked = scored_all

    window = _workday_window(rules, now)
    meetings = _meetings(items, now)
    collected_at = raw.get("collected_at")
    collected_dt = factors.parse_dt(collected_at)
    stale = bool(collected_dt and (now - collected_dt) > timedelta(minutes=STALE_AFTER_MINUTES))

    return {
        "generated_at": now.isoformat(),
        "raw_collected_at": collected_at,
        "stale": stale,
        "sources_health": _sources_health(raw),
        "usage": _total_usage(raw),
        "ranked": ranked,
        "do_now_limit": int(rules.get("do_now_limit", 12)),
        "meetings": meetings,
        "gaps": _gaps(meetings, window),
        "breakdown": _breakdown(items, scored_all, now),
        "workday": window,
    }
