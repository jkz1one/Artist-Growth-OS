from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.domain.enums import PlatformProofStatus
from app.models.platform_proof import (
    PlatformAccount,
    PlatformCapabilitySnapshot,
    PlatformProofEvent,
    PlatformProofRun,
)
from app.services.proof_inspector import ProofInspector
from app.services.proof_security import UnsafeEvidenceError


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def seed_run(
    session_factory,
    *,
    platform="INSTAGRAM",
    status=PlatformProofStatus.READY,
    proof_key="proof-1",
    created_at=None,
    active=True,
    media_uri="https://media.example.com/proof.mp4",
    with_snapshot=True,
    snapshot_evidence=None,
):
    created_at = created_at or datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    with session_factory() as session:
        account = PlatformAccount(
            platform=platform,
            external_account_id=f"{platform.lower()}-acct-{proof_key}",
            display_name=f"{platform} Proof",
            account_type="BUSINESS",
            api_family=f"{platform.lower()}-proof-v1",
            active=active,
            created_at=created_at,
        )
        session.add(account)
        session.flush()

        snapshot = None
        if with_snapshot:
            snapshot = PlatformCapabilitySnapshot(
                platform_account_id=account.id,
                api_family=account.api_family,
                api_version="v1",
                capabilities={"can_publish_video": "SUPPORTED"},
                evidence=snapshot_evidence or {"source": "test"},
                captured_at=created_at,
            )
            session.add(snapshot)
            session.flush()

        run = PlatformProofRun(
            platform_account_id=account.id,
            capability_snapshot_id=snapshot.id if snapshot else None,
            proof_key=proof_key,
            status=status,
            media_uri=media_uri,
            caption="proof caption",
            idempotency_key=f"proof:{account.id}:{proof_key}",
            remote_context={"stage": "SAFE"},
            created_at=created_at,
        )
        session.add(run)
        session.flush()

        session.add_all(
            [
                PlatformProofEvent(
                    proof_run_id=run.id,
                    sequence=2,
                    event_type="SECOND",
                    payload={"value": 2},
                    created_at=created_at + timedelta(seconds=2),
                ),
                PlatformProofEvent(
                    proof_run_id=run.id,
                    sequence=1,
                    event_type="FIRST",
                    payload={"value": 1},
                    created_at=created_at + timedelta(seconds=1),
                ),
            ]
        )
        session.commit()
        return run.id, account.id


def test_inspect_run_reconstructs_account_capabilities_and_ordered_timeline(session_factory):
    run_id, account_id = seed_run(session_factory)

    result = ProofInspector(session_factory).inspect_run(run_id)

    assert result["id"] == str(run_id)
    assert result["platform_account_id"] == str(account_id)
    assert result["platform"] == "INSTAGRAM"
    assert result["capability_snapshot"]["capabilities"]["can_publish_video"] == "SUPPORTED"
    assert [event["sequence"] for event in result["events"]] == [1, 2]
    assert [event["event_type"] for event in result["events"]] == ["FIRST", "SECOND"]
    assert result["attention"]["state"] == "READY_FOR_GUARDED_PUBLISH"
    assert result["attention"]["read_only"] is True


def test_list_runs_is_newest_first_and_filters_platform_and_status(session_factory):
    older = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    newer = datetime(2026, 9, 6, 13, 0, tzinfo=UTC)
    old_id, _ = seed_run(
        session_factory,
        platform="INSTAGRAM",
        status=PlatformProofStatus.PASSED,
        proof_key="old",
        created_at=older,
    )
    new_id, _ = seed_run(
        session_factory,
        platform="TIKTOK",
        status=PlatformProofStatus.RECOVERY_REQUIRED,
        proof_key="new",
        created_at=newer,
    )

    inspector = ProofInspector(session_factory)
    runs = inspector.list_runs()
    assert [item["id"] for item in runs] == [str(new_id), str(old_id)]

    filtered = inspector.list_runs(
        platform="TIKTOK",
        status=PlatformProofStatus.RECOVERY_REQUIRED,
    )
    assert [item["id"] for item in filtered] == [str(new_id)]


def test_historical_inactive_account_remains_visible(session_factory):
    run_id, _ = seed_run(session_factory, active=False)

    result = ProofInspector(session_factory).inspect_run(run_id)

    assert result["id"] == str(run_id)
    assert result["account_active"] is False


def test_missing_capability_snapshot_is_explicitly_none(session_factory):
    run_id, _ = seed_run(
        session_factory,
        status=PlatformProofStatus.CREATED,
        with_snapshot=False,
    )

    result = ProofInspector(session_factory).inspect_run(run_id)

    assert result["capability_snapshot"] is None
    assert result["attention"]["state"] == "SETUP_REQUIRED"


@pytest.mark.parametrize(
    ("status", "expected_state", "actions"),
    [
        (PlatformProofStatus.CREATED, "SETUP_REQUIRED", ["SHOW"]),
        (
            PlatformProofStatus.READY,
            "READY_FOR_GUARDED_PUBLISH",
            ["SHOW", "PUBLISH_GUARDED"],
        ),
        (
            PlatformProofStatus.PUBLISHING,
            "RECONCILIATION_REQUIRED",
            ["SHOW", "RECONCILE"],
        ),
        (
            PlatformProofStatus.PUBLISHED,
            "METRICS_PENDING",
            ["SHOW", "RECONCILE", "METRICS"],
        ),
        (PlatformProofStatus.MEASURING, "MEASURING", ["SHOW"]),
        (PlatformProofStatus.PASSED, "COMPLETE", ["SHOW"]),
        (PlatformProofStatus.FAILED, "FAILED", ["SHOW"]),
        (
            PlatformProofStatus.RECOVERY_REQUIRED,
            "RECOVERY_REQUIRED",
            ["SHOW", "RECONCILE"],
        ),
    ],
)
def test_attention_projection_is_read_only(status, expected_state, actions):
    attention = ProofInspector._attention(status)

    assert attention["state"] == expected_state
    assert attention["available_actions"] == actions
    assert attention["read_only"] is True


@pytest.mark.parametrize("limit", [0, 201])
def test_list_limit_is_bounded(session_factory, limit):
    with pytest.raises(ValueError, match="between 1 and 200"):
        ProofInspector(session_factory).list_runs(limit=limit)


def test_unknown_run_fails_explicitly(session_factory):
    with pytest.raises(RuntimeError, match="proof run not found"):
        ProofInspector(session_factory).inspect_run(uuid4())


def test_unsafe_capability_evidence_is_never_projected(session_factory):
    run_id, _ = seed_run(
        session_factory,
        snapshot_evidence={"access_token": "should-never-be-shown"},
    )

    with pytest.raises(UnsafeEvidenceError):
        ProofInspector(session_factory).inspect_run(run_id)


def test_credential_bearing_legacy_media_uri_is_never_listed(session_factory):
    seed_run(
        session_factory,
        media_uri="https://media.example.com/proof.mp4?access_token=secret",
    )

    with pytest.raises(UnsafeEvidenceError):
        ProofInspector(session_factory).list_runs()
