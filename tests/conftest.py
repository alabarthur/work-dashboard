"""Shared fixtures: redirect all on-disk state into a temp dir per test."""

import pytest

from app import config


@pytest.fixture
def temp_data(tmp_path, monkeypatch):
    """Point every data-file path at an isolated tmp dir."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", d)
    monkeypatch.setattr(config, "RULES_PATH", d / "rules.json")
    monkeypatch.setattr(config, "OVERRIDES_PATH", d / "overrides.json")
    monkeypatch.setattr(config, "RAW_DATA_PATH", d / "raw_data.json")
    monkeypatch.setattr(config, "DATA_PATH", d / "data.json")
    monkeypatch.setattr(config, "STATUS_PATH", d / "status.json")
    monkeypatch.setattr(config, "HISTORY_PATH", d / "history.jsonl")
    monkeypatch.setattr(config, "LOCK_PATH", d / ".collector.lock")
    return d
