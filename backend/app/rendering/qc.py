from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from app.domain.enums import DecisionStatus


class MediaQC:
    def inspect(self, path: Path, *, width: int, height: int, expect_audio: bool) -> tuple[DecisionStatus, dict[str, Any]]:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return DecisionStatus.RESTRICTED, {"error": proc.stderr.strip() or "ffprobe failed"}

        data = json.loads(proc.stdout)
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        checks = {
            "video_present": video is not None,
            "video_codec_h264": bool(video and video.get("codec_name") == "h264"),
            "resolution": bool(video and video.get("width") == width and video.get("height") == height),
            "audio_expected": expect_audio,
            "audio_present": audio is not None,
            "audio_codec_aac": bool(audio and audio.get("codec_name") == "aac"),
            "duration_positive": float(data.get("format", {}).get("duration", 0) or 0) > 0,
        }
        required = [checks["video_present"], checks["video_codec_h264"], checks["resolution"], checks["duration_positive"]]
        if expect_audio:
            required.extend([checks["audio_present"], checks["audio_codec_aac"]])
        status = DecisionStatus.CLEAR if all(required) else DecisionStatus.RESTRICTED
        return status, {"checks": checks, "probe": data}
