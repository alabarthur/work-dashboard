"""Pure scoring-factor functions.

Each factor takes a normalized raw item, the rules dict, and a timezone-aware
``now`` and returns ``(value, reason)`` where ``reason`` is a short human string
(or ``None`` when the factor did not contribute). Everything here is
deterministic and side-effect free so it can be unit-tested in isolation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 string into a timezone-aware datetime, or None.

    Accepts a trailing ``Z`` and naive strings are rejected (returned as None)
    because every comparison in scoring must be timezone-aware.
    """
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt


def _text_of(item: dict[str, Any]) -> str:
    return f"{item.get('title') or ''} {item.get('snippet') or ''}".lower()


def base_source(item: dict[str, Any], rules: dict[str, Any]) -> tuple[float, Optional[str]]:
    base = float(rules.get("base_score", 25))
    weight = float(rules.get("source_weights", {}).get(item.get("source"), 1.0))
    return base * weight, None


def vip_boost(item: dict[str, Any], rules: dict[str, Any]) -> tuple[float, Optional[str]]:
    sender = item.get("from") or {}
    name = (sender.get("name") or "").lower()
    email = (sender.get("email") or "").lower()
    best = 0.0
    matched: Optional[str] = None
    for vip in rules.get("vip_people", []):
        m = str(vip.get("match", "")).lower()
        if not m:
            continue
        if (email and m in email) or (name and m in name):
            boost = float(vip.get("boost", 0))
            if boost > best:
                best = boost
                matched = vip.get("match")
    if best > 0:
        return best, f"VIP sender ({matched})"
    return 0.0, None


def keyword_boost(item: dict[str, Any], rules: dict[str, Any]) -> tuple[float, Optional[str]]:
    text = _text_of(item)
    total = 0.0
    hits: list[str] = []
    for kw in rules.get("keywords", []):
        m = str(kw.get("match", "")).lower()
        if m and m in text:
            total += float(kw.get("boost", 0))
            hits.append(kw.get("match"))
    if total > 0:
        return total, "keyword " + ", ".join(f'"{h}"' for h in hits)
    return 0.0, None


def tag_boost(item: dict[str, Any], rules: dict[str, Any]) -> tuple[float, Optional[str]]:
    tags = set(item.get("tags") or [])
    total = 0.0
    hits: list[str] = []
    for tb in rules.get("notion_tag_boosts", []):
        if tb.get("tag") in tags:
            total += float(tb.get("boost", 0))
            hits.append(tb.get("tag"))
    if total > 0:
        return total, "tag " + ", ".join(hits)
    return 0.0, None


def dependency_boost(item: dict[str, Any], rules: dict[str, Any]) -> tuple[float, Optional[str]]:
    if item.get("has_dependency"):
        boost = float(rules.get("notion_dependency_boost", 0))
        if boost:
            return boost, "blocks other work"
    return 0.0, None


def due_urgency(
    item: dict[str, Any], rules: dict[str, Any], now: datetime
) -> tuple[float, Optional[str]]:
    due = parse_dt(item.get("due_at"))
    if due is None:
        return 0.0, None
    cfg = rules.get("due_date_urgency", {})
    due_local = due.astimezone(now.tzinfo)
    days = (due_local.date() - now.date()).days
    if due_local < now and days <= 0:
        return float(cfg.get("overdue", 0)), "overdue"
    if days == 0:
        return float(cfg.get("due_today", 0)), "due today"
    if days == 1:
        return float(cfg.get("due_tomorrow", 0)), "due tomorrow"
    decay_days = int(cfg.get("decay_days", 7))
    if decay_days > 1 and 1 < days <= decay_days:
        frac = (decay_days - days) / (decay_days - 1)
        value = float(cfg.get("due_tomorrow", 0)) * frac
        if value > 0:
            return value, f"due in {days}d"
    return 0.0, None


def meeting_imminence(
    item: dict[str, Any], rules: dict[str, Any], now: datetime
) -> tuple[float, Optional[str]]:
    meeting = item.get("meeting")
    if not meeting:
        return 0.0, None
    start = parse_dt(meeting.get("start"))
    end = parse_dt(meeting.get("end"))
    if start is None:
        return 0.0, None
    cfg = rules.get("meeting_imminence", {})
    lead = float(cfg.get("lead_minutes", 15))
    max_boost = float(cfg.get("max_boost", 50))
    if end and start <= now <= end:
        return max_boost, "happening now"
    if now < start:
        mins = (start - now).total_seconds() / 60.0
        if mins <= lead and lead > 0:
            value = max_boost * (1 - mins / lead)
            return value, f"starts in {int(round(mins))}m"
    return 0.0, None
