"""Canonical, collection-stable item ids.

The collector LLM emits ids inconsistently (e.g. a Notion task may appear as
`<uuid>`, `notion-<uuid>` or `notion:task:<uuid>` across runs). Manual priority
overrides are keyed by id, so unstable ids make boosts detach. We normalize
every item to `<source>:<stable-core>` derived from the underlying object:

* Notion → the page UUID (dashes stripped), e.g. `notion:357f59be...cfd4`
* Outlook/Teams → the immutable Graph id (any source-ish prefix stripped)
* anything else with no usable id → a hash of the url/title
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

_UUID = re.compile(
    r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}", re.IGNORECASE
)


def _uuid_in(*texts: str) -> Optional[str]:
    for t in texts:
        m = _UUID.search(t or "")
        if m:
            return m.group(0).replace("-", "").lower()
    return None


def canonical_id(item: dict[str, Any]) -> str:
    source = str(item.get("source") or "item")
    raw = str(item.get("id") or "")
    url = str(item.get("url") or "")

    uuid = _uuid_in(raw, url)
    if uuid:
        return f"{source}:{uuid}"

    core = raw.split(":")[-1].strip()  # drop any "src:type:" prefixing
    prefix = source.lower() + "-"
    if core.lower().startswith(prefix):  # drop "<source>-" prefixing
        core = core[len(prefix):]
    if not core:
        basis = url or str(item.get("title") or "")
        core = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    return f"{source}:{core}"


def canonicalize_items(items: list[dict[str, Any]]) -> None:
    """Rewrite each item's id to its canonical form, in place."""
    for it in items:
        it["id"] = canonical_id(it)
