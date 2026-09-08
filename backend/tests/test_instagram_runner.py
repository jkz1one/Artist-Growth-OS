from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.domain.enums import CapabilitySupport, PlatformProofStatus
from app.platforms.proof.fake import FakePlatformProofAdapter
from app.proofs.instagram_runner import (
    LIVE_PUBLISH_CONFIRMATION,
    InstagramOperatorConfig,
    InstagramProofOperator,
    OperatorConfigError,
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
        self.publish_calls = 0
        self.reconcile_calls = 0
        self.metric_calls = 0
        self.create_account_calls = 0
        self.capture_calls = 0

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
        self.run.platform_post_id = "media-1"
        return self.run

    def reconcile(self, run_id, adapter):
        self.reconcile_calls += 1
        return self.run

    def collect_metrics(self, run_id, adapter):
        self.metric_calls += 1
        self.run.status = PlatformProofStatus.PASSED
        return self.run


def fake_instagram_adapter():
    adapter = FakePlatformProofAdapter()
    adapter.platform = "INSTAGRAM"
    adapter.api_family = "instagram-api-instagram-login-v1"
    return adapter


def test_start_captures_capabilities_but_never_publishes():
    harness = RecordingHarness()
    operator = InstagramProofOperator(harness, fake_instagram_adapter())

    result = operator.start(
        external_account_id="ig123",
        proof_key="proof-1",
        media_url="https://media.example.com/proof.mp4",
    )

    assert result["action"] == "STARTED_NO_PUBLISH"
    assert harness.create_account_calls == 1
    assert harness.capture_calls == 1
    assert harness.publish_calls == 0


def test_publish_requires_exact_confirmation_phrase_before_harness_call():
    harness = RecordingHarness()
    operator = InstagramProofOperator(harness, fake_instagram_adapter())

    with pytest.raises(PermissionError, match="live publish blocked"):
        operator.publish(run_id=harness.run.id, confirmation="yes")
    assert harness.publish_calls == 0

    result = operator.publish(
        run_id=harness.run.id,
        confirmation=LIVE_PUBLISH_CONFIRMATION,
    )
    assert result["action"] == "LIVE_PUBLISH_REQUESTED"
    assert harness.publish_calls == 1


def test_show_is_database_only_and_does_not_require_adapter():
    harness = RecordingHarness()
    operator = InstagramProofOperator(harness, adapter=None)

    result = operator.show(run_id=harness.run.id)
    assert result["action"] == "SHOW"
    assert result["run"]["id"] == str(harness.run.id)


def test_network_commands_require_runtime_adapter():
    harness = RecordingHarness()
    operator = InstagramProofOperator(harness, adapter=None)

    with pytest.raises(OperatorConfigError, match="runtime credentials"):
        operator.reconcile(run_id=harness.run.id)
    with pytest.raises(OperatorConfigError, match="runtime credentials"):
        operator.metrics(run_id=harness.run.id)


def test_runtime_config_requires_all_secret_and_media_host_inputs():
    with pytest.raises(OperatorConfigError) as exc_info:
        InstagramOperatorConfig.from_env({})
    message = str(exc_info.value)
    assert "INSTAGRAM_PROOF_API_VERSION" in message
    assert "INSTAGRAM_PROOF_ACCESS_TOKEN" in message
    assert "INSTAGRAM_PROOF_MEDIA_HOSTS" in message


def test_runtime_config_normalizes_and_deduplicates_hosts_without_exposing_token():
    config = InstagramOperatorConfig.from_env(
        {
            "INSTAGRAM_PROOF_API_VERSION": "v99.0",
            "INSTAGRAM_PROOF_ACCESS_TOKEN": "secret",
            "INSTAGRAM_PROOF_MEDIA_HOSTS": "MEDIA.example.com, media.example.com,cdn.example.com",
        }
    )
    assert config.allowed_media_hosts == ("media.example.com", "cdn.example.com")
    assert config.access_token == "secret"


def test_run_summary_rejects_unsafe_persisted_evidence():
    harness = RecordingHarness()
    harness.run.remote_context = {"access_token": "should-never-be-here"}
    operator = InstagramProofOperator(harness, adapter=None)

    with pytest.raises(UnsafeEvidenceError):
        operator.show(run_id=harness.run.id)


def test_runtime_config_repr_does_not_expose_access_token():
    config = InstagramOperatorConfig.from_env(
        {
            "INSTAGRAM_PROOF_API_VERSION": "v99.0",
            "INSTAGRAM_PROOF_ACCESS_TOKEN": "super-secret-token",
            "INSTAGRAM_PROOF_MEDIA_HOSTS": "media.example.com",
        }
    )
    assert "super-secret-token" not in repr(config)


def test_show_cli_does_not_build_instagram_adapter(monkeypatch, capsys):
    from app.proofs import instagram_runner

    harness = RecordingHarness()
    monkeypatch.setattr(instagram_runner, "_build_harness", lambda: harness)

    def fail_adapter(_):
        raise AssertionError("show must not construct the Instagram adapter")

    monkeypatch.setattr(instagram_runner, "_build_adapter", fail_adapter)
    code = instagram_runner.run_cli(["show", "--run-id", str(harness.run.id)], environ={})
    assert code == 0
    assert '"action": "SHOW"' in capsys.readouterr().out


def test_start_rejects_query_string_media_url_before_persisting_run():
    harness = RecordingHarness()
    operator = InstagramProofOperator(harness, fake_instagram_adapter())

    with pytest.raises(ValueError, match="without query string or fragment"):
        operator.start(
            external_account_id="ig123",
            proof_key="proof-1",
            media_url="https://media.example.com/proof.mp4?signature=secret",
        )
    assert harness.create_account_calls == 0
    assert harness.capture_calls == 0
    assert harness.publish_calls == 0


def test_preflight_is_local_only_and_never_exposes_access_token(monkeypatch, capsys):
    from app.platforms.proof.instagram import InstagramProofAdapter
    from app.proofs import instagram_runner

    def fail_harness():
        raise AssertionError("preflight must not construct the database harness")

    def fail_request(*args, **kwargs):
        raise AssertionError("preflight must not make a Meta request")

    monkeypatch.setattr(instagram_runner, "_build_harness", fail_harness)
    monkeypatch.setattr(InstagramProofAdapter, "_request_json", fail_request)
    secret = "super-secret-instagram-token"
    code = instagram_runner.run_cli(
        ["preflight", "--media-url", "https://cdn.media.example.com/proof.mp4"],
        environ={
            "INSTAGRAM_PROOF_API_VERSION": "v99.0",
            "INSTAGRAM_PROOF_ACCESS_TOKEN": secret,
            "INSTAGRAM_PROOF_MEDIA_HOSTS": "media.example.com,MEDIA.example.com",
        },
    )

    assert code == 0
    output = capsys.readouterr().out
    assert secret not in output
    payload = json.loads(output)
    assert payload["action"] == "PREFLIGHT_ONLY"
    assert payload["media_host"] == "cdn.media.example.com"
    assert payload["allowed_media_hosts"] == ["media.example.com"]
    assert payload["runtime_credentials_present"] is True
    assert payload["network_request"] is False
    assert payload["database_write"] is False
    assert payload["public_publish"] is False


def test_preflight_rejects_unstable_media_url_before_any_runtime_action(monkeypatch):
    from app.proofs import instagram_runner

    def fail_harness():
        raise AssertionError("preflight must not construct the database harness")

    monkeypatch.setattr(instagram_runner, "_build_harness", fail_harness)
    with pytest.raises(ValueError, match="without query string or fragment"):
        instagram_runner.run_cli(
            ["preflight", "--media-url", "https://media.example.com/proof.mp4?sig=secret"],
            environ={
                "INSTAGRAM_PROOF_API_VERSION": "v99.0",
                "INSTAGRAM_PROOF_ACCESS_TOKEN": "secret",
                "INSTAGRAM_PROOF_MEDIA_HOSTS": "media.example.com",
            },
        )


def test_preflight_rejects_non_https_media_url():
    from app.proofs import instagram_runner

    with pytest.raises(ValueError, match="public HTTPS URL"):
        instagram_runner.run_cli(
            ["preflight", "--media-url", "http://media.example.com/proof.mp4"],
            environ={
                "INSTAGRAM_PROOF_API_VERSION": "v99.0",
                "INSTAGRAM_PROOF_ACCESS_TOKEN": "secret",
                "INSTAGRAM_PROOF_MEDIA_HOSTS": "media.example.com",
            },
        )


def test_preflight_rejects_media_host_outside_controlled_allowlist():
    from app.proofs import instagram_runner

    with pytest.raises(ValueError, match="controlled allowlist"):
        instagram_runner.run_cli(
            ["preflight", "--media-url", "https://other.example.com/proof.mp4"],
            environ={
                "INSTAGRAM_PROOF_API_VERSION": "v99.0",
                "INSTAGRAM_PROOF_ACCESS_TOKEN": "secret",
                "INSTAGRAM_PROOF_MEDIA_HOSTS": "media.example.com",
            },
        )
