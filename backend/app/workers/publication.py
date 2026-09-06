from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.models.spine import RenderPlan
from app.platforms.base import Publisher
from app.platforms.fake import FakePublisher
from app.schemas.jobs import PublicationJobCommand
from app.schemas.rendering import DeterministicRenderPlan
from app.workers.base import FatalJobError, QuarantineJobError

PublisherResolver = Callable[[str], Publisher]


class PublicationJobHandler:
    """Resolve a persisted render plan and execute the durable publication spine."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        render_root: Path,
        publisher_resolver: PublisherResolver | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.render_root = render_root
        self._fake_publisher = FakePublisher()
        self.publisher_resolver = publisher_resolver or self._default_publisher_resolver

    def handle(self, payload: dict[str, object]) -> dict[str, object]:
        try:
            command = PublicationJobCommand.model_validate(payload)
        except ValidationError as exc:
            raise FatalJobError(f"invalid publication job payload: {exc}") from exc

        plan = self._load_render_plan(command.render_plan_id)
        output_path = (
            self.render_root
            / str(command.candidate_id)
            / f"{command.render_plan_id}.mp4"
        )
        publisher = self.publisher_resolver(command.target_platform)

        # Lazy import keeps the generic job subsystem independent of platform-spine internals.
        from app.services.persistent_spine import (
            PersistentPublicationSpine,
            PersistentSpineInput,
            PublicationRecoveryRequired,
        )

        spine = PersistentPublicationSpine(
            session_factory=self.session_factory,
            publisher=publisher,
        )
        try:
            result = spine.execute(
                PersistentSpineInput(
                    candidate_id=command.candidate_id,
                    artist_id=command.artist_id,
                    concept_id=command.concept_id,
                    audio_use_plan_id=command.audio_use_plan_id,
                    render_plan_id=command.render_plan_id,
                    track_id=command.track_id,
                    asset_ids=command.asset_ids,
                    target_platform=command.target_platform,
                    render_plan=plan,
                    output_path=output_path,
                    policy_classification=command.policy_classification,
                    recent_render_plan_hashes=command.recent_render_plan_hashes,
                    caption=command.caption,
                    lineage=command.lineage,
                )
            )
        except PublicationRecoveryRequired as exc:
            raise QuarantineJobError(str(exc)) from exc
        except PermissionError as exc:
            # A gate rejection is a completed business outcome, not a worker fault.
            return {
                "outcome": "REJECTED",
                "candidate_id": str(command.candidate_id),
                "reason": str(exc),
            }
        except (ValueError, FileNotFoundError) as exc:
            raise FatalJobError(str(exc)) from exc

        return {
            "outcome": "PUBLISHED",
            "candidate_id": str(result.candidate_id),
            "render_id": str(result.render_id),
            "publication_id": str(result.publication_id),
            "platform_post_id": result.platform_post_id,
            "publication_status": result.publication_status.value,
            "canonical_url": result.canonical_url,
            "idempotency_key": result.idempotency_key,
            "reused_publication": result.reused_publication,
        }

    def _load_render_plan(self, render_plan_id) -> DeterministicRenderPlan:
        with self.session_factory() as session:
            persisted = session.get(RenderPlan, render_plan_id)
            if persisted is None:
                raise FatalJobError("persisted render plan is missing")
            try:
                plan = DeterministicRenderPlan.model_validate(persisted.plan_json)
            except ValidationError as exc:
                raise FatalJobError(f"persisted render plan is invalid: {exc}") from exc
            if persisted.deterministic_hash != plan.stable_hash():
                raise FatalJobError("persisted render plan hash does not match payload")
            return plan

    def _default_publisher_resolver(self, platform: str) -> Publisher:
        if platform == self._fake_publisher.platform:
            return self._fake_publisher
        raise FatalJobError(f"no publisher adapter registered for platform {platform}")
