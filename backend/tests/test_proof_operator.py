from __future__ import annotations

from uuid import uuid4

import pytest

from app.domain.enums import CapabilitySupport, PlatformProofStatus
from app.platforms.proof.fake import FakePlatformProofAdapter
from app.proofs.operator import (
    LIVE_PUBLISH_CONFIRMATION,
    OperatorConfigError,
    PlatformProofOperator,
)
from app.services.proof_security import UnsafeEvidenceError


class DummyRun:
    def __init__(self, *, status=PlatformProofStatus.READY):
        self.id = uuid4()
        self.platform_account_id = uuid4()
        self.proof_key = "proof-1"
        self.status = status
        self.media_uri = "https://media.example.com/proof.mp4"
        self.platform_post_id = None
        self.canonical_url = None
        self.last_error = None
        self.remote_context = {}
        self.result_json = None
        self.created_at = None
        self.published_at = None
        self.completed_at = None


class DummyAccount:
    def __init__(self):
        self.id = uuid4()


class DummySnapshot:
    def __init__(self):
        self.id = uuid4()
        self.capabilities = {"can_publish_video": CapabilitySupport.SUPPORTED.value}


class RecordingHarness:
    def __init__(self):
        self.run = DummyRun()
        self.create_account_calls = 0
        self.capture_calls = 0
        self.publish_calls = 0
        self.reconcile_calls = 0
        self.metric_calls = 0

    def create_account(self, **kwargs):
        self.create_account_calls += 1
        return DummyAccount()

    def start_run(self, **kwargs):
        return self.run

    def capture_capabilities(self, run_id, adapter):
        self.capture_calls += 1
        return DummySnapshot()

    def get_run(self, run_id):
        return self.run

    def publish_once(self, run_id, adapter):
        self.publish_calls += 1
        self.run.status = PlatformProofStatus.PUBLISHED
        self.run.platform_post_id = "post-1"
        return self.run

    def reconcile(self, run_id, adapter):
        self.reconcile_calls += 1
        return self.run

    def collect_metrics(self, run_id, adapter):
        self.metric_calls += 1
        self.run.status = PlatformProofStatus.PASSED
        return self.run


def test_start_captures_capabilities_without_publishing():
    harness = RecordingHarness()
    operator = PlatformProofOperator(
        harness,
        FakePlatformProofAdapter(),
        platform_label="Fake",
    )

    result = operator.start(
        external_account_id="acct-1",
        proof_key="proof-1",
        media_uri="https://media.example.com/proof.mp4",
    )

    assert result["action"] == "STARTED_NO_PUBLISH"
    assert harness.create_account_calls == 1
    assert harness.capture_calls == 1
    assert harness.publish_calls == 0


def test_live_publish_is_disabled_by_default_even_with_confirmation():
    harness = RecordingHarness()
    operator = PlatformProofOperator(
        harness,
        FakePlatformProofAdapter(),
        platform_label="Fake",
    )

    with pytest.raises(PermissionError, match="live publish disabled"):
        operator.publish(
            run_id=harness.run.id,
            confirmation=LIVE_PUBLISH_CONFIRMATION,
        )
    assert harness.publish_calls == 0


def test_enabled_live_publish_still_requires_exact_confirmation():
    harness = RecordingHarness()
    operator = PlatformProofOperator(
        harness,
        FakePlatformProofAdapter(),
        platform_label="Fake",
        live_publish_enabled=True,
    )

    with pytest.raises(PermissionError, match="live publish blocked"):
        operator.publish(run_id=harness.run.id, confirmation="yes")
    assert harness.publish_calls == 0

    result = operator.publish(
        run_id=harness.run.id,
        confirmation=LIVE_PUBLISH_CONFIRMATION,
    )
    assert result["action"] == "LIVE_PUBLISH_REQUESTED"
    assert harness.publish_calls == 1


def test_show_is_database_only_without_adapter():
    harness = RecordingHarness()
    operator = PlatformProofOperator(
        harness,
        adapter=None,
        platform_label="Fake",
    )

    result = operator.show(run_id=harness.run.id)
    assert result["action"] == "SHOW"
    assert result["run"]["id"] == str(harness.run.id)


def test_network_operations_require_runtime_adapter():
    harness = RecordingHarness()
    operator = PlatformProofOperator(
        harness,
        adapter=None,
        platform_label="Fake",
    )

    with pytest.raises(OperatorConfigError, match="Fake proof runtime credentials"):
        operator.reconcile(run_id=harness.run.id)
    with pytest.raises(OperatorConfigError, match="Fake proof runtime credentials"):
        operator.metrics(run_id=harness.run.id)


def test_media_validator_runs_before_any_persistence():
    harness = RecordingHarness()

    def reject(_media_uri: str) -> None:
        raise ValueError("media rejected")

    operator = PlatformProofOperator(
        harness,
        FakePlatformProofAdapter(),
        platform_label="Fake",
        media_validator=reject,
    )

    with pytest.raises(ValueError, match="media rejected"):
        operator.start(
            external_account_id="acct-1",
            proof_key="proof-1",
            media_uri="https://media.example.com/proof.mp4",
        )
    assert harness.create_account_calls == 0
    assert harness.capture_calls == 0
    assert harness.publish_calls == 0


def test_unsafe_start_input_is_rejected_before_persistence():
    harness = RecordingHarness()
    operator = PlatformProofOperator(
        harness,
        FakePlatformProofAdapter(),
        platform_label="Fake",
    )

    with pytest.raises(UnsafeEvidenceError):
        operator.start(
            external_account_id="acct-1",
            proof_key="proof-1",
            media_uri="https://media.example.com/proof.mp4?access_token=secret",
        )
    assert harness.create_account_calls == 0
    assert harness.capture_calls == 0


def test_run_summary_rejects_unsafe_persisted_evidence():
    harness = RecordingHarness()
    harness.run.remote_context = {"access_token": "should-never-be-here"}
    operator = PlatformProofOperator(
        harness,
        adapter=None,
        platform_label="Fake",
    )

    with pytest.raises(UnsafeEvidenceError):
        operator.show(run_id=harness.run.id)
