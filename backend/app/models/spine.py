from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums import (
    AudioStrategy,
    CandidateStatus,
    DecisionStatus,
    PublicationStatus,
    RightsCategory,
    SeedMode,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class UUIDTimestampMixin:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Artist(UUIDTimestampMixin, Base):
    __tablename__ = "artists"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    creative_profile: Mapped[ArtistCreativeProfile | None] = relationship(back_populates="artist", uselist=False)


class ArtistCreativeProfile(UUIDTimestampMixin, Base):
    __tablename__ = "artist_creative_profiles"

    artist_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("artists.id", ondelete="CASCADE"), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    hard_rules: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    descriptors: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    artist: Mapped[Artist] = relationship(back_populates="creative_profile")


class Track(UUIDTimestampMixin, Base):
    __tablename__ = "tracks"

    artist_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)


class TrackSegment(UUIDTimestampMixin, Base):
    __tablename__ = "track_segments"
    __table_args__ = (UniqueConstraint("track_id", "segment_key", name="uq_track_segment_key"),)

    track_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tracks.id", ondelete="CASCADE"), index=True)
    segment_key: Mapped[str] = mapped_column(String(32), nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class RightsGrant(UUIDTimestampMixin, Base):
    __tablename__ = "rights_grants"

    subject_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    subject_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    category: Mapped[RightsCategory] = mapped_column(Enum(RightsCategory, native_enum=False), nullable=False)
    status: Mapped[DecisionStatus] = mapped_column(Enum(DecisionStatus, native_enum=False), nullable=False)
    grantor: Mapped[str] = mapped_column(String(240), nullable=False)
    platforms: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    territories: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    starts_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date)
    restrictions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source_reference: Mapped[str | None] = mapped_column(Text)


class Asset(UUIDTimestampMixin, Base):
    __tablename__ = "assets"

    artist_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    media_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)


class SeedPost(UUIDTimestampMixin, Base):
    __tablename__ = "seed_posts"

    artist_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("assets.id", ondelete="RESTRICT"))
    track_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("tracks.id", ondelete="SET NULL"))
    mode: Mapped[SeedMode] = mapped_column(Enum(SeedMode, native_enum=False), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    learn_from_this: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    create_derivatives: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    gold_reference: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fingerprint: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class CreativeConcept(UUIDTimestampMixin, Base):
    __tablename__ = "creative_concepts"

    artist_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    seed_post_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("seed_posts.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    concept_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    generator_name: Mapped[str] = mapped_column(String(120), default="human-or-rule", nullable=False)
    generator_version: Mapped[str] = mapped_column(String(80), default="v1", nullable=False)


class AudioUsePlan(UUIDTimestampMixin, Base):
    __tablename__ = "audio_use_plans"

    artist_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("tracks.id", ondelete="RESTRICT"))
    track_segment_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("track_segments.id", ondelete="RESTRICT"))
    strategy: Mapped[AudioStrategy] = mapped_column(Enum(AudioStrategy, native_enum=False), nullable=False)
    target_platform: Mapped[str | None] = mapped_column(String(40))
    expected_claim_behavior: Mapped[str | None] = mapped_column(Text)
    platform_sound_ref: Mapped[str | None] = mapped_column(Text)


class RenderPlan(UUIDTimestampMixin, Base):
    __tablename__ = "render_plans"

    concept_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("creative_concepts.id", ondelete="CASCADE"), index=True)
    audio_use_plan_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("audio_use_plans.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    deterministic_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class Render(UUIDTimestampMixin, Base):
    __tablename__ = "renders"
    __table_args__ = (UniqueConstraint("render_plan_id", "sha256", name="uq_render_plan_artifact"),)

    render_plan_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("render_plans.id", ondelete="CASCADE"), index=True)
    artifact_uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    qc_status: Mapped[DecisionStatus] = mapped_column(Enum(DecisionStatus, native_enum=False), nullable=False)
    qc_report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Candidate(UUIDTimestampMixin, Base):
    __tablename__ = "candidates"

    artist_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("creative_concepts.id", ondelete="RESTRICT"))
    render_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("renders.id", ondelete="RESTRICT"), nullable=True)
    audio_use_plan_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("audio_use_plans.id", ondelete="RESTRICT"))
    status: Mapped[CandidateStatus] = mapped_column(Enum(CandidateStatus, native_enum=False), nullable=False)
    target_platform: Mapped[str] = mapped_column(String(40), nullable=False)
    lineage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class RightsDecision(UUIDTimestampMixin, Base):
    __tablename__ = "rights_decisions"
    __table_args__ = (UniqueConstraint("candidate_id", "rule_version", name="uq_rights_decision_rule"),)

    candidate_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    status: Mapped[DecisionStatus] = mapped_column(Enum(DecisionStatus, native_enum=False), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(80), default="rights-v1", nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class PolicyDecision(UUIDTimestampMixin, Base):
    __tablename__ = "policy_decisions"
    __table_args__ = (UniqueConstraint("candidate_id", "rule_version", name="uq_policy_decision_rule"),)

    candidate_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    status: Mapped[DecisionStatus] = mapped_column(Enum(DecisionStatus, native_enum=False), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(80), default="policy-v1", nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class DistinctnessDecision(UUIDTimestampMixin, Base):
    __tablename__ = "distinctness_decisions"
    __table_args__ = (UniqueConstraint("candidate_id", "rule_version", name="uq_distinctness_decision_rule"),)

    candidate_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    status: Mapped[DecisionStatus] = mapped_column(Enum(DecisionStatus, native_enum=False), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(80), default="foundation-distinctness-v1", nullable=False)
    novelty_score: Mapped[float] = mapped_column(Float, nullable=False)
    semantic_similarity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    visual_similarity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    audio_overlap: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Publication(UUIDTimestampMixin, Base):
    __tablename__ = "publications"
    __table_args__ = (
        UniqueConstraint("platform", "idempotency_key", name="uq_publication_idempotency"),
        UniqueConstraint("candidate_id", "platform", name="uq_candidate_platform_publication"),
    )

    candidate_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("candidates.id", ondelete="RESTRICT"), index=True)
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    platform_post_id: Mapped[str | None] = mapped_column(String(240))
    status: Mapped[PublicationStatus] = mapped_column(Enum(PublicationStatus, native_enum=False), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canonical_url: Mapped[str | None] = mapped_column(Text)


class PublicationAttempt(UUIDTimestampMixin, Base):
    __tablename__ = "publication_attempts"
    __table_args__ = (UniqueConstraint("publication_id", "attempt_number", name="uq_publication_attempt"),)

    publication_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("publications.id", ondelete="CASCADE"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[PublicationStatus] = mapped_column(Enum(PublicationStatus, native_enum=False), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
