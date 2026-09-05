from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class SourceClip(BaseModel):
    path: str
    start_ms: int = 0
    end_ms: int

    @model_validator(mode="after")
    def validate_window(self) -> "SourceClip":
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("invalid source clip window")
        return self


class AudioSlice(BaseModel):
    path: str
    start_ms: int
    end_ms: int

    @model_validator(mode="after")
    def validate_window(self) -> "AudioSlice":
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("invalid audio window")
        return self


class DeterministicRenderPlan(BaseModel):
    version: int = 1
    width: int = 1080
    height: int = 1920
    fps: int = 30
    video: SourceClip
    audio: AudioSlice | None = None
    duration_ms: int = Field(gt=0, le=60_000)

    @model_validator(mode="after")
    def validate_duration(self) -> "DeterministicRenderPlan":
        if self.video.end_ms - self.video.start_ms < self.duration_ms:
            raise ValueError("video source window shorter than render duration")
        if self.audio and self.audio.end_ms - self.audio.start_ms < self.duration_ms:
            raise ValueError("audio source window shorter than render duration")
        return self

    def stable_hash(self) -> str:
        payload = self.model_dump(mode="json")
        payload["video"]["path"] = str(Path(payload["video"]["path"]).resolve())
        if payload.get("audio"):
            payload["audio"]["path"] = str(Path(payload["audio"]["path"]).resolve())
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()
