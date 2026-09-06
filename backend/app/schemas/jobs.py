from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import JobStatus


class PublicationJobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: UUID
    artist_id: UUID
    concept_id: UUID
    audio_use_plan_id: UUID
    render_plan_id: UUID
    track_id: UUID | None = None
    asset_ids: tuple[UUID, ...] = Field(min_length=1)
    target_platform: str = Field(min_length=1, max_length=40)
    policy_classification: dict[str, Any]
    recent_render_plan_hashes: tuple[str, ...] = ()
    caption: str = Field(default="", max_length=5000)
    lineage: dict[str, Any] = Field(default_factory=dict)


class JobReceipt(BaseModel):
    id: UUID
    job_type: str
    status: JobStatus
    reused: bool
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime


class JobStatusResponse(BaseModel):
    id: UUID
    job_type: str
    status: JobStatus
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime
    lease_expires_at: datetime | None
    last_error: str | None
    result: dict[str, Any] | None
    created_at: datetime
    completed_at: datetime | None
