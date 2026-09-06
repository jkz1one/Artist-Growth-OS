from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.domain.enums import PublicationStatus
from app.models.spine import RenderPlan
from app.schemas.rendering import DeterministicRenderPlan, SourceClip
from app.workers.base import QuarantineJobError
from app.workers.publication import PublicationJobHandler


def make_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def install_fake_spine(monkeypatch, *, recovery: bool = False):
    module = types.ModuleType("app.services.persistent_spine")

    class PublicationRecoveryRequired(RuntimeError):
        pass

    class PersistentSpineInput:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class PersistentPublicationSpine:
        last_input = None

        def __init__(self, *, session_factory, publisher):
            self.session_factory = session_factory
            self.publisher = publisher

        def execute(self, data):
            type(self).last_input = data
            if recovery:
                raise PublicationRecoveryRequired("remote acceptance is ambiguous")
            return SimpleNamespace(
                candidate_id=data.candidate_id,
                render_id=uuid4(),
                publication_id=uuid4(),
                platform_post_id="fake_post",
                publication_status=PublicationStatus.PUBLISHED,
                canonical_url="https://fake.publisher.local/posts/fake_post",
                idempotency_key="publication-key",
                reused_publication=False,
            )

    module.PublicationRecoveryRequired = PublicationRecoveryRequired
    module.PersistentSpineInput = PersistentSpineInput
    module.PersistentPublicationSpine = PersistentPublicationSpine
    monkeypatch.setitem(sys.modules, "app.services.persistent_spine", module)
    return PersistentPublicationSpine


def build_payload(factory, tmp_path: Path):
    candidate_id = uuid4()
    artist_id = uuid4()
    concept_id = uuid4()
    audio_use_plan_id = uuid4()
    render_plan_id = uuid4()
    plan = DeterministicRenderPlan(
        width=360,
        height=640,
        duration_ms=1000,
        video=SourceClip(path=str(tmp_path / "source.mp4"), start_ms=0, end_ms=1100),
    )
    with factory() as session:
        session.add(
            RenderPlan(
                id=render_plan_id,
                concept_id=concept_id,
                audio_use_plan_id=audio_use_plan_id,
                version=1,
                plan_json=plan.model_dump(mode="json"),
                deterministic_hash=plan.stable_hash(),
            )
        )
        session.commit()
    return {
        "candidate_id": str(candidate_id),
        "artist_id": str(artist_id),
        "concept_id": str(concept_id),
        "audio_use_plan_id": str(audio_use_plan_id),
        "render_plan_id": str(render_plan_id),
        "track_id": None,
        "asset_ids": [str(uuid4())],
        "target_platform": "FAKE",
        "policy_classification": {"classified": True},
    }, candidate_id, render_plan_id


def test_publication_handler_owns_output_path(monkeypatch, tmp_path: Path) -> None:
    factory = make_factory()
    payload, candidate_id, render_plan_id = build_payload(factory, tmp_path)
    fake_spine = install_fake_spine(monkeypatch)
    render_root = tmp_path / "renders"
    handler = PublicationJobHandler(session_factory=factory, render_root=render_root)

    result = handler.handle(payload)

    assert result["outcome"] == "PUBLISHED"
    captured = fake_spine.last_input
    assert captured.output_path == render_root / str(candidate_id) / f"{render_plan_id}.mp4"
    assert captured.render_plan_id == render_plan_id


def test_publication_recovery_becomes_job_quarantine(monkeypatch, tmp_path: Path) -> None:
    factory = make_factory()
    payload, _, _ = build_payload(factory, tmp_path)
    install_fake_spine(monkeypatch, recovery=True)
    handler = PublicationJobHandler(session_factory=factory, render_root=tmp_path / "renders")

    with pytest.raises(QuarantineJobError, match="ambiguous"):
        handler.handle(payload)
