"""Load, validate and atomically persist the rules document."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app import config
from app.models import Rules


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def load_rules() -> dict[str, Any]:
    """Return the current rules, seeding from defaults on first run.

    Existing rules files are normalized through the Rules model so any newly
    added fields (e.g. manual_step, reconnect_url) get their defaults filled in
    rather than appearing as missing/zero in the UI.
    """
    config.ensure_data_dir()
    if not config.RULES_PATH.exists():
        defaults = _read_json(config.DEFAULT_RULES_PATH)
        _atomic_write(config.RULES_PATH, defaults)
        return defaults
    data = Rules.model_validate(_read_json(config.RULES_PATH)).model_dump()
    # Backfill any per-source keys missing from older files (pydantic keeps an
    # existing dict as-is, so a new source like "tfs" wouldn't appear otherwise).
    defaults = Rules().model_dump()
    for field in ("source_weights", "sources_enabled"):
        for key, val in defaults[field].items():
            data[field].setdefault(key, val)
    return data


def save_rules(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate against the Rules model and atomically write rules.json."""
    validated = Rules.model_validate(payload).model_dump()
    config.ensure_data_dir()
    _atomic_write(config.RULES_PATH, validated)
    return validated


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
