"""Tests for rules loading, validation and atomic save."""

import json

import pytest

from app import config
from app.rules_store import load_rules, save_rules
from app.models import Rules


def test_load_seeds_defaults(temp_data):
    rules = load_rules()
    assert config.RULES_PATH.exists()
    assert rules["version"] == 1
    assert "source_weights" in rules


def test_save_roundtrip_and_validation(temp_data):
    rules = load_rules()
    rules["base_score"] = 30
    rules["vip_people"] = [{"match": "ceo@x.com", "boost": 35}]
    saved = save_rules(rules)
    assert saved["base_score"] == 30
    on_disk = json.loads(config.RULES_PATH.read_text())
    assert on_disk["vip_people"][0]["boost"] == 35


def test_save_rejects_invalid(temp_data):
    bad = load_rules()
    bad["do_now_limit"] = -5  # violates ge=1
    with pytest.raises(Exception):
        save_rules(bad)


def test_defaults_validate_against_model():
    defaults = json.loads(config.DEFAULT_RULES_PATH.read_text())
    Rules.model_validate(defaults)  # must not raise


def test_mail_and_tfs_config_roundtrip(temp_data):
    rules = load_rules()
    rules["mail"]["folders"] = ["Inbox", "Project X"]
    rules["tfs"]["queries"] = ["https://tfs/_queries/query/abc/"]
    saved = save_rules(rules)
    assert saved["mail"]["folders"] == ["Inbox", "Project X"]
    assert saved["tfs"]["queries"] == ["https://tfs/_queries/query/abc/"]
