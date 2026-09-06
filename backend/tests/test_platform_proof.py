from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.domain.enums import CapabilitySupport, PlatformProofStatus
from app.models.platform_proof import PlatformProofEvent
from app.platforms.proof.base import CapabilityReport
from app.platforms.proof.fake import FakePlatformProofAdapter
from app.services.platform_proof import (
    PlatformProofHarness,
    ProofRecoveryRequired,
    ProofStateError,
    UnsafeEvidenceError,
    ensure_safe_evidence,
)


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture()
def proof(session_factory):
    harness = PlatformProofHarness(session_factory)
    adapter = FakePlatformProofAdapter()
    account = harness.create_account(
        platform="FAKE",
        external_account_id="acct-1",
        api_family=adapter.api_family,
        display_name="Proof Account",
    )
    run = harness.start_run(
        platform_account_id=account.id,
        proof_key="proof-001",
        media_uri="https://media.example.com/proof.mp4",
        caption="proof",
    )
    return harness, adapter, account, run


def test_full_proof_contract_passes_once(proof):
    harness, adapter, _, run = proof
    snapshot = harness.capture_capabilities(run.id, adapter)
    assert snapshot.capabilities["can_publish_video"] == "SUPPORTED"

    published = harness.publish_once(run.id, adapter)
    assert published.status == PlatformProofStatus.PUBLISHED
    assert adapter.publish_calls == 1

    reconciled = harness.reconcile(run.id, adapter)
    assert reconciled.status == PlatformProofStatus.PUBLISHED

    measured = harness.collect_metrics(run.id, adapter)
    assert measured.status == PlatformProofStatus.PASSED
    assert measured.result_json["metrics"]["views"] == 100
    assert adapter.publish_calls == 1


def test_start_run_is_idempotent_but_payload_mismatch_conflicts(proof):
    harness, _, account, run = proof
    reused = harness.start_run(
        platform_account_id=account.id,
        proof_key="proof-001",
        media_uri=run.media_uri,
        caption=run.caption,
    )
    assert reused.id == run.id

    with pytest.raises(ValueError, match="different proof input"):
        harness.start_run(
            platform_account_id=account.id,
            proof_key="proof-001",
            media_uri="https://media.example.com/different.mp4",
        )


def test_capability_refresh_cannot_reopen_published_run(proof):
    harness, adapter, _, run = proof
    harness.capture_capabilities(run.id, adapter)
    harness.publish_once(run.id, adapter)

    with pytest.raises(ProofStateError, match="before remote publication"):
        harness.capture_capabilities(run.id, adapter)
    assert adapter.publish_calls == 1


def test_metrics_failure_is_retryable_without_republish(proof):
    harness, adapter, _, run = proof
    harness.capture_capabilities(run.id, adapter)
    harness.publish_once(run.id, adapter)
    adapter.fail_metrics_once = True

    with pytest.raises(RuntimeError, match="metrics temporarily unavailable"):
        harness.collect_metrics(run.id, adapter)
    assert harness.get_run(run.id).status == PlatformProofStatus.PUBLISHED
    assert adapter.publish_calls == 1

    measured = harness.collect_metrics(run.id, adapter)
    assert measured.status == PlatformProofStatus.PASSED
    assert adapter.publish_calls == 1
    assert adapter.metric_calls == 2


def test_receipt_persistence_failure_requires_reconciliation(proof, monkeypatch):
    harness, adapter, _, run = proof
    harness.capture_capabilities(run.id, adapter)

    def explode(*args, **kwargs):
        raise RuntimeError("database unavailable after remote accept")

    monkeypatch.setattr(harness, "_persist_publish_receipt", explode)
    with pytest.raises(ProofRecoveryRequired):
        harness.publish_once(run.id, adapter)

    persisted = harness.get_run(run.id)
    assert persisted.status == PlatformProofStatus.RECOVERY_REQUIRED
    assert adapter.publish_calls == 1
    with pytest.raises(ProofStateError):
        harness.publish_once(run.id, adapter)
    assert adapter.publish_calls == 1


def test_unsupported_publish_capability_blocks_remote_call(proof):
    harness, adapter, _, run = proof

    def unsupported(_external_account_id: str):
        return CapabilityReport(
            api_family=adapter.api_family,
            api_version="v1",
            capabilities={"can_publish_video": CapabilitySupport.UNSUPPORTED},
            evidence={"source": "test"},
        )

    adapter.inspect_capabilities = unsupported  # type: ignore[method-assign]
    harness.capture_capabilities(run.id, adapter)
    with pytest.raises(ProofStateError, match="has not been proven supported"):
        harness.publish_once(run.id, adapter)
    assert adapter.publish_calls == 0


def test_adapter_identity_must_match_account(proof):
    harness, adapter, _, run = proof
    adapter.platform = "OTHER"
    with pytest.raises(ValueError, match="adapter platform"):
        harness.capture_capabilities(run.id, adapter)


@pytest.mark.parametrize(
    "evidence",
    [
        {"access_token": "abc"},
        {"nested": {"Authorization": "Bearer abc"}},
        {"url": "https://example.com/callback?access_token=abc"},
        {"header": "Bearer abc"},
    ],
)
def test_secret_bearing_evidence_is_rejected(evidence):
    with pytest.raises(UnsafeEvidenceError):
        ensure_safe_evidence(evidence)


def test_proof_events_are_monotonic_and_unique(proof, session_factory):
    harness, adapter, _, run = proof
    harness.capture_capabilities(run.id, adapter)
    harness.publish_once(run.id, adapter)
    harness.collect_metrics(run.id, adapter)

    with session_factory() as session:
        events = session.scalars(
            select(PlatformProofEvent)
            .where(PlatformProofEvent.proof_run_id == run.id)
            .order_by(PlatformProofEvent.sequence)
        ).all()
    sequences = [event.sequence for event in events]
    assert sequences == list(range(1, len(events) + 1))
    assert len(sequences) == len(set(sequences))
