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
        "--max-budget-usd", "0.40",
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


def validate_raw(raw: dict[str, Any]) -> None:
    schema = json.loads(Path(config.RAW_SCHEMA_PATH).read_text())
    jsonschema.validate(raw, schema)
