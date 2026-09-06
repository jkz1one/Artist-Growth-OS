from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.domain.enums import PublicationStatus
from app.platforms.base import PublishRequest, PublishResult


class FakePublisher:
    platform = "FAKE"

    def __init__(self) -> None:
        self._results: dict[str, PublishResult] = {}

    def publish(self, request: PublishRequest) -> PublishResult:
        existing = self._results.get(request.idempotency_key)
        if existing:
            return existing

        post_id = "fake_" + hashlib.sha256(request.idempotency_key.encode()).hexdigest()[:16]
        result = PublishResult(
            platform_post_id=post_id,
            status=PublicationStatus.PUBLISHED,
            published_at=datetime.now(UTC),
            canonical_url=f"https://fake.publisher.local/posts/{post_id}",
        )
        self._results[request.idempotency_key] = result
        return result
