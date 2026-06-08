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
    '{"id","source","type","title","snippet","thread_id","from":{"name","email"},"url",'
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
        '- thread_id = the chat/conversation id, so messages from the SAME chat share it.\n'
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
    folders = rules.get("mail", {}).get("folders", [])
    if folders:
        folder_list = ", ".join(f'"{f}"' for f in folders)
        scope = (
            "Search ONLY these specific mail folders (non-recursively) — make a SEPARATE "
            f"outlook_email_search call for each, passing folderName: {folder_list}. "
            "For each folder use order='newest', limit=15. Do NOT search any other folder."
        )
    else:
        scope = (
            "Use outlook_email_search to get up to 10 recent emails from the mailbox."
        )
    return (
        f"It is {now_iso(rules)}. Using the Microsoft 365 connector, {scope} "
        "From the results, include emails that plausibly need a reply (recent, unread or flagged, "
        'where you are a direct recipient). source="outlook_email", type="email". '
        "Set thread_id = the email conversationId/thread id, so messages in the SAME thread share it. "
        f"Shape: {ITEM_SHAPE}. {_RULES}"
    )


def tfs_prompt(rules: dict[str, Any]) -> str:
    tfs = rules.get("tfs", {})
    queries = tfs.get("queries", [])
    project_default = tfs.get("project")
    query_lines = "\n".join(f"  - {q}" for q in queries)
    proj_hint = (
        f"If a link does not contain a project, use project '{project_default}'."
        if project_default
        else "If a link does not contain a project, skip it."
    )
    return (
        f"It is {now_iso(rules)}. Using the tfs-mcp connector, collect work items from these "
        "saved TFS/Azure DevOps queries. For EACH link, extract the query GUID and the project "
        "from the URL (these URLs contain '/<project>/_queries/query/<guid>/'). "
        f"{proj_hint}\n"
        "Steps per query: call get_query_results(query_id=<guid>, project=<project>, limit=30) to "
        "get work item ids, then get_work_items_batch(ids, project, expand='Relations') for details. "
        "Queries:\n"
        f"{query_lines}\n"
        'Normalize each work item: source="tfs", type="task", id="tfs:<work item id>", '
        'title=the work item title, snippet="<Work Item Type> · <State>", '
        'from = the AssignedTo person, url = the work item web URL, due_at = null, '
        "tags = [the Work Item Type, the State, plus any tags], "
        "has_dependency = true if it has child/related/predecessor links. "
        "Skip removed/closed-done items if obvious. Cap at ~30 items total across all queries. "
        f"Shape: {ITEM_SHAPE}. {_RULES}"
    )


def notion_prompt(rules: dict[str, Any]) -> str:
    notion = rules.get("notion", {})
    due_prop = notion.get("due_property", "Due")
    tags_prop = notion.get("tags_property", "Tags")
    url = notion.get("data_source_url")
    if url:
        find = f"call notion-fetch with id='{url}'"
    else:
        find = "use notion-search to find the user's tasks database, then notion-fetch it"

    return (
        f"It is {now_iso(rules)}. Enumerate the user's open Notion tasks using this exact method:\n"
        f"1. {find}. The result is a database — read its data source id from the "
        '<data-source url="collection://..."> tag.\n'
        "2. Call notion-search with data_source_url set to that collection:// id, "
        'query="open active task to do", page_size=25, max_highlight_length=0. This lists the '
        "task pages in that database.\n"
        "3. If a returned task's fields aren't in the results, notion-fetch it for details.\n"
        "Include ALL returned tasks whose Status is NOT Done / Completed / Archived / Cancelled. "
        "Do NOT filter by date.\n"
        'For each, emit a normalized item: source="notion", type="task", '
        f"title = the task name, due_at = the '{due_prop}' property if it has one else null, "
        f"tags = the '{tags_prop}' property plus the Status, "
        "has_dependency = true if it has Blocking/Blocked-by relations, url = the page URL. "
        f"Shape: {ITEM_SHAPE}. {_RULES}"
    )
