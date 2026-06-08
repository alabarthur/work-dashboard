"""Pydantic models for rules validation and API payloads."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Workday(BaseModel):
    start: str = "09:00"
    end: str = "18:00"
    timezone: str = "UTC"


class Refresh(BaseModel):
    interval_minutes: int = Field(15, ge=1, le=240)
    only_during_workday: bool = True


class Match(BaseModel):
    match: str
    boost: float = 0


class TagBoost(BaseModel):
    tag: str
    boost: float = 0


class DueUrgency(BaseModel):
    overdue: float = 40
    due_today: float = 25
    due_tomorrow: float = 10
    decay_days: int = Field(7, ge=1)


class MeetingImminence(BaseModel):
    lead_minutes: float = Field(15, ge=0)
    max_boost: float = 50


class Tiers(BaseModel):
    now: float = 70
    soon: float = 40


class NotionConfig(BaseModel):
    data_source_url: Optional[str] = None
    due_property: str = "Due"
    tags_property: str = "Tags"


class TfsConfig(BaseModel):
    # Saved-query links (or GUIDs); every work item they return becomes a task.
    queries: list[str] = Field(default_factory=list)
    # Fallback project when a query URL doesn't include one.
    project: Optional[str] = None


class MailConfig(BaseModel):
    # Specific Outlook folders to read (non-recursive, by name). Empty = whole mailbox.
    folders: list[str] = Field(default_factory=list)


class Rules(BaseModel):
    """The full, validated rules document persisted to rules.json."""

    version: int = 1
    workday: Workday = Workday()
    refresh: Refresh = Refresh()
    base_score: float = 25
    sources_enabled: dict[str, bool] = Field(
        default_factory=lambda: {
            "teams": True, "calendar": True, "email": True, "notion": True, "tfs": True
        }
    )
    source_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "teams": 1.0, "outlook_email": 0.9, "calendar": 1.2, "notion": 1.0, "tfs": 1.0
        }
    )
    vip_people: list[Match] = Field(default_factory=list)
    keywords: list[Match] = Field(default_factory=list)
    notion_tag_boosts: list[TagBoost] = Field(default_factory=list)
    notion_dependency_boost: float = 10
    due_date_urgency: DueUrgency = DueUrgency()
    meeting_imminence: MeetingImminence = MeetingImminence()
    tiers: Tiers = Tiers()
    do_now_limit: int = Field(12, ge=1, le=100)
    manual_step: float = Field(10, ge=1, le=100)
    notion: NotionConfig = NotionConfig()
    tfs: TfsConfig = TfsConfig()
    mail: MailConfig = MailConfig()
    reconnect_url: str = "https://claude.ai/settings/connectors"
