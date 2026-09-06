from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.domain.enums import CapabilitySupport, PlatformProofStatus, PublicationStatus
from app.platforms.proof.base import AmbiguousRemotePublishError, ProofPublishRequest
from app.platforms.proof.youtube import (
    YouTubeAPIError,
    YouTubeProofAdapter,
    YouTubeProofConfig,
)
from app.services.platform_proof import PlatformProofHarness, ProofRecoveryRequired, ProofStateError

TOKEN = "youtube-secret-token"
CHANNEL = "UCproof123"
NOW = datetime(2026, 9, 6, 18, 0, tzinfo=UTC)


def make_adapter(handler, **config_overrides):
    config = YouTubeProofConfig(
        access_token=TOKEN,
        poll_interval_seconds=30,
        **config_overrides,
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    adapter = YouTubeProofAdapter(
        config,
        client=client,
        sleep=sleeps.append,
        now=lambda: NOW,
    )
    return adapter, sleeps


def media_file(tmp_path: Path) -> Path:
    path = tmp_path / "proof.mp4"
    path.write_bytes(b"not-real-video-but-http-mock-does-not-care")
    return path


def test_config_repr_redacts_access_token_and_defaults_private():
    config = YouTubeProofConfig(access_token=TOKEN)
    assert TOKEN not in repr(config)
    assert config.privacy_status == "private"


def test_capabilities_verify_owned_channel_and_analytics_scope():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if request.url.path.endswith("/channels"):
            assert request.url.params["mine"] == "true"
            return httpx.Response(
                200,
                json={"items": [{"id": CHANNEL, "snippet": {"title": "Proof Channel"}}]},
            )
        if request.url.host == "youtubeanalytics.googleapis.com":
            return httpx.Response(
                200,
                json={
                    "columnHeaders": [{"name": "views", "columnType": "METRIC"}],
                    "rows": [],
                },
            )
        raise AssertionError(str(request.url))

    adapter, _ = make_adapter(handler)
    report = adapter.inspect_capabilities(CHANNEL)
    assert report.capabilities["can_publish_video"] == CapabilitySupport.SUPPORTED
    assert report.capabilities["can_publish_public_video"] == CapabilitySupport.REQUIRES_PROOF
    assert report.capabilities["can_publish_short"] == CapabilitySupport.REQUIRES_PROOF
    assert report.capabilities["can_read_post_metrics"] == CapabilitySupport.SUPPORTED
    assert report.capabilities["can_attach_platform_catalog_audio"] == CapabilitySupport.UNSUPPORTED
    assert (
        report.capabilities["can_set_synthetic_media_disclosure"]
        == CapabilitySupport.REQUIRES_PROOF
    )
    assert TOKEN not in repr(report.evidence)


def test_capability_analytics_failure_is_requires_proof_and_redacted():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/channels"):
            return httpx.Response(200, json={"items": [{"id": CHANNEL, "snippet": {}}]})
        return httpx.Response(
            403,
            json={"error": {"code": 403, "message": f"bad {TOKEN}"}},
        )

    adapter, _ = make_adapter(handler)
    report = adapter.inspect_capabilities(CHANNEL)
    assert report.capabilities["can_read_post_metrics"] == CapabilitySupport.REQUIRES_PROOF
    assert TOKEN not in repr(report.evidence)
    assert "[REDACTED]" in report.evidence["analytics_probe"]["error"]


def test_resumable_upload_creates_video_once_and_polls_processing(tmp_path: Path):
    path = media_file(tmp_path)
    put_calls = 0
    video_polls = 0
    checkpoints: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal put_calls, video_polls
        if request.method == "POST" and request.url.path.endswith("/upload/youtube/v3/videos"):
            metadata = json.loads(request.content)
            assert metadata["status"]["privacyStatus"] == "private"
            assert metadata["status"]["containsSyntheticMedia"] is False
            assert metadata["snippet"]["categoryId"] == "10"
            assert request.headers["X-Upload-Content-Length"] == str(path.stat().st_size)
            return httpx.Response(
                200,
                headers={
                    "Location": (
                        "https://www.googleapis.com/upload/youtube/v3/videos"
                        "?upload_id=session-secret"
                    )
                },
            )
        if request.method == "PUT" and request.url.params.get("upload_id") == "session-secret":
            put_calls += 1
            assert request.content == path.read_bytes()
            return httpx.Response(201, json={"id": "video-1", "kind": "youtube#video"})
        if request.method == "GET" and request.url.path.endswith("/youtube/v3/videos"):
            video_polls += 1
            processing = "processing" if video_polls == 1 else "succeeded"
            upload = "uploaded" if video_polls == 1 else "processed"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "video-1",
                            "snippet": {"channelId": CHANNEL},
                            "status": {
                                "uploadStatus": upload,
                                "privacyStatus": "private",
                            },
                            "processingDetails": {"processingStatus": processing},
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected {request.method} {request.url}")

    adapter, sleeps = make_adapter(handler)
    receipt = adapter.publish_controlled(
        CHANNEL,
        ProofPublishRequest(
            media_uri=str(path),
            caption="proof caption",
            idempotency_key="proof-key",
        ),
        checkpoint=checkpoints.append,
    )
    assert receipt.platform_post_id == "video-1"
    assert receipt.status == PublicationStatus.PUBLISHED
    assert put_calls == 1
    assert video_polls == 2
    assert sleeps == [30]
    assert [item["stage"] for item in checkpoints] == [
        "UPLOAD_SESSION_CREATED",
        "UPLOAD_BINARY_STARTING",
        "VIDEO_CREATED",
    ]
    assert "session-secret" not in repr(checkpoints)
    assert "session-secret" not in repr(receipt.raw)


def test_binary_transport_failure_is_ambiguous_and_never_retries(tmp_path: Path):
    path = media_file(tmp_path)
    puts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal puts
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={
                    "Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=x"
                },
            )
        if request.method == "PUT":
            puts += 1
            raise httpx.ReadTimeout("lost response", request=request)
        raise AssertionError(str(request.url))

    adapter, _ = make_adapter(handler)
    with pytest.raises(AmbiguousRemotePublishError, match="may have started") as exc_info:
        adapter.publish_controlled(
            CHANNEL,
            ProofPublishRequest(
                media_uri=str(path),
                caption="",
                idempotency_key="proof-key",
            ),
        )
    assert puts == 1
    assert exc_info.value.remote_context == {"stage": "UPLOAD_BINARY_AMBIGUOUS"}


def test_308_upload_requires_supervised_recovery_without_session_uri(tmp_path: Path):
    path = media_file(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={
                    "Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=x"
                },
            )
        if request.method == "PUT":
            return httpx.Response(308, headers={"Range": "bytes=0-3"})
        raise AssertionError(str(request.url))

    adapter, _ = make_adapter(handler)
    with pytest.raises(
        AmbiguousRemotePublishError,
        match="supervised resumable recovery",
    ) as exc_info:
        adapter.publish_controlled(
            CHANNEL,
            ProofPublishRequest(
                media_uri=str(path),
                caption="",
                idempotency_key="proof-key",
            ),
        )
    assert "upload_id" not in repr(exc_info.value.remote_context)


def test_post_upload_checkpoint_failure_carries_video_id(tmp_path: Path):
    path = media_file(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={
                    "Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=x"
                },
            )
        if request.method == "PUT":
            return httpx.Response(201, json={"id": "video-1"})
        raise AssertionError(str(request.url))

    def checkpoint(context: dict[str, object]) -> None:
        if context["stage"] == "VIDEO_CREATED":
            raise RuntimeError("database unavailable")

    adapter, _ = make_adapter(handler)
    with pytest.raises(AmbiguousRemotePublishError) as exc_info:
        adapter.publish_controlled(
            CHANNEL,
            ProofPublishRequest(
                media_uri=str(path),
                caption="",
                idempotency_key="proof-key",
            ),
            checkpoint=checkpoint,
        )
    assert exc_info.value.remote_context["media_id"] == "video-1"


def test_reconcile_known_video_id_checks_processing_and_ownership():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "video-1",
                        "snippet": {"channelId": CHANNEL},
                        "status": {"uploadStatus": "processed"},
                        "processingDetails": {"processingStatus": "succeeded"},
                    }
                ]
            },
        )

    adapter, _ = make_adapter(handler)
    status = adapter.reconcile_publish(
        CHANNEL,
        platform_post_id=None,
        idempotency_key="unused",
        remote_context={"media_id": "video-1"},
    )
    assert status.status == PublicationStatus.PUBLISHED
    assert status.canonical_url == "https://www.youtube.com/watch?v=video-1"


def test_reconcile_without_video_id_never_searches_or_uploads_again():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP call is permitted without a durable video id")

    adapter, _ = make_adapter(handler)
    status = adapter.reconcile_publish(
        CHANNEL,
        platform_post_id=None,
        idempotency_key="proof-key",
        remote_context={"stage": "UPLOAD_BINARY_AMBIGUOUS"},
    )
    assert status.status == PublicationStatus.PROCESSING
    assert status.platform_post_id is None
    assert "do not upload again" in status.raw["reason"]


def test_metrics_preserve_raw_data_and_parse_data_api_plus_analytics():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.googleapis.com":
            assert request.url.params["part"] == "snippet,status,statistics"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "video-1",
                            "snippet": {"channelId": CHANNEL},
                            "status": {"uploadStatus": "processed"},
                            "statistics": {
                                "viewCount": "120",
                                "likeCount": "9",
                                "commentCount": "2",
                            },
                        }
                    ]
                },
            )
        if request.url.host == "youtubeanalytics.googleapis.com":
            assert request.url.params["filters"] == "video==video-1"
            return httpx.Response(
                200,
                json={
                    "columnHeaders": [
                        {"name": "views"},
                        {"name": "averageViewDuration"},
                        {"name": "shares"},
                    ],
                    "rows": [[115, 7.5, 4]],
                },
            )
        raise AssertionError(str(request.url))

    adapter, _ = make_adapter(handler)
    snapshot = adapter.fetch_metrics(CHANNEL, platform_post_id="video-1")
    assert snapshot.metrics["data_api_view_count"] == 120
    assert snapshot.metrics["views"] == 115
    assert snapshot.metrics["averageViewDuration"] == 7.5
    assert snapshot.metrics["shares"] == 4
    assert snapshot.raw["data_api_video"]["id"] == "video-1"
    assert snapshot.raw["analytics"]["rows"][0][0] == 115


def test_api_errors_redact_access_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"code": 401, "message": f"bad {TOKEN}"}},
        )

    adapter, _ = make_adapter(handler)
    with pytest.raises(YouTubeAPIError) as exc_info:
        adapter.inspect_capabilities(CHANNEL)
    assert TOKEN not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


def test_publish_requires_existing_local_media_file(tmp_path: Path):
    adapter, _ = make_adapter(lambda request: httpx.Response(500))
    with pytest.raises(ValueError, match="local video file path"):
        adapter.publish_controlled(
            CHANNEL,
            ProofPublishRequest(
                media_uri="https://media.example.com/proof.mp4",
                caption="",
                idempotency_key="proof-key",
            ),
        )
    with pytest.raises(ValueError, match="does not exist"):
        adapter.publish_controlled(
            CHANNEL,
            ProofPublishRequest(
                media_uri=str(tmp_path / "missing.mp4"),
                caption="",
                idempotency_key="proof-key",
            ),
        )


def test_harness_persists_ambiguous_upload_without_session_uri(tmp_path: Path):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    harness = PlatformProofHarness(sessions)
    path = media_file(tmp_path)
    put_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal put_calls
        if request.method == "GET" and request.url.path.endswith("/channels"):
            return httpx.Response(
                200,
                json={"items": [{"id": CHANNEL, "snippet": {"title": "Proof"}}]},
            )
        if request.method == "GET" and request.url.host == "youtubeanalytics.googleapis.com":
            return httpx.Response(200, json={"columnHeaders": [{"name": "views"}]})
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={
                    "Location": (
                        "https://www.googleapis.com/upload/youtube/v3/videos"
                        "?upload_id=must-not-persist"
                    )
                },
            )
        if request.method == "PUT":
            put_calls += 1
            raise httpx.ReadTimeout("lost response", request=request)
        raise AssertionError(f"unexpected {request.method} {request.url}")

    adapter, _ = make_adapter(handler)
    account = harness.create_account(
        platform="YOUTUBE",
        external_account_id=CHANNEL,
        api_family=adapter.api_family,
    )
    run = harness.start_run(
        platform_account_id=account.id,
        proof_key="youtube-proof-1",
        media_uri=str(path),
    )
    harness.capture_capabilities(run.id, adapter)

    with pytest.raises(ProofRecoveryRequired):
        harness.publish_once(run.id, adapter)
    persisted = harness.get_run(run.id)
    assert persisted.status == PlatformProofStatus.RECOVERY_REQUIRED
    assert persisted.remote_context["stage"] == "UPLOAD_BINARY_AMBIGUOUS"
    assert "upload_id" not in repr(persisted.remote_context)
    assert "must-not-persist" not in repr(persisted.remote_context)
    assert put_calls == 1

    with pytest.raises(ProofStateError):
        harness.publish_once(run.id, adapter)
    assert put_calls == 1
