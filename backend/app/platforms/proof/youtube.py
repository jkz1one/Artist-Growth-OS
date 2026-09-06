from __future__ import annotations

import mimetypes
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from app.domain.enums import CapabilitySupport, PublicationStatus
from app.platforms.proof.base import (
    AmbiguousRemotePublishError,
    CapabilityReport,
    ProofCheckpoint,
    ProofMetricSnapshot,
    ProofPostStatus,
    ProofPublishReceipt,
    ProofPublishRequest,
)


class YouTubeProofError(RuntimeError):
    pass


class YouTubeAPIError(YouTubeProofError):
    pass


@dataclass(frozen=True)
class YouTubeProofConfig:
    access_token: str = field(repr=False)
    privacy_status: Literal["private", "public", "unlisted"] = "private"
    contains_synthetic_media: bool = False
    category_id: str = "10"
    title_prefix: str = "Artist Growth OS proof"
    max_processing_polls: int = 5
    poll_interval_seconds: float = 30.0
    analytics_window_days: int = 7
    request_timeout_seconds: float = 60.0
    data_base_url: str = "https://www.googleapis.com/youtube/v3"
    upload_base_url: str = "https://www.googleapis.com/upload/youtube/v3"
    analytics_base_url: str = "https://youtubeanalytics.googleapis.com/v2"

    def __post_init__(self) -> None:
        if not self.access_token.strip():
            raise ValueError("access_token is required")
        if self.privacy_status not in {"private", "public", "unlisted"}:
            raise ValueError("privacy_status must be private, public, or unlisted")
        if not self.category_id.strip():
            raise ValueError("category_id is required")
        if not self.title_prefix.strip():
            raise ValueError("title_prefix is required")
        if len(self.title_prefix) > 80:
            raise ValueError("title_prefix must be at most 80 characters")
        if self.max_processing_polls < 1:
            raise ValueError("max_processing_polls must be at least 1")
        if self.poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds cannot be negative")
        if self.analytics_window_days < 1:
            raise ValueError("analytics_window_days must be at least 1")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")


class YouTubeProofAdapter:
    """Proof-only YouTube Data/Analytics API adapter.

    The resumable session URI is intentionally never returned in durable evidence. Once the
    binary PUT begins, a transport/server ambiguity becomes recovery-required rather than a
    blind second upload.
    """

    platform = "YOUTUBE"
    api_family = "youtube-data-api-v3"

    def __init__(
        self,
        config: YouTubeProofConfig,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self._client = client or httpx.Client(timeout=config.request_timeout_seconds)
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(UTC))

    def inspect_capabilities(self, external_account_id: str) -> CapabilityReport:
        channel = self._owned_channel(external_account_id)

        analytics_probe: dict[str, Any]
        metrics_support = CapabilitySupport.REQUIRES_PROOF
        try:
            today = self._now().date()
            probe = self._analytics_query(
                start_date=today - timedelta(days=2),
                end_date=today - timedelta(days=1),
                metrics="views",
            )
            analytics_probe = {
                "available": True,
                "has_rows": bool(probe.get("rows")),
                "columns": self._analytics_columns(probe),
            }
            metrics_support = CapabilitySupport.SUPPORTED
        except YouTubeAPIError as exc:
            analytics_probe = {"available": False, "error": str(exc)}

        snippet = channel.get("snippet") if isinstance(channel.get("snippet"), dict) else {}
        return CapabilityReport(
            api_family=self.api_family,
            api_version="v3",
            capabilities={
                "can_publish_video": CapabilitySupport.SUPPORTED,
                "can_publish_public_video": CapabilitySupport.REQUIRES_PROOF,
                "can_publish_short": CapabilitySupport.REQUIRES_PROOF,
                "can_read_publish_status": CapabilitySupport.SUPPORTED,
                "can_read_post_metrics": metrics_support,
                "can_attach_platform_catalog_audio": CapabilitySupport.UNSUPPORTED,
                "can_use_baked_audio": CapabilitySupport.SUPPORTED,
                "can_detect_content_id_claims": CapabilitySupport.REQUIRES_PROOF,
                "can_set_synthetic_media_disclosure": CapabilitySupport.REQUIRES_PROOF,
            },
            evidence={
                "account": {
                    "id": channel.get("id"),
                    "title": snippet.get("title"),
                },
                "analytics_probe": analytics_probe,
                "upload_visibility": {
                    "configured_privacy_status": self.config.privacy_status,
                    "public_visibility_requires_account_project_proof": True,
                },
                "documentation": {
                    "upload": "YouTube Data API v3 / resumable videos.insert",
                    "processing": "YouTube Data API v3 / videos.list processingDetails",
                    "analytics": "YouTube Analytics API v2 / reports.query",
                },
            },
        )

    def publish_controlled(
        self,
        external_account_id: str,
        request: ProofPublishRequest,
        *,
        checkpoint: ProofCheckpoint | None = None,
    ) -> ProofPublishReceipt:
        media_path = self._validate_media_path(request.media_uri)
        if len(request.caption) > 5000:
            raise ValueError("YouTube proof caption must be at most 5000 characters")

        file_size = media_path.stat().st_size
        content_type = mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"
        if not content_type.startswith("video/"):
            content_type = "application/octet-stream"

        metadata = {
            "snippet": {
                "title": f"{self.config.title_prefix} {request.idempotency_key[:12]}",
                "description": request.caption,
                "categoryId": self.config.category_id,
            },
            "status": {
                "privacyStatus": self.config.privacy_status,
                "containsSyntheticMedia": self.config.contains_synthetic_media,
            },
        }
        upload_url = self._start_upload_session(
            metadata=metadata,
            file_size=file_size,
            content_type=content_type,
        )
        self._checkpoint(
            checkpoint,
            {
                "stage": "UPLOAD_SESSION_CREATED",
                "file_size": file_size,
                "content_type": content_type,
                "privacy_status": self.config.privacy_status,
            },
        )
        self._checkpoint(
            checkpoint,
            {
                "stage": "UPLOAD_BINARY_STARTING",
                "file_size": file_size,
                "privacy_status": self.config.privacy_status,
            },
        )

        created = self._upload_binary(
            upload_url=upload_url,
            media_path=media_path,
            file_size=file_size,
            content_type=content_type,
        )
        video_id = self._string_or_none(created.get("id"))
        if not video_id:
            raise AmbiguousRemotePublishError(
                "YouTube upload returned success without a video id",
                remote_context={"stage": "UPLOAD_SUCCEEDED_WITHOUT_VIDEO_ID"},
            )

        try:
            self._checkpoint(
                checkpoint,
                {
                    "stage": "VIDEO_CREATED",
                    "media_id": video_id,
                    "privacy_status": self.config.privacy_status,
                },
            )
        except Exception as exc:
            raise AmbiguousRemotePublishError(
                "YouTube video was created but durable video-id checkpoint failed",
                remote_context={
                    "stage": "VIDEO_CREATED_UNCHECKPOINTED",
                    "media_id": video_id,
                    "privacy_status": self.config.privacy_status,
                },
            ) from exc

        last_video: dict[str, Any] | None = None
        publication_status = PublicationStatus.PROCESSING
        for poll_number in range(1, self.config.max_processing_polls + 1):
            video = self._read_video(video_id, expected_channel_id=external_account_id)
            if video is None:
                last_video = {"id": video_id, "poll": poll_number, "visible": False}
                publication_status = PublicationStatus.PROCESSING
            else:
                last_video = video
                publication_status = self._classify_video(video)
                if publication_status != PublicationStatus.PROCESSING:
                    break
            if poll_number < self.config.max_processing_polls:
                self._sleep(self.config.poll_interval_seconds)

        return ProofPublishReceipt(
            platform_post_id=video_id,
            status=publication_status,
            canonical_url=self._watch_url(video_id),
            raw={
                "upload": created,
                "video": last_video,
                "configured_privacy_status": self.config.privacy_status,
            },
        )

    def reconcile_publish(
        self,
        external_account_id: str,
        *,
        platform_post_id: str | None,
        idempotency_key: str,
        remote_context: dict[str, Any] | None = None,
    ) -> ProofPostStatus:
        del idempotency_key
        context = remote_context or {}
        video_id = platform_post_id or self._string_or_none(context.get("media_id"))
        if not video_id:
            return ProofPostStatus(
                status=PublicationStatus.PROCESSING,
                platform_post_id=None,
                raw={
                    "recovery": "manual",
                    "reason": "video id unavailable; do not upload again automatically",
                },
            )

        video = self._read_video(video_id, expected_channel_id=external_account_id)
        if video is None:
            return ProofPostStatus(
                status=PublicationStatus.PROCESSING,
                platform_post_id=video_id,
                canonical_url=self._watch_url(video_id),
                raw={"video_id": video_id, "visible_to_api": False},
            )
        return ProofPostStatus(
            status=self._classify_video(video),
            platform_post_id=video_id,
            canonical_url=self._watch_url(video_id),
            raw=video,
        )

    def fetch_metrics(
        self, external_account_id: str, *, platform_post_id: str
    ) -> ProofMetricSnapshot:
        video = self._read_video(
            platform_post_id,
            expected_channel_id=external_account_id,
            parts="snippet,status,statistics",
        )
        if video is None:
            raise YouTubeAPIError("video metrics lookup returned no owned video")

        statistics = video.get("statistics") if isinstance(video.get("statistics"), dict) else {}
        metrics: dict[str, Any] = {}
        for source_key, target_key in (
            ("viewCount", "data_api_view_count"),
            ("likeCount", "data_api_like_count"),
            ("commentCount", "data_api_comment_count"),
        ):
            if source_key in statistics:
                metrics[target_key] = self._integer_or_original(statistics[source_key])

        today = self._now().date()
        start_date = today - timedelta(days=self.config.analytics_window_days - 1)
        analytics = self._analytics_query(
            start_date=start_date,
            end_date=today,
            metrics=(
                "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
                "likes,comments,shares,subscribersGained"
            ),
            filters=f"video=={platform_post_id}",
        )
        metrics.update(self._first_analytics_row(analytics))
        return ProofMetricSnapshot(
            metrics=metrics,
            raw={"data_api_video": video, "analytics": analytics},
        )

    def _owned_channel(self, external_account_id: str) -> dict[str, Any]:
        payload = self._request_json(
            "GET",
            f"{self.config.data_base_url.rstrip('/')}/channels",
            params={"part": "id,snippet", "mine": "true"},
            stage="owned channel inspection",
        )
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        matches = [
            item
            for item in items
            if isinstance(item, dict) and str(item.get("id")) == external_account_id
        ]
        if len(matches) != 1:
            raise YouTubeAPIError("authenticated YouTube channel does not match configured account")
        return matches[0]

    def _start_upload_session(
        self,
        *,
        metadata: dict[str, Any],
        file_size: int,
        content_type: str,
    ) -> str:
        url = f"{self.config.upload_base_url.rstrip('/')}/videos"
        try:
            response = self._client.post(
                url,
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers={
                    **self._auth_header(),
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Length": str(file_size),
                    "X-Upload-Content-Type": content_type,
                },
                json=metadata,
                timeout=self.config.request_timeout_seconds,
            )
        except httpx.TransportError as exc:
            raise YouTubeAPIError("transport failed while creating YouTube upload session") from exc
        if response.is_error:
            self._raise_api_error(response, "upload session creation")
        upload_url = response.headers.get("Location", "").strip()
        if not upload_url:
            raise YouTubeAPIError("YouTube upload session response did not include Location")
        self._validate_upload_session_url(upload_url)
        return upload_url

    def _upload_binary(
        self,
        *,
        upload_url: str,
        media_path: Path,
        file_size: int,
        content_type: str,
    ) -> dict[str, Any]:
        try:
            with media_path.open("rb") as media_file:
                response = self._client.put(
                    upload_url,
                    headers={
                        **self._auth_header(),
                        "Content-Length": str(file_size),
                        "Content-Type": content_type,
                    },
                    content=media_file,
                    timeout=self.config.request_timeout_seconds,
                )
        except httpx.TransportError as exc:
            raise AmbiguousRemotePublishError(
                "transport failed after YouTube binary upload may have started",
                remote_context={"stage": "UPLOAD_BINARY_AMBIGUOUS"},
            ) from exc

        if response.status_code == 308:
            raise AmbiguousRemotePublishError(
                "YouTube upload is incomplete and requires supervised resumable recovery",
                remote_context={"stage": "UPLOAD_INCOMPLETE"},
            )
        if response.status_code >= 500:
            raise AmbiguousRemotePublishError(
                f"YouTube upload returned HTTP {response.status_code} after binary send",
                remote_context={"stage": "UPLOAD_BINARY_AMBIGUOUS"},
            )
        if response.is_error:
            self._raise_api_error(response, "binary upload")

        try:
            payload = response.json()
        except ValueError as exc:
            raise AmbiguousRemotePublishError(
                "YouTube upload returned an unreadable success response",
                remote_context={"stage": "UPLOAD_SUCCESS_RESPONSE_UNREADABLE"},
            ) from exc
        if not isinstance(payload, dict):
            raise AmbiguousRemotePublishError(
                "YouTube upload returned a non-object success response",
                remote_context={"stage": "UPLOAD_SUCCESS_RESPONSE_UNREADABLE"},
            )
        return payload

    def _read_video(
        self,
        video_id: str,
        *,
        expected_channel_id: str,
        parts: str = "snippet,status,processingDetails",
    ) -> dict[str, Any] | None:
        payload = self._request_json(
            "GET",
            f"{self.config.data_base_url.rstrip('/')}/videos",
            params={"part": parts, "id": video_id},
            stage="video status lookup",
        )
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        if not items:
            return None
        video = items[0]
        if not isinstance(video, dict):
            raise YouTubeAPIError("video status lookup returned malformed item")
        snippet = video.get("snippet") if isinstance(video.get("snippet"), dict) else {}
        channel_id = self._string_or_none(snippet.get("channelId"))
        if channel_id and channel_id != expected_channel_id:
            raise YouTubeAPIError("video does not belong to configured YouTube channel")
        return video

    def _analytics_query(
        self,
        *,
        start_date,
        end_date,
        metrics: str,
        filters: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "ids": "channel==MINE",
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "metrics": metrics,
        }
        if filters:
            params["filters"] = filters
        return self._request_json(
            "GET",
            f"{self.config.analytics_base_url.rstrip('/')}/reports",
            params=params,
            stage="YouTube Analytics query",
        )

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        stage: str,
    ) -> dict[str, Any]:
        try:
            response = self._client.request(
                method,
                url,
                headers=self._auth_header(),
                params=params,
                timeout=self.config.request_timeout_seconds,
            )
        except httpx.TransportError as exc:
            raise YouTubeAPIError(f"transport failed during {stage}") from exc
        if response.is_error:
            self._raise_api_error(response, stage)
        try:
            payload = response.json()
        except ValueError as exc:
            raise YouTubeAPIError(f"non-JSON response during {stage}") from exc
        if not isinstance(payload, dict):
            raise YouTubeAPIError(f"non-object response during {stage}")
        return payload

    def _raise_api_error(self, response: httpx.Response, stage: str) -> None:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        error = (
            payload.get("error")
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict)
            else {}
        )
        message = self._redact(str(error.get("message") or f"HTTP {response.status_code}"))
        code = error.get("code")
        summary = f"{stage} failed: {message}"
        if code is not None:
            summary += f" [code={code}]"
        raise YouTubeAPIError(summary)

    def _validate_media_path(self, media_uri: str) -> Path:
        parsed = urlparse(media_uri)
        if parsed.scheme and parsed.scheme.lower() != "file":
            raise ValueError("YouTube proof media_uri must be a local video file path")
        path = Path(parsed.path if parsed.scheme.lower() == "file" else media_uri).expanduser()
        if not path.is_file():
            raise ValueError("YouTube proof media file does not exist")
        if path.stat().st_size <= 0:
            raise ValueError("YouTube proof media file is empty")
        return path.resolve()

    def _validate_upload_session_url(self, upload_url: str) -> None:
        session = urlparse(upload_url)
        configured = urlparse(self.config.upload_base_url)
        if session.scheme.lower() != "https" or not session.hostname:
            raise YouTubeAPIError("YouTube resumable upload session URL is not HTTPS")
        if configured.hostname and session.hostname.lower() != configured.hostname.lower():
            raise YouTubeAPIError(
                "YouTube resumable upload session host does not match configured API host"
            )

    @staticmethod
    def _classify_video(video: dict[str, Any]) -> PublicationStatus:
        status = video.get("status") if isinstance(video.get("status"), dict) else {}
        processing = (
            video.get("processingDetails")
            if isinstance(video.get("processingDetails"), dict)
            else {}
        )
        upload_status = str(status.get("uploadStatus") or "").lower()
        processing_status = str(processing.get("processingStatus") or "").lower()
        if upload_status in {"deleted", "failed", "rejected"} or processing_status == "failed":
            return PublicationStatus.REJECTED
        if upload_status == "processed" or processing_status == "succeeded":
            return PublicationStatus.PUBLISHED
        return PublicationStatus.PROCESSING

    @staticmethod
    def _first_analytics_row(payload: dict[str, Any]) -> dict[str, Any]:
        headers = (
            payload.get("columnHeaders")
            if isinstance(payload.get("columnHeaders"), list)
            else []
        )
        rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
        if not rows or not isinstance(rows[0], list):
            return {}
        names = [
            str(header.get("name"))
            for header in headers
            if isinstance(header, dict) and header.get("name")
        ]
        return {name: value for name, value in zip(names, rows[0], strict=False)}

    @staticmethod
    def _analytics_columns(payload: dict[str, Any]) -> list[str]:
        headers = (
            payload.get("columnHeaders")
            if isinstance(payload.get("columnHeaders"), list)
            else []
        )
        return [
            str(header.get("name"))
            for header in headers
            if isinstance(header, dict) and header.get("name")
        ]

    def _auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.access_token}"}

    def _redact(self, value: str) -> str:
        return value.replace(self.config.access_token, "[REDACTED]")

    @staticmethod
    def _checkpoint(checkpoint: ProofCheckpoint | None, context: dict[str, Any]) -> None:
        if checkpoint is not None:
            checkpoint(context)

    @staticmethod
    def _integer_or_original(value: Any) -> Any:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value

    @staticmethod
    def _watch_url(video_id: str) -> str:
        return f"https://www.youtube.com/watch?v={video_id}"

    @staticmethod
    def _string_or_none(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
