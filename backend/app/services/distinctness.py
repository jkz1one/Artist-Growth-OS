from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import DecisionStatus


@dataclass(frozen=True)
class DistinctnessEvaluation:
    status: DecisionStatus
    novelty_score: float
    reasons: tuple[str, ...]


class FoundationDistinctnessEngine:
    """Phase-1 exact-plan guard.

    Embedding/perceptual similarity comes later. This gate already prevents an exact
    RenderPlan fingerprint from being treated as materially new.
    """

    rule_version = "foundation-distinctness-v1"

    def evaluate(self, *, render_plan_hash: str, recent_render_plan_hashes: tuple[str, ...]) -> DistinctnessEvaluation:
        if render_plan_hash in recent_render_plan_hashes:
            return DistinctnessEvaluation(
                status=DecisionStatus.RESTRICTED,
                novelty_score=0.0,
                reasons=("exact_render_plan_duplicate",),
            )
        return DistinctnessEvaluation(
            status=DecisionStatus.CLEAR,
            novelty_score=1.0,
            reasons=(),
        )
