from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.enums import DecisionStatus


@dataclass(frozen=True)
class PolicyEvaluation:
    status: DecisionStatus
    rule_version: str
    reasons: tuple[str, ...]


class FoundationPolicyEngine:
    """Minimal Phase-1 safety gate, not a substitute for platform policy adapters.

    The engine only accepts content that has an explicit structured classification.
    Unknown classification fails closed. Later platform adapters may add stricter rules.
    """

    rule_version = "foundation-policy-v1"

    def evaluate(self, classification: dict[str, Any] | None) -> PolicyEvaluation:
        if not classification or classification.get("classified") is not True:
            return PolicyEvaluation(
                status=DecisionStatus.UNKNOWN,
                rule_version=self.rule_version,
                reasons=("missing_structured_policy_classification",),
            )

        reasons: list[str] = []
        if classification.get("fabricated_real_quote") is True:
            reasons.append("fabricated_real_quote")
        if classification.get("fake_real_event") is True:
            reasons.append("fake_real_event")
        if classification.get("evasion_intent") is True:
            reasons.append("platform_classification_evasion")

        return PolicyEvaluation(
            status=DecisionStatus.RESTRICTED if reasons else DecisionStatus.CLEAR,
            rule_version=self.rule_version,
            reasons=tuple(reasons),
        )
