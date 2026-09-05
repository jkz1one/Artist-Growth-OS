from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from app.domain.enums import DecisionStatus, RightsCategory


@dataclass(frozen=True)
class GrantEvidence:
    subject_type: str
    subject_id: str
    category: RightsCategory
    status: DecisionStatus
    platforms: tuple[str, ...] = ()
    starts_on: date | None = None
    expires_on: date | None = None


@dataclass(frozen=True)
class RightsEvaluation:
    status: DecisionStatus
    missing: tuple[str, ...]
    restricted: tuple[str, ...]
    expired: tuple[str, ...]


class RightsEngine:
    rule_version = "rights-v1"

    REQUIRED_TRACK = {
        RightsCategory.MASTER,
        RightsCategory.COMPOSITION,
        RightsCategory.AUDIOVISUAL_USE,
    }
    REQUIRED_ASSET = {
        RightsCategory.PROMOTIONAL_USE,
        RightsCategory.DERIVATIVE_EDIT,
    }

    def evaluate(
        self,
        *,
        track_id: str | None,
        asset_ids: Iterable[str],
        platform: str,
        grants: Iterable[GrantEvidence],
        today: date | None = None,
    ) -> RightsEvaluation:
        today = today or date.today()
        grants = tuple(grants)
        missing: list[str] = []
        restricted: list[str] = []
        expired: list[str] = []

        def check(subject_type: str, subject_id: str, categories: set[RightsCategory]) -> None:
            for category in categories:
                prefix = f"{subject_type}:{subject_id}:{category}"
                matches = [
                    grant
                    for grant in grants
                    if grant.subject_type == subject_type
                    and grant.subject_id == subject_id
                    and grant.category == category
                    and (not grant.platforms or platform in grant.platforms)
                ]
                if not matches:
                    missing.append(prefix)
                    continue

                # Any currently effective CLEAR grant satisfies this right. Old expired
                # agreements remain provenance, but do not poison a valid renewal.
                if any(
                    grant.status == DecisionStatus.CLEAR
                    and (grant.starts_on is None or grant.starts_on <= today)
                    and (grant.expires_on is None or grant.expires_on >= today)
                    for grant in matches
                ):
                    continue

                if any(grant.status == DecisionStatus.RESTRICTED for grant in matches):
                    restricted.append(f"{prefix}:RESTRICTED")
                    continue

                if any(grant.starts_on is not None and grant.starts_on > today for grant in matches):
                    restricted.append(f"{prefix}:NOT_YET_EFFECTIVE")
                    continue

                if any(
                    grant.status == DecisionStatus.EXPIRED
                    or (grant.expires_on is not None and grant.expires_on < today)
                    for grant in matches
                ):
                    expired.append(f"{prefix}:EXPIRED")
                    continue

                # A recorded UNKNOWN (or any non-clear state we do not understand)
                # remains UNKNOWN and therefore fails closed.
                missing.append(f"{prefix}:UNKNOWN")

        if track_id:
            check("TRACK", track_id, self.REQUIRED_TRACK)
        for asset_id in asset_ids:
            check("ASSET", asset_id, self.REQUIRED_ASSET)

        if restricted:
            status = DecisionStatus.RESTRICTED
        elif expired:
            status = DecisionStatus.EXPIRED
        elif missing:
            status = DecisionStatus.UNKNOWN
        else:
            status = DecisionStatus.CLEAR

        return RightsEvaluation(
            status=status,
            missing=tuple(missing),
            restricted=tuple(restricted),
            expired=tuple(expired),
        )
