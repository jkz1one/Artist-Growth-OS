from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class PublishRequest:
    candidate_id: str
    media_path: Path
    idempotency_key: str
    caption: str = ""


@dataclass(frozen=True)
class PublishResult:
    platform_post_id: str
    status: str
    published_at: datetime
    canonical_url: str


class Publisher(Protocol):
    platform: str

    def publish(self, request: PublishRequest) -> PublishResult: ...
