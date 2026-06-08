"""Canonical id stability — the property that makes manual overrides persist."""

from collector.ids import canonical_id, canonicalize_items

UUID = "357f59be-6944-80a6-b16b-d4dceab9cfd4"
UUID32 = UUID.replace("-", "")


def _notion(raw_id, url=None):
    return {"source": "notion", "id": raw_id, "url": url, "title": "t"}


def test_notion_id_variants_collapse_to_one():
    forms = [
        _notion(UUID),
        _notion(f"notion-{UUID}"),
        _notion(f"notion:task:{UUID}"),
        _notion("notion:task:xyz", url=f"https://notion.so/{UUID}"),
        _notion(UUID32),  # already-canonical no-dash form is idempotent
    ]
    canon = {canonical_id(f) for f in forms}
    assert canon == {f"notion:{UUID32}"}


def test_outlook_prefixes_stripped():
    assert canonical_id({"source": "outlook_email", "id": "outlook:mail:AAMk010"}) == "outlook_email:AAMk010"
    assert canonical_id({"source": "outlook_email", "id": "outlook_email-AAMk010"}) == "outlook_email:AAMk010"
    assert canonical_id({"source": "outlook_email", "id": "AAMk010"}) == "outlook_email:AAMk010"


def test_teams_id():
    assert canonical_id({"source": "teams", "id": "teams:msg:AAQk001"}) == "teams:AAQk001"


def test_missing_id_falls_back_to_url_hash_and_is_stable():
    item = {"source": "calendar", "id": None, "url": "https://x/evt/123", "title": "Sync"}
    a = canonical_id(item)
    b = canonical_id(dict(item))
    assert a == b and a.startswith("calendar:")


def test_canonicalize_items_in_place():
    items = [_notion(f"notion-{UUID}"), {"source": "teams", "id": "teams:msg:Z9"}]
    canonicalize_items(items)
    assert items[0]["id"] == f"notion:{UUID32}"
    assert items[1]["id"] == "teams:Z9"
