"""Subprocess wrapper around the headless `claude -p` CLI.

Kept small and injectable: callers pass the prompt + allowed tools, and the
parsing is exposed separately (``extract_json``) so it can be unit-tested with a
fake runner — the whole collector runs without invoking Claude or MCP.

Two environment-verified choices baked in here:
* No ``--json-schema``: in this CLI version that flag makes the model answer
  conversationally (the JSON lands outside ``result``). Prompts pin the shape
  and Python re-validates instead.
* The Microsoft 365 connector is a claude.ai-managed connector (no stored token,
  excluded by ``--strict-mcp-config``), so M365 sources use the default config
  with an ``--allowedTools`` allowlist; Notion uses a pinned strict config.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Optional

import jsonschema

from app import config

DEFAULT_TIMEOUT = 150


def build_command(
    prompt: str,
    allowed_tools: str,
    mcp_config: Optional[str] = None,
    strict: bool = False,
) -> list[str]:
    cmd = [config.CLAUDE_BIN, "-p", prompt, "--output-format", "json", "--model", config.CLAUDE_MODEL]
    if mcp_config:
        cmd += ["--mcp-config", mcp_config]
    if strict:
        cmd += ["--strict-mcp-config"]
    cmd += [
        "--allowedTools", allowed_tools,
        "--permission-mode", "dontAsk",
        # Safety rail per source. Set high enough that the heaviest source
        # (Notion, which fetches task pages) doesn't get truncated mid-output
        # — truncation produced JSONDecodeErrors and endless retries.
        "--max-budget-usd", "0.85",
    ]
    return cmd


def run_claude(
    prompt: str,
    allowed_tools: str,
    mcp_config: Optional[str] = None,
    strict: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Invoke claude headless and return raw stdout. Raises on non-zero exit."""
    proc = subprocess.run(
        build_command(prompt, allowed_tools, mcp_config, strict),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(config.ROOT),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr.strip()[:300]}")
    return proc.stdout


def extract_json(stdout: str) -> dict[str, Any]:
    """Pull a JSON object out of claude's stdout.

    Handles the `--output-format json` envelope ({"result": ...}), a bare JSON
    object, and markdown-fenced JSON.
    """
    text = stdout.strip()
    if not text:
        raise ValueError("empty output from claude")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_strip_fences(text))

    if isinstance(payload, dict) and "result" in payload and "items" not in payload:
        result = payload["result"]
        if isinstance(result, dict):
            return result
        return json.loads(_strip_fences(str(result)))
    return payload


# Backwards-compatible alias.
extract_raw = extract_json


def extract_usage(stdout: str) -> dict[str, Any]:
    """Pull token usage + cost from the `--output-format json` envelope.

    Returns zeros when the envelope has no usage (e.g. a mocked runner in tests).
    """
    zero = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    try:
        env = json.loads(stdout.strip())
    except (json.JSONDecodeError, AttributeError):
        return dict(zero)
    if not isinstance(env, dict):
        return dict(zero)
    u = env.get("usage") or {}
    inp = (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) + (
        u.get("cache_read_input_tokens") or 0
    )
    return {
        "input_tokens": int(inp),
        "output_tokens": int(u.get("output_tokens") or 0),
        "cost_usd": round(float(env.get("total_cost_usd") or 0.0), 4),
    }


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:] if lines and lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        return text[start : end + 1]
    return text


def _sanitize_item(it: dict[str, Any]) -> dict[str, Any]:
    """Coerce common LLM quirks so a minor deviation doesn't drop a good item."""
    if it.get("from") is None:
        it["from"] = {"name": None, "email": None}
    if not isinstance(it.get("tags"), list):
        it["tags"] = []
    if "has_dependency" in it and not isinstance(it["has_dependency"], bool):
        it["has_dependency"] = bool(it["has_dependency"])
    return it


def validate_raw(raw: dict[str, Any]) -> None:
    """Validate raw_data, dropping any individually-invalid item rather than
    failing the whole collection (one bad item used to blank everything)."""
    schema = json.loads(Path(config.RAW_SCHEMA_PATH).read_text())
    item_validator = jsonschema.Draft7Validator(
        {"definitions": schema["definitions"], "$ref": "#/definitions/item"}
    )
    good = []
    for it in raw.get("items", []):
        _sanitize_item(it)
        if item_validator.is_valid(it):
            good.append(it)
    raw["items"] = good
    jsonschema.validate(raw, schema)  # top-level (sources etc.) — we control this
