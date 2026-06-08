"""Build human-readable explanations and tiers from scored factors."""

from __future__ import annotations

from typing import Any


def build_why(reasons: list[str]) -> str:
    """Join the non-empty factor reasons into a single ' · '-separated string."""
    parts = [r for r in reasons if r]
    return " · ".join(parts) if parts else "baseline priority"


def tier_for(score: float, rules: dict[str, Any]) -> str:
    tiers = rules.get("tiers", {})
    if score >= float(tiers.get("now", 70)):
        return "now"
    if score >= float(tiers.get("soon", 40)):
        return "soon"
    return "later"
