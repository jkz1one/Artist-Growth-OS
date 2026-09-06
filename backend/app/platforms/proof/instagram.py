from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
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


class InstagramProofError(RuntimeError):
    pass


class InstagramAPIError(InstagramProofError):
    pass


@dataclass(frozen=True)
class InstagramProofConfig:
    api_version: str
    access_token: str
    allowed_media_hosts: tuple[str, ...]
    graph_base_url: str = "https://graph.instagram.com"
    share_to_feed: bool = False
    max_status_polls: int = 5
    poll_interval_seconds: float = 60.0
    request_timeout_seconds: float = 30.0
    insight_metrics: tuple[str, ...] = (
        "views",
        "reach",
        "likes",
        "comments",
        "shares",
        "saved",
    )

    def __post_init__(self) -> None:
        if not self.api_version.strip():
            raise ValueError("api_version is required")
        if not self.access_token.strip():
            raise ValueError("access_token is required")
        if not self.allowed_media_hosts:
            raise ValueError("at least one allowed media host is required")
        if self.max_status_polls < 1:
            raise ValueError("max_status_polls must be at least 1")
        if self.poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds cannot be negative")


class InstagramProofAdapter:
    """Proof-only Instagram adapter using Business Login for Instagram endpoints."""

    platform = "INSTAGRAM"
    api_family = "instagram-api-instagram-login-v1"

    def __init__(
        self,
        config: InstagramProofConfig,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._client = client or httpx.Client(timeout=config.request_timeout_seconds)
        self._sleep = sleep

    def inspect_capabilities(self, external_account_id: str) -> CapabilityReport:
        account = self._request_json(
            "GET",
            f"/{external_account_id}",
            params={"fields": "id,username"},
            stage="account inspection",
        )
        if str(account.get("id")) != external_account_id:
            raise InstagramAPIError("authorized account identity does not match configured account")

        publishing_limit: dict[str, Any] | None = None
        publish_support = CapabilitySupport.REQUIRES_PROOF
        try:
            publishing_limit = self._request_json(
                "GET",
                f"/{external_account_id}/content_publishing_limit",
                params={"fields": "config,quota_usage"},
                stage="content publishing capability probe",
            )
            publish_support = CapabilitySupport.SUPPORTED
        except InstagramAPIError as exc:
            publishing_limit = {"available": False, "error": str(exc)}

        insights_probe: dict[str, Any] | None = None
        metrics_support = CapabilitySupport.REQUIRES_PROOF
        try:
            insights_probe = self._request_json(
                "GET",
                f"/{external_account_id}/insights",
                params={"metric": "reach", "period": "day"},
                stage="insights capability probe",
            )
            metrics_support = CapabilitySupport.SUPPORTED
        except InstagramAPIError as exc:
            insights_probe = {"available": False, "error": str(exc)}

        return CapabilityReport(
            api_family=self.api_family,
            api_version=self.config.api_version,
            capabilities={
                "can_publish_video": publish_support,
                "can_read_publish_status": publish_support,
                "can_read_post_metrics": metrics_support,
                "can_attach_platform_catalog_audio": CapabilitySupport.REQUIRES_PROOF,
                "can_use_owned_sound": CapabilitySupport.REQUIRES_PROOF,
                "can_trial_reels": CapabilitySupport.UNKNOWN,
                "can_set_synthetic_media_disclosure": CapabilitySupport.UNKNOWN,
            },
            evidence={
                "account": {"id": account.get("id"), "username": account.get("username")},
                "content_publishing_limit": publishing_limit,
                "insights_probe": insights_probe,
                "documentation": {
                    "publish": "Meta Instagram API / Publish Content / Reels",
                    "insights": "Meta Instagram API / Insights",
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
        self._validate_media_uri(request.media_uri)
        created = self._request_json(
            "POST",
            f"/{external_account_id}/media",
            data={
                "media_type": "REELS",
                "video_url": request.media_uri,
                "caption": request.caption,
                "share_to_feed": str(self.config.share_to_feed).lower(),
            },
            stage="reel container creation",
        )
        container_id = str(created.get("id") or "")
        if not container_id:
            raise InstagramAPIError("reel container creation returned no container id")
        self._checkpoint(checkpoint, {"stage": "CONTAINER_CREATED", "container_id": container_id})

        final_status: dict[str, Any] | None = None
        for poll_number in range(1, self.config.max_status_polls + 1):
            status = self._request_json(
                "GET",
                f"/{container_id}",
                params={"fields": "status_code,status"},
                stage="reel container status",
            )
            code = str(status.get("status_code") or "").upper()
            final_status = {
                "status_code": code,
                "status": status.get("status"),
                "poll": poll_number,
            }
            if code == "FINISHED":
                self._checkpoint(
                    checkpoint,
                    {
                        "stage": "CONTAINER_FINISHED",
                        "container_id": container_id,
                        "container_status": code,
                    },
                )
                break
            if code in {"ERROR", "EXPIRED"}:
                raise InstagramAPIError(f"reel container entered terminal state {code}")
            if code == "PUBLISHED":
                self._checkpoint(
                    checkpoint,
                    {
                        "stage": "CONTAINER_ALREADY_PUBLISHED",
                        "container_id": container_id,
                        "container_status": code,
                    },
                )
                raise AmbiguousRemotePublishError(
                    "container is already PUBLISHED before this proof received a media id"
                )
            if code != "IN_PROGRESS":
                raise InstagramAPIError(f"unexpected reel container status {code or 'MISSING'}")
            if poll_number < self.config.max_status_polls:
                self._sleep(self.config.poll_interval_seconds)
        else:
            raise InstagramAPIError("reel container did not finish within bounded polling window")

        self._checkpoint(
            checkpoint,
            {"stage": "MEDIA_PUBLISH_STARTING", "container_id": container_id},
        )
        published = self._request_json(
            "POST",
            f"/{external_account_id}/media_publish",
            data={"creation_id": container_id},
            stage="media publish",
            ambiguous_after_send=True,
        )
        media_id = str(published.get("id") or "")
        if not media_id:
            raise AmbiguousRemotePublishError("media_publish returned no media id")
        try:
            self._checkpoint(
                checkpoint,
                {
                    "stage": "MEDIA_PUBLISHED",
                    "container_id": container_id,
                    "media_id": media_id,
                },
            )
        except Exception as exc:
            raise AmbiguousRemotePublishError(
                "media was published but durable remote checkpoint failed",
                remote_context={
                    "stage": "MEDIA_PUBLISHED_UNCHECKPOINTED",
                    "container_id": container_id,
                    "media_id": media_id,
                },
            ) from exc

        return ProofPublishReceipt(
            platform_post_id=media_id,
            status=PublicationStatus.PUBLISHED,
            raw={
                "container_id": container_id,
                "media_id": media_id,
                "container_status": final_status,
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
        context = remote_context or {}
        media_id = platform_post_id or self._string_or_none(context.get("media_id"))
        if media_id:
            media = self._request_json(
                "GET",
                f"/{media_id}",
                params={"fields": "id,media_type,permalink,timestamp"},
                stage="published media reconciliation",
            )
            return ProofPostStatus(
                status=PublicationStatus.PUBLISHED,
                platform_post_id=str(media.get("id") or media_id),
                canonical_url=self._string_or_none(media.get("permalink")),
                raw={
                    "id": media.get("id"),
                    "media_type": media.get("media_type"),
                    "permalink": media.get("permalink"),
                    "timestamp": media.get("timestamp"),
                },
            )

        container_id = self._string_or_none(context.get("container_id"))
        if not container_id:
            return ProofPostStatus(
                status=PublicationStatus.PROCESSING,
                platform_post_id=None,
                raw={
                    "recovery": "manual",
                    "reason": "no durable media or container id is available",
                },
            )

        container = self._request_json(
            "GET",
            f"/{container_id}",
            params={"fields": "status_code,status"},
            stage="container reconciliation",
        )
        code = str(container.get("status_code") or "").upper()
        if code in {"ERROR", "EXPIRED"}:
            return ProofPostStatus(
                status=PublicationStatus.REJECTED,
                platform_post_id=None,
                raw={"container_id": container_id, "status_code": code},
            )
        return ProofPostStatus(
            status=PublicationStatus.PROCESSING,
            platform_post_id=None,
            raw={
                "container_id": container_id,
                "status_code": code,
                "recovery": "media id unavailable; do not republish automatically",
            },
        )

    def fetch_metrics(
        self, external_account_id: str, *, platform_post_id: str
    ) -> ProofMetricSnapshot:
        raw = self._request_json(
            "GET",
            f"/{platform_post_id}/insights",
            params={"metric": ",".join(self.config.insight_metrics)},
            stage="media insights",
        )
        metrics: dict[str, Any] = {}
        for item in raw.get("data", []):
            if not isinstance(item, dict) or not item.get("name"):
                continue
            value: Any = None
            values = item.get("values")
            if isinstance(values, list) and values and isinstance(values[-1], dict):
                value = values[-1].get("value")
            total_value = item.get("total_value")
            if value is None and isinstance(total_value, dict):
                value = total_value.get("value")
            metrics[str(item["name"])] = value
        return ProofMetricSnapshot(metrics=metrics, raw=raw)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        stage: str,
        ambiguous_after_send: bool = False,
    ) -> dict[str, Any]:
        url = (
            f"{self.config.graph_base_url.rstrip('/')}/"
            f"{self.config.api_version}/{path.lstrip('/')}"
        )
        try:
            response = self._client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {self.config.access_token}"},
                params=params,
                data=data,
                timeout=self.config.request_timeout_seconds,
            )
        except httpx.TransportError as exc:
            if ambiguous_after_send:
                raise AmbiguousRemotePublishError(
                    f"transport failed during {stage} after request may have been sent"
                ) from exc
            raise InstagramAPIError(f"transport failed during {stage}") from exc

        payload: dict[str, Any]
        try:
            decoded = response.json()
            payload = decoded if isinstance(decoded, dict) else {"data": decoded}
        except ValueError as exc:
            if ambiguous_after_send and response.is_success:
                raise AmbiguousRemotePublishError(
                    f"unreadable success response during {stage}"
                ) from exc
            raise InstagramAPIError(f"non-JSON response during {stage}") from exc

        if response.is_error:
            error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            message = self._redact(str(error.get("message") or f"HTTP {response.status_code}"))
            error_type = self._redact(str(error.get("type") or ""))
            code = error.get("code")
            summary = f"{stage} failed: {message}"
            if error_type:
                summary += f" ({error_type})"
            if code is not None:
                summary += f" [code={code}]"
            if ambiguous_after_send and response.status_code >= 500:
                raise AmbiguousRemotePublishError(summary)
            raise InstagramAPIError(summary)
        return payload

    def _validate_media_uri(self, media_uri: str) -> None:
        parsed = urlparse(media_uri)
        host = (parsed.hostname or "").lower()
        if parsed.scheme.lower() != "https" or not host:
            raise ValueError("Instagram proof media_uri must be a public HTTPS URL")
        allowed = tuple(value.lower() for value in self.config.allowed_media_hosts)
        if not any(host == value or host.endswith(f".{value}") for value in allowed):
            raise ValueError("Instagram proof media_uri host is not in the controlled allowlist")

    @staticmethod
    def _checkpoint(checkpoint: ProofCheckpoint | None, context: dict[str, Any]) -> None:
        if checkpoint is not None:
            checkpoint(context)

    def _redact(self, value: str) -> str:
        return value.replace(self.config.access_token, "[REDACTED]")

    @staticmethod
    def _string_or_none(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
