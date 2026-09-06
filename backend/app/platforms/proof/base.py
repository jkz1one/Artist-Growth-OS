from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.domain.enums import CapabilitySupport, PublicationStatus


@dataclass(frozen=True)
class CapabilityReport:
    api_family: str
    api_version: str | None
    capabilities: dict[str, CapabilitySupport]
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProofPublishRequest:
    media_uri: str
    caption: str
    idempotency_key: str


@dataclass(frozen=True)
class ProofPublishReceipt:
    platform_post_id: str
    status: PublicationStatus
    canonical_url: str | None = None
    published_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProofPostStatus:
    status: PublicationStatus
    platform_post_id: str | None
    canonical_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProofMetricSnapshot:
    metrics: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict)


class PlatformProofAdapter(Protocol):
    platform: str
    api_family: str

    def inspect_capabilities(self, external_account_id: str) -> CapabilityReport: ...

    def publish_controlled(
        self, external_account_id: str, request: ProofPublishRequest
    ) -> ProofPublishReceipt: ...

    def reconcile_publish(
        self,
        external_account_id: str,
        *,
        platform_post_id: str | None,
        idempotency_key: str,
    ) -> ProofPostStatus: ...

    def fetch_metrics(
        self, external_account_id: str, *, platform_post_id: str
    ) -> ProofMetricSnapshot: ...
