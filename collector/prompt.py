"""Per-source collector prompts.

Each prompt asks Claude to fetch and normalize ONE source via its MCP connector
and return a small JSON envelope: {"ok": bool, "error": null|str, "items": [...]}.
Splitting per source lets the collector run them concurrently and degrade one
source without losing the others. No scoring/prioritization here — fetch only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

# The normalized item shape every source must emit.
ITEM_SHAPE = (
    '{"id","source","type","title","snippet","from":{"name","email"},"url",'
    '"created_at","due_at","tags":[],"has_dependency":bool,'
    '"meeting":null|{"start","end","is_organizer","response"}}'
)

_RULES = (
    "Return ONLY one JSON object: "
    '{"ok":bool,"error":null|str,"items":[ ...normalized items... ]}. '
    'If the connector is unavailable or not authenticated, return '
    '{"ok":false,"error":"auth_required","items":[]} — never invent data. '
    "All timestamps must be ISO-8601 WITH timezone offset; use null when unknown. "
    "Give each item a stable unique id. Keep snippets under 140 chars."
)


def now_iso(rules: dict[str, Any]) -> str:
    tz = rules.get("workday", {}).get("timezone", "UTC")
    try:
        return datetime.now(ZoneInfo(tz)).isoformat()
    except Exception:
        return datetime.now().isoformat()


def teams_prompt(rules: dict[str, Any]) -> str:
    return (
        f"It is {now_iso(rules)}. Using the Microsoft 365 connector tool "
        "chat_message_search, find up to 15 recent (last 48h) Microsoft Teams "
        "@mentions and direct/1:1 messages that are awaiting your reply. "
        'For each, emit a normalized item with source="teams", type="mention" or "dm". '
        "Requirements for each item:\n"
        '- title MUST identify the conversation as "<sender name> in <chat/channel name>" '
        "(use the channel/team name for channel mentions, the group-chat name for group chats, "
        'or the person\'s name for a 1:1 DM). Never use a vague title like "follow-up in same chat".\n'
        '- url MUST be the message\'s clickable web permalink (webUrl) so the user can open the '
        "chat; if no message link is available, use the chat/channel link. Do not leave url null.\n"
        '- snippet = the message text preview. Put the sender in "from".\n'
        f"Normalized item shape: {ITEM_SHAPE}. {_RULES}"
    )


def calendar_prompt(rules: dict[str, Any]) -> str:
    return (
        f"It is {now_iso(rules)}. Using the Microsoft 365 connector tool "
        "outlook_calendar_search, get TODAY's meetings only. "
        "EXCLUDE cancelled meetings (skip any event whose title starts with 'Canceled'/'Cancelled' "
        "or that is marked cancelled). "
        'For each remaining meeting, emit a normalized item with source="calendar", type="meeting", '
        'and fill the "meeting" object {start,end,is_organizer,response}. '
        f"Shape: {ITEM_SHAPE}. {_RULES}"
    )


def email_prompt(rules: dict[str, Any]) -> str:
    return (
        f"It is {now_iso(rules)}. Using the Microsoft 365 connector tool "
        "outlook_email_search, get up to 10 recent unread/flagged emails where you are a "
        'direct recipient and that plausibly need a reply. source="outlook_email", type="email". '
        f"Shape: {ITEM_SHAPE}. {_RULES}"
    )


def notion_prompt(rules: dict[str, Any]) -> str:
    notion = rules.get("notion", {})
    if notion.get("data_source_url"):
        where = (
            f"Open the Notion data source {notion['data_source_url']} and read open tasks. "
            f"Treat the '{notion.get('due_property', 'Due')}' property as due_at and "
            f"'{notion.get('tags_property', 'Tags')}' as tags."
        )
    else:
        where = "Use notion-search to find the user's task database, then read open tasks with due dates."
    return (
        f"It is {now_iso(rules)}. {where} Emit up to 20 open tasks as normalized items with "
        'source="notion", type="task", due_at from the due property, tags from tags/status, and '
        "has_dependency=true if the task has blocking/dependency relations. "
        f"Shape: {ITEM_SHAPE}. {_RULES}"
    )
