from __future__ import annotations

import json

import httpx
import pytest

from app.domain.enums import CapabilitySupport, PublicationStatus
from app.platforms.proof.base import AmbiguousRemotePublishError, ProofPublishRequest
from app.platforms.proof.tiktok import TikTokAPIError, TikTokProofAdapter, TikTokProofConfig

TOKEN = "secret-tiktok-token"
ACCOUNT = "biz-123"


def ok(data=None):
    return httpx.Response(200, json={"code": 0, "message": "OK", "data": data or {}})


def make_adapter(handler, *, max_polls=5, sleep=None, **config):
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return TikTokProofAdapter(
        TikTokProofConfig(
            access_token=TOKEN,
            verified_media_hosts=("media.example.com",),
            max_status_polls=max_polls,
            poll_interval_seconds=10.0,
            **config,
        ),
        client=client,
        sleep=sleep or (lambda _: None),
    )


def test_config_repr_excludes_access_token():
    config = TikTokProofConfig(
        access_token=TOKEN,
        verified_media_hosts=("media.example.com",),
    )
    assert TOKEN not in repr(config)


def test_capability_probe_uses_account_scoped_endpoints_and_preserves_no_token():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.headers["Access-Token"] == TOKEN
        path = request.url.path
        if path.endswith("/tt_user/token_info/get/"):
            return ok({"scopes": ["Account User", "Video Publish", "Get Account Media"]})
        if path.endswith("/business/get/"):
            assert request.url.params["business_id"] == ACCOUNT
            return ok(
                {
                    "business_id": ACCOUNT,
                    "username": "proof",
                    "display_name": "Proof",
                    "followers_count": 10,
                }
            )
        if path.endswith("/business/video/settings/"):
            return ok({"privacy_level_options": ["PUBLIC_TO_EVERYONE"]})
        if path.endswith("/business/video/list/"):
            return ok({"videos": []})
        raise AssertionError(path)

    report = make_adapter(handler).inspect_capabilities(ACCOUNT)

    assert report.capabilities["can_publish_video"] == CapabilitySupport.SUPPORTED
    assert report.capabilities["can_read_post_metrics"] == CapabilitySupport.SUPPORTED
    assert (
        report.capabilities["can_attach_platform_catalog_audio"]
        == CapabilitySupport.REQUIRES_PROOF
    )
    assert report.capabilities["can_set_synthetic_media_disclosure"] == CapabilitySupport.UNKNOWN
    assert TOKEN not in repr(report.evidence)
    assert any(path.endswith("/business/video/settings/") for path in calls)


def test_profile_identity_mismatch_fails_closed():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/tt_user/token_info/get/"):
            return ok({"scopes": []})
        if path.endswith("/business/get/"):
            return ok({"business_id": "other-account"})
        raise AssertionError(path)

    with pytest.raises(TikTokAPIError, match="identity does not match"):
        make_adapter(handler).inspect_capabilities(ACCOUNT)


def test_media_uri_requires_configured_verified_property():
    adapter = make_adapter(lambda request: ok())
    request = ProofPublishRequest(
        media_uri="https://unverified.example.org/proof.mp4",
        caption="proof",
        idempotency_key="proof-key",
    )
    with pytest.raises(ValueError, match="verified URL property"):
        adapter.publish_controlled(ACCOUNT, request)


def test_verified_prefix_accepts_only_matching_host_and_path_boundary():
    adapter = TikTokProofAdapter(
        TikTokProofConfig(
            access_token=TOKEN,
            verified_media_prefixes=("https://cdn.example.com/proofs/",),
        ),
        client=httpx.Client(transport=httpx.MockTransport(lambda request: ok())),
    )
    adapter._validate_media_uri("https://cdn.example.com/proofs/video.mp4")
    with pytest.raises(ValueError):
        adapter._validate_media_uri("https://cdn.example.com/other/video.mp4")
    with pytest.raises(ValueError):
        adapter._validate_media_uri("https://cdn.example.com.evil.test/proofs/video.mp4")


def test_publish_calls_public_endpoint_once_and_polls_to_post_id():
    publish_calls = 0
    status_calls = 0
    sleeps = []
    checkpoints = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal publish_calls, status_calls
        path = request.url.path
        if request.method == "POST" and path.endswith("/business/video/publish/"):
            publish_calls += 1
            body = json.loads(request.content)
            assert body["business_id"] == ACCOUNT
            assert body["video_url"] == "https://media.example.com/proof.mp4"
            assert body["post_info"]["caption"] == "proof"
            return ok({"share_id": "share-1"})
        if request.method == "GET" and path.endswith("/business/publish/status/"):
            status_calls += 1
            assert request.url.params["publish_id"] == "share-1"
            if status_calls == 1:
                return ok({"status": "PROCESSING_DOWNLOAD"})
            return ok({"status": "PUBLISH_COMPLETE", "post_ids": ["post-1"]})
        raise AssertionError(f"{request.method} {path}")

    receipt = make_adapter(handler, sleep=sleeps.append).publish_controlled(
        ACCOUNT,
        ProofPublishRequest(
            media_uri="https://media.example.com/proof.mp4",
            caption="proof",
            idempotency_key="proof-key",
        ),
        checkpoint=checkpoints.append,
    )

    assert receipt.status == PublicationStatus.PUBLISHED
    assert receipt.platform_post_id == "post-1"
    assert publish_calls == 1
    assert status_calls == 2
    assert sleeps == [10.0]
    assert checkpoints == [
        {"stage": "PUBLISH_TASK_CREATED", "publish_id": "share-1"},
        {"stage": "POST_PUBLISHED", "publish_id": "share-1", "post_id": "post-1"},
    ]


def test_publish_transport_failure_is_ambiguous_and_not_retried():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("lost response", request=request)

    with pytest.raises(AmbiguousRemotePublishError, match="may have been accepted"):
        make_adapter(handler).publish_controlled(
            ACCOUNT,
            ProofPublishRequest(
                media_uri="https://media.example.com/proof.mp4",
                caption="",
                idempotency_key="proof-key",
            ),
        )
    assert calls == 1


def test_publish_server_error_is_ambiguous():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"code": 50000, "message": "unavailable"})

    with pytest.raises(AmbiguousRemotePublishError, match="server error"):
        make_adapter(handler).publish_controlled(
            ACCOUNT,
            ProofPublishRequest(
                media_uri="https://media.example.com/proof.mp4",
                caption="",
                idempotency_key="proof-key",
            ),
        )
    assert calls == 1


def test_missing_publish_id_is_ambiguous():
    def handler(request: httpx.Request) -> httpx.Response:
        return ok({})

    with pytest.raises(AmbiguousRemotePublishError, match="no publish task id"):
        make_adapter(handler).publish_controlled(
            ACCOUNT,
            ProofPublishRequest(
                media_uri="https://media.example.com/proof.mp4",
                caption="",
                idempotency_key="proof-key",
            ),
        )


def test_terminal_publish_failure_never_issues_second_publish():
    publish_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal publish_calls
        path = request.url.path
        if request.method == "POST":
            publish_calls += 1
            return ok({"share_id": "share-1"})
        if path.endswith("/business/publish/status/"):
            return ok({"status": "FAILED", "reason": "copyright check failed"})
        raise AssertionError(path)

    with pytest.raises(TikTokAPIError, match="terminal state FAILED"):
        make_adapter(handler).publish_controlled(
            ACCOUNT,
            ProofPublishRequest(
                media_uri="https://media.example.com/proof.mp4",
                caption="",
                idempotency_key="proof-key",
            ),
        )
    assert publish_calls == 1


def test_unresolved_processing_becomes_recovery_with_publish_id():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            return ok({"share_id": "share-1"})
        if path.endswith("/business/publish/status/"):
            return ok({"status": "PROCESSING_DOWNLOAD"})
        raise AssertionError(path)

    with pytest.raises(AmbiguousRemotePublishError) as exc_info:
        make_adapter(handler, max_polls=2).publish_controlled(
            ACCOUNT,
            ProofPublishRequest(
                media_uri="https://media.example.com/proof.mp4",
                caption="",
                idempotency_key="proof-key",
            ),
        )
    assert exc_info.value.remote_context["publish_id"] == "share-1"
    assert "video_url" not in exc_info.value.remote_context


def test_unknown_publish_status_fails_closed():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return ok({"share_id": "share-1"})
        return ok({"status": "SOMETHING_NEW"})

    with pytest.raises(TikTokAPIError, match="unknown TikTok publish status"):
        make_adapter(handler).publish_controlled(
            ACCOUNT,
            ProofPublishRequest(
                media_uri="https://media.example.com/proof.mp4",
                caption="",
                idempotency_key="proof-key",
            ),
        )


def test_reconcile_known_post_id_uses_video_list_not_publish():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.url.path.endswith("/business/video/list/")
        filters = json.loads(request.url.params["filters"])
        assert filters == {"video_ids": ["post-1"]}
        return ok({"videos": [{"item_id": "post-1", "caption": "proof"}]})

    status = make_adapter(handler).reconcile_publish(
        ACCOUNT,
        platform_post_id="post-1",
        idempotency_key="proof-key",
        remote_context={"publish_id": "share-1"},
    )
    assert status.status == PublicationStatus.PUBLISHED
    assert status.platform_post_id == "post-1"
    assert all(method == "GET" for method, _ in calls)


def test_reconcile_publish_task_never_republishes():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        assert request.url.path.endswith("/business/publish/status/")
        return ok({"status": "PROCESSING_DOWNLOAD"})

    status = make_adapter(handler).reconcile_publish(
        ACCOUNT,
        platform_post_id=None,
        idempotency_key="proof-key",
        remote_context={"publish_id": "share-1"},
    )
    assert status.status == PublicationStatus.PROCESSING
    assert status.platform_post_id is None
    assert calls == ["GET"]
    assert "do not issue another publish" in status.raw["recovery"]


def test_metrics_normalize_known_fields_and_preserve_raw():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/business/video/list/")
        return ok(
            {
                "videos": [
                    {
                        "item_id": "post-1",
                        "video_views": 123,
                        "likes": 12,
                        "comments": 3,
                        "shares": 4,
                        "total_time_watched": 999,
                        "average_time_watched": 8.5,
                        "reach": 100,
                        "full_video_watched_rate": 0.42,
                    }
                ]
            }
        )

    snapshot = make_adapter(handler).fetch_metrics(ACCOUNT, platform_post_id="post-1")
    assert snapshot.metrics["video_views"] == 123
    assert snapshot.metrics["full_video_watched_rate"] == 0.42
    assert snapshot.raw["video"]["item_id"] == "post-1"


def test_api_error_redacts_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"code": 40100, "message": f"bad token {TOKEN}", "data": {}},
        )

    with pytest.raises(TikTokAPIError) as exc_info:
        make_adapter(handler).inspect_capabilities(ACCOUNT)
    assert TOKEN not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


def test_safe_payload_strips_credential_fields_from_raw_evidence():
    adapter = make_adapter(lambda request: ok())
    safe = adapter._safe_payload(
        {
            "access_token": TOKEN,
            "refresh-token": "refresh",
            "nested": {"client_secret": "hidden", "value": f"prefix {TOKEN}"},
        }
    )
    assert "access_token" not in safe
    assert "refresh-token" not in safe
    assert "client_secret" not in safe["nested"]
    assert safe["nested"]["value"] == "prefix [REDACTED]"
