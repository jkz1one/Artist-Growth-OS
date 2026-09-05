from datetime import date, timedelta

from app.domain.enums import DecisionStatus, RightsCategory
from app.services.rights import GrantEvidence, RightsEngine


def grant(subject_type: str, subject_id: str, category: RightsCategory, **kwargs) -> GrantEvidence:
    return GrantEvidence(
        subject_type=subject_type,
        subject_id=subject_id,
        category=category,
        status=kwargs.pop("status", DecisionStatus.CLEAR),
        **kwargs,
    )


def complete_grants() -> tuple[GrantEvidence, ...]:
    return (
        grant("TRACK", "t1", RightsCategory.MASTER),
        grant("TRACK", "t1", RightsCategory.COMPOSITION),
        grant("TRACK", "t1", RightsCategory.AUDIOVISUAL_USE),
        grant("ASSET", "a1", RightsCategory.PROMOTIONAL_USE),
        grant("ASSET", "a1", RightsCategory.DERIVATIVE_EDIT),
    )


def test_rights_clear_only_when_every_required_grant_is_clear() -> None:
    result = RightsEngine().evaluate(track_id="t1", asset_ids=["a1"], platform="FAKE", grants=complete_grants())
    assert result.status == DecisionStatus.CLEAR
    assert not result.missing


def test_missing_right_fails_closed_as_unknown() -> None:
    result = RightsEngine().evaluate(track_id="t1", asset_ids=["a1"], platform="FAKE", grants=complete_grants()[:-1])
    assert result.status == DecisionStatus.UNKNOWN
    assert any("DERIVATIVE_EDIT" in item for item in result.missing)


def test_expired_grant_is_reported_as_expired() -> None:
    grants = list(complete_grants())
    grants[-1] = grant(
        "ASSET",
        "a1",
        RightsCategory.DERIVATIVE_EDIT,
        expires_on=date.today() - timedelta(days=1),
    )
    result = RightsEngine().evaluate(track_id="t1", asset_ids=["a1"], platform="FAKE", grants=grants)
    assert result.status == DecisionStatus.EXPIRED
    assert any("EXPIRED" in item for item in result.expired)


def test_active_renewal_supersedes_expired_historical_grant() -> None:
    grants = list(complete_grants())
    grants.append(
        grant(
            "ASSET",
            "a1",
            RightsCategory.DERIVATIVE_EDIT,
            expires_on=date.today() - timedelta(days=30),
        )
    )
    result = RightsEngine().evaluate(track_id="t1", asset_ids=["a1"], platform="FAKE", grants=grants)
    assert result.status == DecisionStatus.CLEAR
