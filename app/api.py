"""API route handlers (thin wrappers over app.services and rules_store)."""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Response
from pydantic import ValidationError

from app import lock, services
from app.models import Rules
from app.rules_store import load_rules, save_rules

router = APIRouter(prefix="/api")


@router.get("/data")
def get_data() -> dict[str, Any]:
    return services.get_data()


@router.get("/rules")
def get_rules() -> dict[str, Any]:
    return load_rules()


@router.put("/rules")
def put_rules(payload: dict[str, Any], response: Response) -> dict[str, Any]:
    """Validate + persist rules, then re-score cached data so the UI updates instantly."""
    try:
        saved = save_rules(payload)
    except ValidationError as exc:
        response.status_code = 422
        return {"error": "invalid_rules", "detail": exc.errors()}
    services.rescore()
    return saved


@router.post("/override")
def post_override(payload: dict[str, Any], response: Response) -> dict[str, Any]:
    """Bump/lower a single item's manual priority by `delta`, then re-rank."""
    item_id = payload.get("id")
    delta = payload.get("delta")
    if not isinstance(item_id, str) or not isinstance(delta, (int, float)):
        response.status_code = 422
        return {"error": "invalid_override", "detail": "expected {id: str, delta: number}"}
    return services.adjust_override(item_id, float(delta))


@router.post("/refresh")
def post_refresh(response: Response) -> dict[str, Any]:
    """Kick off a collection in the background and return immediately.

    A full collection takes minutes, so we never block the request on it — the
    frontend polls /api/status for completion. The run-lock prevents overlap.
    """
    response.status_code = 202
    if lock.is_locked():
        return {"status": "already_running"}
    threading.Thread(target=services.refresh, args=("manual",), daemon=True).start()
    return {"status": "started"}


@router.get("/status")
def get_status() -> dict[str, Any]:
    return services.get_status()


@router.get("/health")
def get_health() -> dict[str, Any]:
    return services.health()


@router.get("/history")
def get_history() -> list[dict[str, Any]]:
    return services.get_history()


@router.get("/rules/schema")
def get_rules_schema() -> dict[str, Any]:
    """JSON schema of the rules document — lets the panel render generically."""
    return Rules.model_json_schema()
