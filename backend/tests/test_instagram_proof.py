from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.domain.enums import CapabilitySupport, PlatformProofStatus, PublicationStatus
from app.platforms.proof.base import AmbiguousRemotePublishError, ProofPublishRequest
from app.platforms.proof.instagram import (
    InstagramAPIError,
    InstagramProofAdapter,
    InstagramProofConfig,
)
from app.services.platform_proof import PlatformProofHarness, ProofRecoveryRequired, ProofStateError

TOKEN = "secret-token-value"
ACCOUNT = "ig123"


def make_adapter(handler, *, max_polls=5, sleep=None):
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return InstagramProofAdapter(
        InstagramProofConfig(
            api_version="v99.0",
            access_token=TOKEN,
            allowed_media_hosts=("media.example.com",),
            max_status_polls=max_polls,
            poll_interval_seconds=60.0,
        ),
        client=client,
        sleep=sleep or (lambda _: None),
    )


def capability_handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    path = request.url.path
    if path.endswith(f"/{ACCOUNT}"):
        return httpx.Response(200, json={"id": ACCOUNT, "username": "artistgrowthproof"})
    if path.endswith(f"/{ACCOUNT}/content_publishing_limit"):
        return httpx.Response(
            200, json={"data": [{"quota_usage": 0, "config": {"quota_total": 100}}]}
        )
    if path.endswith(f"/{ACCOUNT}/insights"):
        return httpx.Response(200, json={"data": []})
    raise AssertionError(f"unexpected request {request.method} {path}")


def test_capability_probe_is_authorized_but_evidence_is_secret_free():
    adapter = make_adapter(capability_handler)
    report = adapter.inspect_capabilities(ACCOUNT)

    assert report.capabilities["can_publish_video"] == CapabilitySupport.SUPPORTED
    assert report.capabilities["can_read_post_metrics"] == CapabilitySupport.SUPPORTED
    assert (
        report.capabilities["can_attach_platform_catalog_audio"]
        == CapabilitySupport.REQUIRES_PROOF
    )
    assert report.capabilities["can_trial_reels"] == CapabilitySupport.UNKNOWN
    assert TOKEN not in repr(report.evidence)


def test_reel_publish_polls_finished_then_calls_media_publish_once():
    polls = 0
    media_publish_calls = 0
    sleeps: list[float] = []
    checkpoints: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal polls, media_publish_calls
        path = request.url.path
        if request.method == "POST" and path.endswith(f"/{ACCOUNT}/media"):
            body = parse_qs(request.content.decode())
            assert body["media_type"] == ["REELS"]
            assert body["video_url"] == ["https://media.example.com/proof.mp4"]
            return httpx.Response(200, json={"id": "container-1"})
        if request.method == "GET" and path.endswith("/container-1"):
            polls += 1
            code = "IN_PROGRESS" if polls == 1 else "FINISHED"
            return httpx.Response(200, json={"id": "container-1", "status_code": code})
        if request.method == "POST" and path.endswith(f"/{ACCOUNT}/media_publish"):
            media_publish_calls += 1
            assert parse_qs(request.content.decode())["creation_id"] == ["container-1"]
            return httpx.Response(200, json={"id": "media-1"})
        raise AssertionError(f"unexpected request {request.method} {path}")

    adapter = make_adapter(handler, sleep=sleeps.append)
    receipt = adapter.publish_controlled(
        ACCOUNT,
        ProofPublishRequest(
            media_uri="https://media.example.com/proof.mp4",
            caption="proof",
            idempotency_key="proof-key",
        ),
        checkpoint=checkpoints.append,
    )

    assert receipt.status == PublicationStatus.PUBLISHED
    assert receipt.platform_post_id == "media-1"
    assert polls == 2
    assert media_publish_calls == 1
    assert sleeps == [60.0]
    assert [item["stage"] for item in checkpoints] == [
        "CONTAINER_CREATED",
        "CONTAINER_FINISHED",
        "MEDIA_PUBLISH_STARTING",
        "MEDIA_PUBLISHED",
    ]
    assert TOKEN not in repr(receipt.raw)


def test_terminal_container_error_never_calls_media_publish():
    media_publish_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal media_publish_calls
        path = request.url.path
        if request.method == "POST" and path.endswith(f"/{ACCOUNT}/media"):
            return httpx.Response(200, json={"id": "container-1"})
        if request.method == "GET" and path.endswith("/container-1"):
            return httpx.Response(200, json={"status_code": "ERROR"})
        if path.endswith(f"/{ACCOUNT}/media_publish"):
            media_publish_calls += 1
        raise AssertionError(f"unexpected request {request.method} {path}")

    adapter = make_adapter(handler)
    with pytest.raises(InstagramAPIError, match="terminal state ERROR"):
        adapter.publish_controlled(
            ACCOUNT,
            ProofPublishRequest(
                media_uri="https://media.example.com/proof.mp4",
                caption="",
                idempotency_key="proof-key",
            ),
        )
    assert media_publish_calls == 0


def test_container_poll_timeout_never_calls_media_publish():
    media_publish_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal media_publish_calls
        path = request.url.path
        if request.method == "POST" and path.endswith(f"/{ACCOUNT}/media"):
            return httpx.Response(200, json={"id": "container-1"})
        if request.method == "GET" and path.endswith("/container-1"):
            return httpx.Response(200, json={"status_code": "IN_PROGRESS"})
        if path.endswith(f"/{ACCOUNT}/media_publish"):
            media_publish_calls += 1
        raise AssertionError(f"unexpected request {request.method} {path}")

    adapter = make_adapter(handler, max_polls=2)
    with pytest.raises(InstagramAPIError, match="bounded polling window"):
        adapter.publish_controlled(
            ACCOUNT,
            ProofPublishRequest(
                media_uri="https://media.example.com/proof.mp4",
                caption="",
                idempotency_key="proof-key",
            ),
        )
    assert media_publish_calls == 0


def test_media_publish_transport_failure_is_ambiguous_with_container_checkpoint():
    checkpoints: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith(f"/{ACCOUNT}/media"):
            return httpx.Response(200, json={"id": "container-1"})
        if request.method == "GET" and path.endswith("/container-1"):
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if request.method == "POST" and path.endswith(f"/{ACCOUNT}/media_publish"):
            raise httpx.ReadTimeout("lost response", request=request)
        raise AssertionError(f"unexpected request {request.method} {path}")

    adapter = make_adapter(handler)
    with pytest.raises(AmbiguousRemotePublishError, match="may have been sent"):
        adapter.publish_controlled(
            ACCOUNT,
            ProofPublishRequest(
                media_uri="https://media.example.com/proof.mp4",
                caption="",
                idempotency_key="proof-key",
            ),
            checkpoint=checkpoints.append,
        )
    assert checkpoints[-1] == {"stage": "MEDIA_PUBLISH_STARTING", "container_id": "container-1"}


def test_reconcile_with_media_id_proves_published_media():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/media-1")
        return httpx.Response(
            200,
            json={
                "id": "media-1",
                "media_type": "VIDEO",
                "permalink": "https://www.instagram.com/reel/example/",
                "timestamp": "2026-09-06T18:00:00+0000",
            },
        )

    status = make_adapter(handler).reconcile_publish(
        ACCOUNT,
        platform_post_id=None,
        idempotency_key="proof-key",
        remote_context={"media_id": "media-1", "container_id": "container-1"},
    )
    assert status.status == PublicationStatus.PUBLISHED
    assert status.platform_post_id == "media-1"
    assert status.canonical_url == "https://www.instagram.com/reel/example/"


def test_reconcile_published_container_without_media_id_stays_recovery_required():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/container-1")
        return httpx.Response(200, json={"status_code": "PUBLISHED"})

    status = make_adapter(handler).reconcile_publish(
        ACCOUNT,
        platform_post_id=None,
        idempotency_key="proof-key",
        remote_context={"container_id": "container-1"},
    )
    assert status.status == PublicationStatus.PROCESSING
    assert status.platform_post_id is None
    assert "do not republish" in status.raw["recovery"]


def test_media_insights_are_normalized_without_losing_raw_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/media-1/insights")
        assert "views" in request.url.params["metric"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"name": "views", "values": [{"value": 120}]},
                    {"name": "reach", "total_value": {"value": 90}},
                    {"name": "shares", "values": [{"value": 7}]},
                ]
            },
        )

    snapshot = make_adapter(handler).fetch_metrics(ACCOUNT, platform_post_id="media-1")
    assert snapshot.metrics == {"views": 120, "reach": 90, "shares": 7}
    assert snapshot.raw["data"][0]["name"] == "views"
    assert TOKEN not in repr(snapshot.raw)


def test_graph_error_redacts_access_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": f"bad token {TOKEN}",
                    "type": "OAuthException",
                    "code": 190,
                }
            },
        )

    adapter = make_adapter(handler)
    with pytest.raises(InstagramAPIError) as exc_info:
        adapter.inspect_capabilities(ACCOUNT)
    assert TOKEN not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


def test_media_url_must_use_controlled_https_host():
    adapter = make_adapter(lambda request: httpx.Response(500))
    with pytest.raises(ValueError, match="controlled allowlist"):
        adapter.publish_controlled(
            ACCOUNT,
            ProofPublishRequest(
                media_uri="https://untrusted.example.org/proof.mp4",
                caption="",
                idempotency_key="proof-key",
            ),
        )


def test_harness_persists_container_checkpoint_before_ambiguous_final_publish():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    harness = PlatformProofHarness(sessions)
    media_publish_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal media_publish_calls
        path = request.url.path
        if request.method == "GET" and path.endswith(f"/{ACCOUNT}"):
            return httpx.Response(200, json={"id": ACCOUNT, "username": "proof"})
        if request.method == "GET" and path.endswith(f"/{ACCOUNT}/content_publishing_limit"):
            return httpx.Response(200, json={"data": []})
        if request.method == "GET" and path.endswith(f"/{ACCOUNT}/insights"):
            return httpx.Response(200, json={"data": []})
        if request.method == "POST" and path.endswith(f"/{ACCOUNT}/media"):
            return httpx.Response(200, json={"id": "container-1"})
        if request.method == "GET" and path.endswith("/container-1"):
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if request.method == "POST" and path.endswith(f"/{ACCOUNT}/media_publish"):
            media_publish_calls += 1
            raise httpx.ReadTimeout("lost response", request=request)
        raise AssertionError(f"unexpected request {request.method} {path}")

    adapter = make_adapter(handler)
    account = harness.create_account(
        platform="INSTAGRAM",
        external_account_id=ACCOUNT,
        api_family=adapter.api_family,
    )
    run = harness.start_run(
        platform_account_id=account.id,
        proof_key="instagram-proof-1",
        media_uri="https://media.example.com/proof.mp4",
    )
    harness.capture_capabilities(run.id, adapter)

    with pytest.raises(ProofRecoveryRequired):
        harness.publish_once(run.id, adapter)
    persisted = harness.get_run(run.id)
    assert persisted.status == PlatformProofStatus.RECOVERY_REQUIRED
    assert persisted.remote_context["container_id"] == "container-1"
    assert persisted.remote_context["stage"] == "MEDIA_PUBLISH_STARTING"
    assert media_publish_calls == 1

    with pytest.raises(ProofStateError):
        harness.publish_once(run.id, adapter)
    assert media_publish_calls == 1


def test_post_publish_checkpoint_failure_carries_media_id_for_recovery():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith(f"/{ACCOUNT}/media"):
            return httpx.Response(200, json={"id": "container-1"})
        if request.method == "GET" and path.endswith("/container-1"):
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if request.method == "POST" and path.endswith(f"/{ACCOUNT}/media_publish"):
            return httpx.Response(200, json={"id": "media-1"})
        raise AssertionError(f"unexpected request {request.method} {path}")

    def checkpoint(context: dict[str, object]) -> None:
        if context["stage"] == "MEDIA_PUBLISHED":
            raise RuntimeError("database unavailable")

    with pytest.raises(AmbiguousRemotePublishError) as exc_info:
        make_adapter(handler).publish_controlled(
            ACCOUNT,
            ProofPublishRequest(
                media_uri="https://media.example.com/proof.mp4",
                caption="",
                idempotency_key="proof-key",
            ),
            checkpoint=checkpoint,
        )
    assert exc_info.value.remote_context["media_id"] == "media-1"
    assert exc_info.value.remote_context["container_id"] == "container-1"
