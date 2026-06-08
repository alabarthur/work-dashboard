"""Per-source collector specs and the concurrent fan-out.

Each source is collected by its own headless `claude -p` run so they execute in
parallel and fail independently. Notion uses a pinned strict config (fast, only
its server loads); the Microsoft 365 sources use the default config with a tool
allowlist because M365 is a claude.ai-managed connector that strict mode excludes.
"""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app import config
from collector import claude_runner, prompt

# Generous per-source timeout; sources run concurrently so wall time ~= the max.
SOURCE_TIMEOUT = 200

M365 = "mcp__claude_ai_Microsoft_365__"


@dataclass(frozen=True)
class SourceSpec:
    key: str  # health key: teams | calendar | email | notion | tfs
    build_prompt: Callable[[dict[str, Any]], str]
    allowed_tools: str
    strict: bool = False
    mcp_config: Optional[str] = None
    # Optional predicate; when it returns False the source is skipped (no run).
    enabled: Optional[Callable[[dict[str, Any]], bool]] = None


def _notion_config() -> str:
    return str(config.COLLECTOR_DIR / "notion.mcp.json")


# Calendar and email are separate sources so today's meetings always land fast
# even when the (slower) email search lags or times out.
SPECS: list[SourceSpec] = [
    SourceSpec("teams", prompt.teams_prompt, f"{M365}chat_message_search"),
    SourceSpec("calendar", prompt.calendar_prompt, f"{M365}outlook_calendar_search"),
    SourceSpec("email", prompt.email_prompt, f"{M365}outlook_email_search"),
    SourceSpec(
        "notion",
        prompt.notion_prompt,
        "mcp__notion__*",
        strict=True,
        mcp_config=_notion_config(),
    ),
    SourceSpec(
        "tfs",
        prompt.tfs_prompt,
        "mcp__tfs-mcp__*",
        enabled=lambda rules: bool(rules.get("tfs", {}).get("queries")),
    ),
]


def _classify_error(exc: Exception) -> str:
    """Map an exception to a short, badge-friendly reason code."""
    if isinstance(exc, subprocess.TimeoutExpired):
        return "timeout"
    msg = str(exc).lower()
    if "rate" in msg and "limit" in msg:
        return "rate_limited"
    if "auth" in msg:
        return "auth_required"
    return type(exc).__name__


def collect_source(
    spec: SourceSpec,
    rules: dict[str, Any],
    runner: Optional[Callable[..., str]] = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run one source. Returns (health, items). Never raises — failures become health."""
    runner = runner or claude_runner.run_claude
    try:
        stdout = runner(
            spec.build_prompt(rules),
            spec.allowed_tools,
            spec.mcp_config,
            spec.strict,
            SOURCE_TIMEOUT,
        )
        result = claude_runner.extract_json(stdout)
        if not result.get("ok", False):
            reason = str(result.get("error") or "source_error")[:60]
            return {"ok": False, "error": reason}, []
        return {"ok": True, "error": None}, list(result.get("items", []))
    except Exception as exc:
        return {"ok": False, "error": _classify_error(exc)}, []


def collect_all(
    rules: dict[str, Any],
    runner: Optional[Callable[..., str]] = None,
) -> dict[str, Any]:
    """Fan out all sources concurrently and assemble a single raw_data document."""
    sources: dict[str, Any] = {}
    items: list[dict[str, Any]] = []

    enabled_map = rules.get("sources_enabled") or {}
    active = []
    for spec in SPECS:
        toggled_off = not enabled_map.get(spec.key, True)
        predicate_off = spec.enabled is not None and not spec.enabled(rules)
        if toggled_off or predicate_off:
            sources[spec.key] = {"ok": True, "error": None}  # off / nothing to fetch
        else:
            active.append(spec)

    with ThreadPoolExecutor(max_workers=max(1, len(active))) as pool:
        futures = {pool.submit(collect_source, spec, rules, runner): spec for spec in active}
        for fut in as_completed(futures):
            spec = futures[fut]
            health, src_items = fut.result()
            sources[spec.key] = health
            items.extend(src_items)

    return {
        "collected_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "sources": sources,
        "items": items,
    }
