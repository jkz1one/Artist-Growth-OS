from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.domain.enums import CandidateStatus, DecisionStatus, PublicationStatus
from app.models.spine import Publication, Render
from app.platforms.base import Publisher, PublishRequest
from app.rendering.ffmpeg import FFmpegRenderer
from app.rendering.qc import MediaQC
from app.schemas.rendering import DeterministicRenderPlan
from app.services.distinctness import FoundationDistinctnessEngine
from app.services.policy import FoundationPolicyEngine
from app.services.publication_store import PublicationStore
from app.services.rights import RightsEngine
from app.services.source_lineage import verify_source_lineage


class PublicationRecoveryRequired(RuntimeError):
    """Raised when retrying could double-publish because remote acceptance is ambiguous."""


@dataclass(frozen=True)
class PersistentSpineInput:
    candidate_id: UUID
    artist_id: UUID
    concept_id: UUID
    audio_use_plan_id: UUID
    render_plan_id: UUID
    track_id: UUID | None
    asset_ids: tuple[UUID, ...]
    target_platform: str
    render_plan: DeterministicRenderPlan
    output_path: Path
    policy_classification: dict[str, Any]
    recent_render_plan_hashes: tuple[str, ...] = ()
    caption: str = ""
    lineage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PersistentSpineResult:
    candidate_id: UUID
    render_id: UUID
    publication_id: UUID
    platform_post_id: str | None
    publication_status: PublicationStatus
    canonical_url: str | None
    idempotency_key: str
    reused_publication: bool


class PersistentPublicationSpine:
    """Durable Phase-1 coordinator with fail-closed ambiguous-delivery recovery."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        publisher: Publisher,
        renderer: FFmpegRenderer | None = None,
        qc: MediaQC | None = None,
        rights: RightsEngine | None = None,
        policy: FoundationPolicyEngine | None = None,
        distinctness: FoundationDistinctnessEngine | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.publisher = publisher
        self.renderer = renderer or FFmpegRenderer()
        self.qc = qc or MediaQC()
        self.rights = rights or RightsEngine()
        self.policy = policy or FoundationPolicyEngine()
        self.distinctness = distinctness or FoundationDistinctnessEngine()
        self.store = PublicationStore(session_factory)

    def execute(self, data: PersistentSpineInput) -> PersistentSpineResult:
        if self.publisher.platform != data.target_platform:
            raise ValueError("publisher/platform mismatch")

        existing = self._existing_publication(data)
        if existing is not None:
            return existing

        verify_source_lineage(
            session_factory=self.session_factory,
            artist_id=data.artist_id,
            concept_id=data.concept_id,
            audio_use_plan_id=data.audio_use_plan_id,
            render_plan_id=data.render_plan_id,
            track_id=data.track_id,
            asset_ids=data.asset_ids,
            render_plan=data.render_plan,
        )
        candidate = self.store.ensure_candidate(
            candidate_id=data.candidate_id,
            artist_id=data.artist_id,
            concept_id=data.concept_id,
            audio_use_plan_id=data.audio_use_plan_id,
            target_platform=data.target_platform,
            lineage={
                **data.lineage,
                "render_plan_id": str(data.render_plan_id),
                "render_plan_hash": data.render_plan.stable_hash(),
            },
        )
        if candidate.status in {CandidateStatus.REJECTED, CandidateStatus.QUARANTINED}:
            raise PermissionError(f"candidate is not eligible: {candidate.status}")

        if candidate.status == CandidateStatus.ELIGIBLE and candidate.render_id is not None:
            render = self._load_render(candidate.render_id)
        else:
            self._evaluate_and_persist_gates(data)
            render = self._render_and_persist(data)

        return self._publish_reserved(data, render)

    def _existing_publication(self, data: PersistentSpineInput) -> PersistentSpineResult | None:
        publication = self.store.find_publication(data.candidate_id, data.target_platform)
        if publication is None:
            return None
        if publication.status == PublicationStatus.PUBLISHED:
            candidate = self.store.ensure_candidate(
                candidate_id=data.candidate_id,
                artist_id=data.artist_id,
                concept_id=data.concept_id,
                audio_use_plan_id=data.audio_use_plan_id,
                target_platform=data.target_platform,
                lineage=data.lineage,
            )
            if candidate.render_id is None:
                raise RuntimeError("published publication has no persisted render")
            return self._result(publication, candidate.render_id, reused=True)
        if publication.status in {
            PublicationStatus.UPLOADING,
            PublicationStatus.PROCESSING,
            PublicationStatus.RETRYABLE,
            PublicationStatus.QUARANTINED,
        }:
            raise PublicationRecoveryRequired(
                f"publication {publication.id} is {publication.status}; "
                "remote reconciliation required before retry"
            )
        return None

    def _evaluate_and_persist_gates(self, data: PersistentSpineInput) -> None:
        subject_ids = [*data.asset_ids]
        if data.track_id is not None:
            subject_ids.append(data.track_id)
        grants = self.store.load_grants(subject_ids)

        rights = self.rights.evaluate(
            track_id=str(data.track_id) if data.track_id else None,
            asset_ids=(str(asset_id) for asset_id in data.asset_ids),
            platform=data.target_platform,
            grants=grants,
        )
        policy = self.policy.evaluate(data.policy_classification)
        distinctness = self.distinctness.evaluate(
            render_plan_hash=data.render_plan.stable_hash(),
            recent_render_plan_hashes=data.recent_render_plan_hashes,
        )
        self.store.persist_gate_decisions(
            candidate_id=data.candidate_id,
            rights=rights,
            rights_rule_version=self.rights.rule_version,
            policy=policy,
            policy_rule_version=self.policy.rule_version,
            distinctness=distinctness,
            distinctness_rule_version=self.distinctness.rule_version,
        )

        if rights.status != DecisionStatus.CLEAR:
            raise PermissionError(f"rights gate failed closed: {rights.status}")
        if policy.status != DecisionStatus.CLEAR:
            raise PermissionError(f"policy gate failed closed: {policy.status}")
        if distinctness.status != DecisionStatus.CLEAR:
            raise PermissionError(f"distinctness gate failed closed: {distinctness.status}")

    def _render_and_persist(self, data: PersistentSpineInput) -> Render:
        render_sha = self.renderer.render(data.render_plan, data.output_path)
        qc_status, qc_report = self.qc.inspect(
            data.output_path,
            width=data.render_plan.width,
            height=data.render_plan.height,
            expect_audio=data.render_plan.audio is not None,
        )
        render = self.store.persist_render(
            candidate_id=data.candidate_id,
            render_plan_id=data.render_plan_id,
            artifact_uri=str(data.output_path),
            sha256=render_sha,
            qc_status=qc_status,
            qc_report=qc_report,
        )
        if qc_status != DecisionStatus.CLEAR:
            raise RuntimeError("media QC failed and candidate was quarantined")
        return render

    def _load_render(self, render_id: UUID) -> Render:
        render = self.store.load_render(render_id)
        if render is None:
            raise RuntimeError("eligible candidate references missing render")
        if render.qc_status != DecisionStatus.CLEAR:
            raise RuntimeError("eligible candidate references non-clear render")
        if not Path(render.artifact_uri).exists():
            raise RuntimeError("persisted render artifact is missing")
        return render

    def _publish_reserved(self, data: PersistentSpineInput, render: Render) -> PersistentSpineResult:
        key_material = f"{data.candidate_id}:{data.target_platform}:{render.sha256}"
        idempotency_key = hashlib.sha256(key_material.encode()).hexdigest()
        publication = self.store.reserve_publication(
            candidate_id=data.candidate_id,
            platform=data.target_platform,
            idempotency_key=idempotency_key,
        )
        if publication.status == PublicationStatus.PUBLISHED:
            return self._result(publication, render.id, reused=True)
        if publication.status != PublicationStatus.SCHEDULED:
            raise PublicationRecoveryRequired(
                f"publication {publication.id} is {publication.status}; refusing duplicate submission"
            )

        attempt = self.store.start_attempt(
            publication.id,
            self._request_fingerprint(data, idempotency_key),
        )
        try:
            result = self.publisher.publish(
                PublishRequest(
                    candidate_id=str(data.candidate_id),
                    media_path=Path(render.artifact_uri),
                    idempotency_key=idempotency_key,
                    caption=data.caption,
                )
            )
        except Exception as exc:
            self.store.quarantine_attempt(
                publication.id,
                attempt.id,
                f"{type(exc).__name__}: {exc}",
            )
            raise

        publication = self.store.complete_attempt(
            publication_id=publication.id,
            attempt_id=attempt.id,
            platform_post_id=result.platform_post_id,
            status=result.status,
            published_at=result.published_at,
            canonical_url=result.canonical_url,
        )
        return self._result(publication, render.id, reused=False)

    @staticmethod
    def _request_fingerprint(data: PersistentSpineInput, idempotency_key: str) -> str:
        payload = json.dumps(
            {
                "candidate_id": str(data.candidate_id),
                "platform": data.target_platform,
                "idempotency_key": idempotency_key,
                "caption": data.caption,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _result(publication: Publication, render_id: UUID, *, reused: bool) -> PersistentSpineResult:
        return PersistentSpineResult(
            candidate_id=publication.candidate_id,
            render_id=render_id,
            publication_id=publication.id,
            platform_post_id=publication.platform_post_id,
            publication_status=publication.status,
            canonical_url=publication.canonical_url,
            idempotency_key=publication.idempotency_key,
            reused_publication=reused,
        )
