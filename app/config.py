"""Centralized paths and runtime settings for the work-table dashboard."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"
COLLECTOR_DIR = ROOT / "collector"
FRONTEND_DIR = ROOT / "frontend"
FIXTURES_DIR = COLLECTOR_DIR / "fixtures"

RULES_PATH = DATA_DIR / "rules.json"
OVERRIDES_PATH = DATA_DIR / "overrides.json"
RAW_DATA_PATH = DATA_DIR / "raw_data.json"
DATA_PATH = DATA_DIR / "data.json"
STATUS_PATH = DATA_DIR / "status.json"
HISTORY_PATH = DATA_DIR / "history.jsonl"
LOCK_PATH = DATA_DIR / ".collector.lock"

DEFAULT_RULES_PATH = COLLECTOR_DIR / "default_rules.json"
SAMPLE_RAW_PATH = FIXTURES_DIR / "raw_data.sample.json"
RAW_SCHEMA_PATH = COLLECTOR_DIR / "raw_schema.json"

# Path to the claude CLI used by the collector (overridable for tests/launchd).
CLAUDE_BIN = os.environ.get("WORKTABLE_CLAUDE_BIN", "/opt/homebrew/bin/claude")

# Model for the headless collector. "sonnet" balances speed/cost against the
# reliability needed for the multi-step tool work (Notion enumeration, TFS
# query→batch, normalization). Set WORKTABLE_CLAUDE_MODEL=haiku to go faster/
# cheaper, or to a full id like "claude-sonnet-4-6".
CLAUDE_MODEL = os.environ.get("WORKTABLE_CLAUDE_MODEL", "sonnet")

PORT = int(os.environ.get("WORKTABLE_PORT", "8787"))


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
