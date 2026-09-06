from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import PlatformProofStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class PlatformAccount(Base):
    __tablename__ = "platform_accounts"
    __table_args__ = (
        UniqueConstraint("platform", "external_account_id", name="uq_platform_external_account"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    platform: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    external_account_id: Mapped[str] = mapped_column(String(240), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(240))
    account_type: Mapped[str | None] = mapped_column(String(80))
    api_family: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PlatformCapabilitySnapshot(Base):
    __tablename__ = "platform_capability_snapshots"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    platform_account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("platform_accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    api_family: Mapped[str] = mapped_column(String(120), nullable=False)
    api_version: Mapped[str | None] = mapped_column(String(80))
    capabilities: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PlatformProofRun(Base):
    __tablename__ = "platform_proof_runs"
    __table_args__ = (
        UniqueConstraint("platform_account_id", "proof_key", name="uq_platform_proof_run_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    platform_account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("platform_accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    capability_snapshot_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("platform_capability_snapshots.id", ondelete="SET NULL")
    )
    proof_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[PlatformProofStatus] = mapped_column(
        Enum(PlatformProofStatus, native_enum=False), nullable=False, default=PlatformProofStatus.CREATED
    )
    media_uri: Mapped[str] = mapped_column(Text, nullable=False)
    caption: Mapped[str] = mapped_column(Text, default="", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    platform_post_id: Mapped[str | None] = mapped_column(String(240))
    canonical_url: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    remote_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformProofEvent(Base):
    __tablename__ = "platform_proof_events"
    __table_args__ = (
        UniqueConstraint("proof_run_id", "sequence", name="uq_platform_proof_event_sequence"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    proof_run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("platform_proof_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sequence: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
