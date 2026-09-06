from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.domain.enums import CapabilitySupport, PublicationStatus
from app.platforms.proof.base import (
    CapabilityReport,
    ProofCheckpoint,
    ProofMetricSnapshot,
    ProofPostStatus,
    ProofPublishReceipt,
    ProofPublishRequest,
)


class FakePlatformProofAdapter:
    platform = "FAKE"
    api_family = "fake-proof-v1"

    def __init__(self) -> None:
        self.publish_calls = 0
        self.metric_calls = 0
        self.fail_metrics_once = False
        self._posts: dict[str, ProofPublishReceipt] = {}

    def inspect_capabilities(self, external_account_id: str) -> CapabilityReport:
        return CapabilityReport(
            api_family=self.api_family,
            api_version="v1",
            capabilities={
                "can_publish_video": CapabilitySupport.SUPPORTED,
                "can_read_publish_status": CapabilitySupport.SUPPORTED,
                "can_read_post_metrics": CapabilitySupport.SUPPORTED,
                "can_attach_platform_catalog_audio": CapabilitySupport.REQUIRES_PROOF,
                "can_set_synthetic_media_disclosure": CapabilitySupport.UNKNOWN,
            },
            evidence={"source": "fake-contract"},
        )

    def publish_controlled(
        self,
        external_account_id: str,
        request: ProofPublishRequest,
        *,
        checkpoint: ProofCheckpoint | None = None,
    ) -> ProofPublishReceipt:
        self.publish_calls += 1
        existing = self._posts.get(request.idempotency_key)
        if existing is not None:
            return existing
        post_id = "proof_" + hashlib.sha256(request.idempotency_key.encode()).hexdigest()[:16]
        receipt = ProofPublishReceipt(
            platform_post_id=post_id,
            status=PublicationStatus.PUBLISHED,
            canonical_url=f"https://fake.publisher.local/posts/{post_id}",
            published_at=datetime.now(UTC),
            raw={"post_id": post_id},
        )
        self._posts[request.idempotency_key] = receipt
        if checkpoint is not None:
            checkpoint({"stage": "MEDIA_PUBLISHED", "media_id": post_id})
        return receipt

    def reconcile_publish(
        self,
        external_account_id: str,
        *,
        platform_post_id: str | None,
        idempotency_key: str,
        remote_context: dict[str, object] | None = None,
    ) -> ProofPostStatus:
        receipt = self._posts.get(idempotency_key)
        if receipt is None:
            return ProofPostStatus(
                status=PublicationStatus.RETRYABLE,
                platform_post_id=platform_post_id,
                raw={"found": False},
            )
        return ProofPostStatus(
            status=receipt.status,
            platform_post_id=receipt.platform_post_id,
            canonical_url=receipt.canonical_url,
            raw={"found": True},
        )

    def fetch_metrics(
        self, external_account_id: str, *, platform_post_id: str
    ) -> ProofMetricSnapshot:
        self.metric_calls += 1
        if self.fail_metrics_once:
            self.fail_metrics_once = False
            raise RuntimeError("metrics temporarily unavailable")
        return ProofMetricSnapshot(
            metrics={"views": 100, "likes": 10, "shares": 3},
            raw={"video_id": platform_post_id, "views": 100},
        )
