from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
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


class TikTokProofError(RuntimeError):
    pass


class TikTokAPIError(TikTokProofError):
    pass


@dataclass(frozen=True)
class TikTokProofConfig:
    access_token: str = field(repr=False)
    api_version: str = "v1.3"
    base_url: str = "https://business-api.tiktok.com/open_api"
    verified_media_hosts: tuple[str, ...] = ()
    verified_media_prefixes: tuple[str, ...] = ()
    max_status_polls: int = 5
    poll_interval_seconds: float = 10.0
    request_timeout_seconds: float = 30.0
    disable_comment: bool = False
    disable_duet: bool = False
    disable_stitch: bool = False
    metric_fields: tuple[str, ...] = (
        "item_id",
        "caption",
        "likes",
        "comments",
        "shares",
        "video_views",
        "create_time",
        "total_time_watched",
        "average_time_watched",
        "reach",
        "full_video_watched_rate",
    )

    def __post_init__(self) -> None:
        if not self.access_token.strip():
            raise ValueError("access_token is required")
        if not self.api_version.strip():
            raise ValueError("api_version is required")
        if not self.verified_media_hosts and not self.verified_media_prefixes:
            raise ValueError("at least one verified media host or URL prefix is required")
        if self.max_status_polls < 1:
            raise ValueError("max_status_polls must be at least 1")
        if self.poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds cannot be negative")


class TikTokProofAdapter:
    """Proof-only adapter for TikTok API for Business Organic Accounts API."""

    platform = "TIKTOK"
    api_family = "tiktok-business-organic-v1"

    _PROCESSING_STATES = frozenset({
        "PROCESSING",
        "PROCESSING_DOWNLOAD",
        "DOWNLOADING",
        "PENDING",
        "QUEUED",
    })
    _COMPLETE_STATES = frozenset({"PUBLISH_COMPLETE", "PUBLISHED", "SUCCESS", "COMPLETE"})
    _FAILED_STATES = frozenset({"FAILED", "FAIL", "PUBLISH_FAILED"})
    _INBOX_STATES = frozenset({"SEND_TO_USER_INBOX"})

    def __init__(
        self,
        config: TikTokProofConfig,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._client = client or httpx.Client(timeout=config.request_timeout_seconds)
        self._sleep = sleep

    def inspect_capabilities(self, external_account_id: str) -> CapabilityReport:
        token_info = self._request_data(
            "GET",
            "/tt_user/token_info/get/",
            stage="access-token scope inspection",
        )
        profile = self._request_data(
            "GET",
            "/business/get/",
            params={
                "business_id": external_account_id,
                "fields": json.dumps(
                    ["display_name", "username", "followers_count", "likes"],
                    separators=(",", ":"),
                ),
            },
            stage="business profile inspection",
        )
        self._verify_profile_identity(external_account_id, profile)

        publish_support = CapabilitySupport.REQUIRES_PROOF
        settings_evidence: dict[str, Any]
        try:
            settings = self._request_data(
                "GET",
                "/business/video/settings/",
                params={"business_id": external_account_id},
                stage="video publishing settings probe",
            )
            publish_support = CapabilitySupport.SUPPORTED
            settings_evidence = self._safe_payload(settings)
        except TikTokAPIError as exc:
            settings_evidence = {"available": False, "error": str(exc)}

        metrics_support = CapabilitySupport.REQUIRES_PROOF
        metrics_probe: dict[str, Any]
        try:
            raw = self._video_list(
                external_account_id,
                fields=("item_id", "video_views"),
            )
            metrics_support = CapabilitySupport.SUPPORTED
            metrics_probe = {
                "available": True,
                "returned_items": len(self._video_items(raw)),
            }
        except TikTokAPIError as exc:
            metrics_probe = {"available": False, "error": str(exc)}

        return CapabilityReport(
            api_family=self.api_family,
            api_version=self.config.api_version,
            capabilities={
                "can_publish_video": publish_support,
                "can_read_publish_status": publish_support,
                "can_read_post_metrics": metrics_support,
                "can_use_verified_media_url": CapabilitySupport.REQUIRES_PROOF,
                "can_attach_platform_catalog_audio": CapabilitySupport.REQUIRES_PROOF,
                "can_use_owned_sound": CapabilitySupport.REQUIRES_PROOF,
                "can_set_synthetic_media_disclosure": CapabilitySupport.UNKNOWN,
            },
            evidence={
                "token_scopes": self._extract_scope_names(token_info),
                "profile": self._profile_evidence(external_account_id, profile),
                "video_settings": settings_evidence,
                "metrics_probe": metrics_probe,
                "verified_media_configuration": {
                    "hosts": list(self.config.verified_media_hosts),
                    "prefixes": list(self.config.verified_media_prefixes),
                    "platform_verification": "requires controlled proof",
                },
                "documentation": {
                    "api_family": "TikTok API for Business / Organic API / Accounts API",
                    "publish": "/business/video/publish/",
                    "status": "/business/publish/status/",
                    "metrics": "/business/video/list/",
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

        payload = {
            "business_id": external_account_id,
            "video_url": request.media_uri,
            "post_info": {
                "caption": request.caption,
                "disable_comment": self.config.disable_comment,
                "disable_duet": self.config.disable_duet,
                "disable_stitch": self.config.disable_stitch,
            },
        }
        created = self._request_data(
            "POST",
            "/business/video/publish/",
            json_body=payload,
            stage="public video publish",
            ambiguous_after_send=True,
        )
        publish_id = self._first_string(created, "share_id", "publish_id")
        if not publish_id:
            raise AmbiguousRemotePublishError(
                "TikTok accepted the publish request but returned no publish task id"
            )

        try:
            self._checkpoint(
                checkpoint,
                {"stage": "PUBLISH_TASK_CREATED", "publish_id": publish_id},
            )
        except Exception as exc:
            raise AmbiguousRemotePublishError(
                "TikTok publish task was created but durable checkpoint failed",
                remote_context={
                    "stage": "PUBLISH_TASK_CREATED_UNCHECKPOINTED",
                    "publish_id": publish_id,
                },
            ) from exc

        for poll_number in range(1, self.config.max_status_polls + 1):
            status_data = self._publish_status(external_account_id, publish_id)
            state = self._publish_state(status_data)
            post_ids = self._post_ids(status_data)

            if state in self._COMPLETE_STATES and post_ids:
                post_id = post_ids[0]
                try:
                    self._checkpoint(
                        checkpoint,
                        {
                            "stage": "POST_PUBLISHED",
                            "publish_id": publish_id,
                            "post_id": post_id,
                        },
                    )
                except Exception as exc:
                    raise AmbiguousRemotePublishError(
                        "TikTok post published but durable post checkpoint failed",
                        remote_context={
                            "stage": "POST_PUBLISHED_UNCHECKPOINTED",
                            "publish_id": publish_id,
                            "post_id": post_id,
                        },
                    ) from exc
                return ProofPublishReceipt(
                    platform_post_id=post_id,
                    status=PublicationStatus.PUBLISHED,
                    raw={
                        "publish_id": publish_id,
                        "publish_status": self._safe_payload(status_data),
                    },
                )

            if state in self._FAILED_STATES:
                reason = self._failure_reason(status_data)
                raise TikTokAPIError(
                    f"TikTok publish task entered terminal state {state}: {reason}"
                )

            if state in self._INBOX_STATES:
                raise TikTokAPIError(
                    "TikTok routed the upload to user inbox instead of public publication"
                )

            if state in self._COMPLETE_STATES:
                if poll_number < self.config.max_status_polls:
                    self._sleep(self.config.poll_interval_seconds)
                    continue
                break

            if state not in self._PROCESSING_STATES:
                raise TikTokAPIError(
                    f"unknown TikTok publish status {state or 'MISSING'}; failing closed"
                )
            if poll_number < self.config.max_status_polls:
                self._sleep(self.config.poll_interval_seconds)

        raise AmbiguousRemotePublishError(
            "TikTok publish remains unresolved after bounded status polling",
            remote_context={
                "stage": "PUBLISH_STATUS_UNRESOLVED",
                "publish_id": publish_id,
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
        post_id = platform_post_id or self._first_string(context, "post_id", "video_id")
        if post_id:
            raw = self._video_list(
                external_account_id,
                video_ids=(post_id,),
                fields=("item_id", "caption", "create_time"),
            )
            item = self._find_video(raw, post_id)
            if item is None:
                return ProofPostStatus(
                    status=PublicationStatus.PROCESSING,
                    platform_post_id=post_id,
                    raw={
                        "reason": "known post id is not visible in business video list yet",
                        "video_list": self._safe_payload(raw),
                    },
                )
            return ProofPostStatus(
                status=PublicationStatus.PUBLISHED,
                platform_post_id=post_id,
                raw={"video": self._safe_payload(item)},
            )

        publish_id = self._first_string(context, "publish_id", "share_id")
        if not publish_id:
            return ProofPostStatus(
                status=PublicationStatus.PROCESSING,
                platform_post_id=None,
                raw={
                    "recovery": "manual",
                    "reason": "no durable TikTok post id or publish task id is available",
                },
            )

        data = self._publish_status(external_account_id, publish_id)
        state = self._publish_state(data)
        post_ids = self._post_ids(data)
        if state in self._COMPLETE_STATES and post_ids:
            return ProofPostStatus(
                status=PublicationStatus.PUBLISHED,
                platform_post_id=post_ids[0],
                raw={
                    "publish_id": publish_id,
                    "publish_status": self._safe_payload(data),
                },
            )
        if state in self._FAILED_STATES or state in self._INBOX_STATES:
            return ProofPostStatus(
                status=PublicationStatus.REJECTED,
                platform_post_id=None,
                raw={
                    "publish_id": publish_id,
                    "publish_status": self._safe_payload(data),
                },
            )
        if state in self._PROCESSING_STATES or state in self._COMPLETE_STATES:
            return ProofPostStatus(
                status=PublicationStatus.PROCESSING,
                platform_post_id=None,
                raw={
                    "publish_id": publish_id,
                    "publish_status": self._safe_payload(data),
                    "recovery": "status only; do not issue another publish request",
                },
            )
        raise TikTokAPIError(
            f"unknown TikTok publish status {state or 'MISSING'} during reconciliation"
        )

    def fetch_metrics(
        self, external_account_id: str, *, platform_post_id: str
    ) -> ProofMetricSnapshot:
        raw = self._video_list(
            external_account_id,
            video_ids=(platform_post_id,),
            fields=self.config.metric_fields,
        )
        item = self._find_video(raw, platform_post_id)
        if item is None:
            raise TikTokAPIError("target TikTok post is not available in business video insights")

        metrics = {
            key: item.get(key)
            for key in (
                "video_views",
                "likes",
                "comments",
                "shares",
                "total_time_watched",
                "average_time_watched",
                "reach",
                "full_video_watched_rate",
            )
            if key in item
        }
        return ProofMetricSnapshot(
            metrics=metrics,
            raw={"video": self._safe_payload(item), "response": self._safe_payload(raw)},
        )

    def _publish_status(self, business_id: str, publish_id: str) -> dict[str, Any]:
        return self._request_data(
            "GET",
            "/business/publish/status/",
            params={"business_id": business_id, "publish_id": publish_id},
            stage="publish status",
        )

    def _video_list(
        self,
        business_id: str,
        *,
        video_ids: tuple[str, ...] = (),
        fields: tuple[str, ...],
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "business_id": business_id,
            "fields": json.dumps(list(fields), separators=(",", ":")),
        }
        if video_ids:
            params["filters"] = json.dumps(
                {"video_ids": list(video_ids)},
                separators=(",", ":"),
            )
        return self._request_data(
            "GET",
            "/business/video/list/",
            params=params,
            stage="business video list",
        )

    def _request_data(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        stage: str,
        ambiguous_after_send: bool = False,
    ) -> dict[str, Any]:
        url = (
            f"{self.config.base_url.rstrip('/')}/"
            f"{self.config.api_version.strip('/')}/{path.lstrip('/')}"
        )
        try:
            response = self._client.request(
                method,
                url,
                headers={
                    "Access-Token": self.config.access_token,
                    "Content-Type": "application/json",
                },
                params=params,
                json=json_body,
                timeout=self.config.request_timeout_seconds,
            )
        except httpx.TransportError as exc:
            if ambiguous_after_send:
                raise AmbiguousRemotePublishError(
                    f"transport failed during {stage} after request may have been accepted"
                ) from exc
            raise TikTokAPIError(f"transport failed during {stage}") from exc

        try:
            decoded = response.json()
        except ValueError as exc:
            if ambiguous_after_send and response.is_success:
                raise AmbiguousRemotePublishError(
                    f"unreadable success response during {stage}"
                ) from exc
            raise TikTokAPIError(f"non-JSON response during {stage}") from exc

        if not isinstance(decoded, dict):
            raise TikTokAPIError(f"unexpected response shape during {stage}")

        if response.status_code >= 500 and ambiguous_after_send:
            raise AmbiguousRemotePublishError(
                f"TikTok server error during {stage} after request may have been accepted"
            )
        if response.is_error:
            raise TikTokAPIError(
                f"{stage} failed with HTTP {response.status_code}: "
                f"{self._redact(str(decoded.get('message') or 'request failed'))}"
            )

        code = decoded.get("code", 0)
        if str(code) not in {"0", "None"}:
            message = self._redact(str(decoded.get("message") or "TikTok API error"))
            raise TikTokAPIError(f"{stage} failed: {message} [code={code}]")

        data = decoded.get("data", {})
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise TikTokAPIError(f"unexpected data shape during {stage}")
        return self._safe_payload(data)

    def _validate_media_uri(self, media_uri: str) -> None:
        parsed = urlparse(media_uri)
        host = (parsed.hostname or "").lower()
        if parsed.scheme.lower() != "https" or not host:
            raise ValueError("TikTok proof media_uri must be a public HTTPS URL")

        configured_hosts = tuple(
            value.lower().strip(".") for value in self.config.verified_media_hosts
        )
        if any(host == value or host.endswith(f".{value}") for value in configured_hosts):
            return

        for raw_prefix in self.config.verified_media_prefixes:
            prefix = urlparse(raw_prefix)
            if prefix.scheme.lower() != "https" or not prefix.hostname:
                raise ValueError("configured TikTok verified media prefix must be HTTPS")
            if host != prefix.hostname.lower():
                continue
            prefix_path = prefix.path.rstrip("/") + "/"
            request_path = parsed.path
            if request_path.startswith(prefix_path):
                return
        raise ValueError(
            "TikTok proof media_uri is not covered by a configured verified URL property"
        )

    def _verify_profile_identity(self, external_account_id: str, profile: dict[str, Any]) -> None:
        returned = self._first_string(
            profile,
            "business_id",
            "open_id",
            "id",
        )
        if returned and returned != external_account_id:
            raise TikTokAPIError(
                "authorized TikTok account identity does not match configured account"
            )

    @staticmethod
    def _profile_evidence(
        external_account_id: str, profile: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "business_id": external_account_id,
            "username": profile.get("username"),
            "display_name": profile.get("display_name"),
            "followers_count": profile.get("followers_count"),
        }

    @staticmethod
    def _extract_scope_names(data: dict[str, Any]) -> list[str]:
        raw = data.get("scopes")
        if raw is None:
            raw = data.get("scope")
        if isinstance(raw, str):
            return [item.strip() for item in raw.replace(",", " ").split() if item.strip()]
        if isinstance(raw, list):
            names: list[str] = []
            for item in raw:
                if isinstance(item, str):
                    names.append(item)
                elif isinstance(item, dict):
                    name = item.get("scope") or item.get("name") or item.get("permission")
                    if name:
                        names.append(str(name))
            return names
        return []

    @classmethod
    def _publish_state(cls, data: dict[str, Any]) -> str:
        value = (
            data.get("status")
            or data.get("publish_status")
            or data.get("status_code")
            or ""
        )
        return str(value).strip().upper()

    @classmethod
    def _post_ids(cls, data: dict[str, Any]) -> list[str]:
        for key in ("post_ids", "video_ids", "item_ids"):
            value = data.get(key)
            if isinstance(value, list):
                return [str(item) for item in value if str(item).strip()]
            if value:
                return [str(value)]
        for key in ("post_id", "video_id", "item_id"):
            value = data.get(key)
            if value:
                return [str(value)]
        return []

    @staticmethod
    def _failure_reason(data: dict[str, Any]) -> str:
        for key in ("reason", "fail_reason", "error_message", "message"):
            value = data.get(key)
            if value:
                return str(value)
        return "no reason provided"

    @staticmethod
    def _video_items(data: dict[str, Any]) -> list[dict[str, Any]]:
        for key in ("videos", "list", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    @classmethod
    def _find_video(cls, data: dict[str, Any], post_id: str) -> dict[str, Any] | None:
        for item in cls._video_items(data):
            item_id = cls._first_string(item, "item_id", "video_id", "post_id", "id")
            if item_id == post_id:
                return item
        return None

    @staticmethod
    def _first_string(data: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = data.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    def _safe_payload(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): self._safe_payload(child)
                for key, child in value.items()
                if str(key).lower().replace("-", "_")
                not in {"access_token", "refresh_token", "client_secret", "app_secret"}
            }
        if isinstance(value, list):
            return [self._safe_payload(item) for item in value]
        if isinstance(value, tuple):
            return [self._safe_payload(item) for item in value]
        if isinstance(value, str):
            return self._redact(value)
        return value

    def _redact(self, value: str) -> str:
        return value.replace(self.config.access_token, "[REDACTED]")

    @staticmethod
    def _checkpoint(checkpoint: ProofCheckpoint | None, context: dict[str, Any]) -> None:
        if checkpoint is not None:
            checkpoint(context)
