from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.enums import DecisionStatus
from app.platforms.base import Publisher, PublishRequest, PublishResult
from app.rendering.ffmpeg import FFmpegRenderer
from app.rendering.qc import MediaQC
from app.schemas.rendering import DeterministicRenderPlan
from app.services.distinctness import DistinctnessEvaluation, FoundationDistinctnessEngine
from app.services.policy import FoundationPolicyEngine, PolicyEvaluation
from app.services.rights import GrantEvidence, RightsEngine, RightsEvaluation


@dataclass(frozen=True)
class SpineInput:
    candidate_id: str
    track_id: str | None
    asset_ids: tuple[str, ...]
    target_platform: str
    render_plan: DeterministicRenderPlan
    output_path: Path
    policy_classification: dict[str, Any]
    recent_render_plan_hashes: tuple[str, ...] = ()
    caption: str = ""


@dataclass(frozen=True)
class SpineResult:
    render_sha256: str
    qc_status: DecisionStatus
    rights: RightsEvaluation
    policy: PolicyEvaluation
    distinctness: DistinctnessEvaluation
    publication: PublishResult
    idempotency_key: str


class PublicationSpine:
    def __init__(
        self,
        *,
        publisher: Publisher,
        renderer: FFmpegRenderer | None = None,
        qc: MediaQC | None = None,
        rights: RightsEngine | None = None,
        policy: FoundationPolicyEngine | None = None,
        distinctness: FoundationDistinctnessEngine | None = None,
    ) -> None:
        self.publisher = publisher
        self.renderer = renderer or FFmpegRenderer()
        self.qc = qc or MediaQC()
        self.rights = rights or RightsEngine()
        self.policy = policy or FoundationPolicyEngine()
        self.distinctness = distinctness or FoundationDistinctnessEngine()

    def execute(self, data: SpineInput, grants: tuple[GrantEvidence, ...]) -> SpineResult:
        if self.publisher.platform != data.target_platform:
            raise ValueError("publisher/platform mismatch")

        rights = self.rights.evaluate(
            track_id=data.track_id,
            asset_ids=data.asset_ids,
            platform=data.target_platform,
            grants=grants,
        )
        if rights.status != DecisionStatus.CLEAR:
            raise PermissionError(f"rights gate failed closed: {rights.status}")

        policy = self.policy.evaluate(data.policy_classification)
        if policy.status != DecisionStatus.CLEAR:
            raise PermissionError(f"policy gate failed closed: {policy.status}")

        plan_hash = data.render_plan.stable_hash()
        distinctness = self.distinctness.evaluate(
            render_plan_hash=plan_hash,
            recent_render_plan_hashes=data.recent_render_plan_hashes,
        )
        if distinctness.status != DecisionStatus.CLEAR:
            raise PermissionError(f"distinctness gate failed closed: {distinctness.status}")

        render_sha = self.renderer.render(data.render_plan, data.output_path)
        qc_status, report = self.qc.inspect(
            data.output_path,
            width=data.render_plan.width,
            height=data.render_plan.height,
            expect_audio=data.render_plan.audio is not None,
        )
        if qc_status != DecisionStatus.CLEAR:
            raise RuntimeError(f"media QC failed: {report.get('checks', report)}")

        key_material = f"{data.candidate_id}:{data.target_platform}:{render_sha}"
        idempotency_key = hashlib.sha256(key_material.encode()).hexdigest()
        publication = self.publisher.publish(
            PublishRequest(
                candidate_id=data.candidate_id,
                media_path=data.output_path,
                idempotency_key=idempotency_key,
                caption=data.caption,
            )
        )
        return SpineResult(
            render_sha256=render_sha,
            qc_status=qc_status,
            rights=rights,
            policy=policy,
            distinctness=distinctness,
            publication=publication,
            idempotency_key=idempotency_key,
        )
