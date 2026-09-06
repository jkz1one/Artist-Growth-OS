from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.domain.enums import (
    AudioStrategy,
    CandidateStatus,
    DecisionStatus,
    PublicationStatus,
    RightsCategory,
)
from app.models.spine import (
    Artist,
    Asset,
    AudioUsePlan,
    Candidate,
    CreativeConcept,
    DistinctnessDecision,
    PolicyDecision,
    Publication,
    PublicationAttempt,
    Render,
    RenderPlan,
    RightsDecision,
    RightsGrant,
    Track,
    TrackSegment,
)
from app.platforms.base import PublishRequest, PublishResult
from app.schemas.rendering import AudioSlice, DeterministicRenderPlan, SourceClip
from app.services.persistent_spine import (
    PersistentPublicationSpine,
    PersistentSpineInput,
    PublicationRecoveryRequired,
)


class RecordingPublisher:
    platform = "FAKE"

    def __init__(self) -> None:
        self.calls = 0

    def publish(self, request: PublishRequest) -> PublishResult:
        self.calls += 1
        return PublishResult(
            platform_post_id=f"remote-{request.idempotency_key[:12]}",
            status=PublicationStatus.PUBLISHED,
            published_at=datetime.now(UTC),
            canonical_url=f"https://fake.publisher.local/{request.idempotency_key[:12]}",
        )


def make_fixture_media(tmp_path: Path) -> tuple[Path, Path]:
    video = tmp_path / "source.mp4"
    audio = tmp_path / "track.wav"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=30",
            "-t", "1.2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "1.2", str(audio),
        ],
        check=True,
    )
    return video, audio


def db_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'spine.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def seed_domain(factory: sessionmaker[Session], plan: DeterministicRenderPlan) -> dict[str, UUID]:
    ids = {name: uuid4() for name in ["artist", "track", "segment", "asset", "concept", "audio", "render_plan", "candidate"]}
    with factory() as session:
        session.add(Artist(id=ids["artist"], name="Artist A", slug=f"artist-{ids['artist'].hex[:8]}"))
        session.add(
            Track(
                id=ids["track"],
                artist_id=ids["artist"],
                title="Track 1",
                duration_ms=180000,
                source_uri="private://track-1.wav",
            )
        )
        session.add(
            TrackSegment(
                id=ids["segment"],
                track_id=ids["track"],
                segment_key="S01",
                start_ms=0,
                end_ms=1000,
                features={},
            )
        )
        session.add(
            Asset(
                id=ids["asset"],
                artist_id=ids["artist"],
                media_type="VIDEO",
                source_uri="private://source.mp4",
                sha256="a" * 64,
                duration_ms=1200,
                metadata_json={},
            )
        )
        session.add(
            CreativeConcept(
                id=ids["concept"],
                artist_id=ids["artist"],
                title="Foundation test",
                concept_json={"hook": "test"},
            )
        )
        session.add(
            AudioUsePlan(
                id=ids["audio"],
                artist_id=ids["artist"],
                track_id=ids["track"],
                track_segment_id=ids["segment"],
                strategy=AudioStrategy.BAKED_AUDIO,
                target_platform="FAKE",
            )
        )
        session.add(
            RenderPlan(
                id=ids["render_plan"],
                concept_id=ids["concept"],
                audio_use_plan_id=ids["audio"],
                version=1,
                plan_json=plan.model_dump(mode="json"),
                deterministic_hash=plan.stable_hash(),
            )
        )
        for subject_type, subject_id, categories in (
            (
                "TRACK",
                ids["track"],
                (RightsCategory.MASTER, RightsCategory.COMPOSITION, RightsCategory.AUDIOVISUAL_USE),
            ),
            (
                "ASSET",
                ids["asset"],
                (RightsCategory.PROMOTIONAL_USE, RightsCategory.DERIVATIVE_EDIT),
            ),
        ):
            for category in categories:
                session.add(
                    RightsGrant(
                        subject_type=subject_type,
                        subject_id=subject_id,
                        category=category,
                        status=DecisionStatus.CLEAR,
                        grantor="test-rightsholder",
                        platforms=["FAKE"],
                        territories=["US"],
                        restrictions={},
                    )
                )
        session.commit()
    return ids


def build_input(tmp_path: Path, ids: dict[str, UUID], plan: DeterministicRenderPlan) -> PersistentSpineInput:
    return PersistentSpineInput(
        candidate_id=ids["candidate"],
        artist_id=ids["artist"],
        concept_id=ids["concept"],
        audio_use_plan_id=ids["audio"],
        render_plan_id=ids["render_plan"],
        track_id=ids["track"],
        asset_ids=(ids["asset"],),
        target_platform="FAKE",
        render_plan=plan,
        output_path=tmp_path / "published.mp4",
        policy_classification={"classified": True},
        lineage={"test": True},
    )


def setup_case(tmp_path: Path) -> tuple[sessionmaker[Session], PersistentSpineInput]:
    video, audio = make_fixture_media(tmp_path)
    plan = DeterministicRenderPlan(
        width=360,
        height=640,
        duration_ms=1000,
        video=SourceClip(path=str(video), start_ms=0, end_ms=1100),
        audio=AudioSlice(path=str(audio), start_ms=0, end_ms=1100),
    )
    factory = db_factory(tmp_path)
    ids = seed_domain(factory, plan)
    return factory, build_input(tmp_path, ids, plan)


def test_persistent_loop_survives_service_restart_without_republishing(tmp_path: Path) -> None:
    factory, data = setup_case(tmp_path)
    first_publisher = RecordingPublisher()
    first = PersistentPublicationSpine(session_factory=factory, publisher=first_publisher).execute(data)

    assert first_publisher.calls == 1
    assert first.publication_status == PublicationStatus.PUBLISHED
    assert first.reused_publication is False

    second_publisher = RecordingPublisher()
    second = PersistentPublicationSpine(session_factory=factory, publisher=second_publisher).execute(data)

    assert second_publisher.calls == 0
    assert second.reused_publication is True
    assert second.publication_id == first.publication_id
    assert second.platform_post_id == first.platform_post_id

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Candidate)) == 1
        assert session.scalar(select(func.count()).select_from(RightsDecision)) == 1
        assert session.scalar(select(func.count()).select_from(PolicyDecision)) == 1
        assert session.scalar(select(func.count()).select_from(DistinctnessDecision)) == 1
        assert session.scalar(select(func.count()).select_from(Render)) == 1
        assert session.scalar(select(func.count()).select_from(Publication)) == 1
        assert session.scalar(select(func.count()).select_from(PublicationAttempt)) == 1


def test_missing_right_is_persisted_as_rejected_before_render(tmp_path: Path) -> None:
    factory, data = setup_case(tmp_path)
    with factory() as session:
        grant = session.scalar(
            select(RightsGrant).where(RightsGrant.category == RightsCategory.DERIVATIVE_EDIT)
        )
        assert grant is not None
        session.delete(grant)
        session.commit()

    publisher = RecordingPublisher()
    with pytest.raises(PermissionError, match="rights gate failed closed"):
        PersistentPublicationSpine(session_factory=factory, publisher=publisher).execute(data)

    assert publisher.calls == 0
    assert not data.output_path.exists()
    with factory() as session:
        candidate = session.get(Candidate, data.candidate_id)
        assert candidate is not None
        assert candidate.status == CandidateStatus.REJECTED
        assert candidate.render_id is None
        decision = session.scalar(select(RightsDecision).where(RightsDecision.candidate_id == data.candidate_id))
        assert decision is not None
        assert decision.status == DecisionStatus.UNKNOWN
        assert session.scalar(select(func.count()).select_from(Render)) == 0
        assert session.scalar(select(func.count()).select_from(Publication)) == 0


def test_ambiguous_uploading_state_never_blindly_republishes(tmp_path: Path) -> None:
    factory, data = setup_case(tmp_path)
    first_publisher = RecordingPublisher()
    first = PersistentPublicationSpine(session_factory=factory, publisher=first_publisher).execute(data)
    assert first_publisher.calls == 1

    with factory() as session:
        publication = session.get(Publication, first.publication_id)
        assert publication is not None
        publication.status = PublicationStatus.UPLOADING
        publication.platform_post_id = None
        publication.canonical_url = None
        session.commit()

    restart_publisher = RecordingPublisher()
    with pytest.raises(PublicationRecoveryRequired, match="remote reconciliation required"):
        PersistentPublicationSpine(session_factory=factory, publisher=restart_publisher).execute(data)
    assert restart_publisher.calls == 0


def test_cross_artist_asset_is_rejected_before_candidate_creation(tmp_path: Path) -> None:
    factory, data = setup_case(tmp_path)
    other_artist_id = uuid4()
    other_asset_id = uuid4()
    with factory() as session:
        session.add(Artist(id=other_artist_id, name="Artist B", slug=f"artist-{other_artist_id.hex[:8]}"))
        session.add(
            Asset(
                id=other_asset_id,
                artist_id=other_artist_id,
                media_type="VIDEO",
                source_uri="private://other.mp4",
                sha256="b" * 64,
                duration_ms=1200,
                metadata_json={},
            )
        )
        session.commit()

    bad = PersistentSpineInput(
        candidate_id=data.candidate_id,
        artist_id=data.artist_id,
        concept_id=data.concept_id,
        audio_use_plan_id=data.audio_use_plan_id,
        render_plan_id=data.render_plan_id,
        track_id=data.track_id,
        asset_ids=(other_asset_id,),
        target_platform=data.target_platform,
        render_plan=data.render_plan,
        output_path=data.output_path,
        policy_classification=data.policy_classification,
    )
    publisher = RecordingPublisher()
    with pytest.raises(ValueError, match="asset does not belong"):
        PersistentPublicationSpine(session_factory=factory, publisher=publisher).execute(bad)
    assert publisher.calls == 0
    with factory() as session:
        assert session.get(Candidate, data.candidate_id) is None
