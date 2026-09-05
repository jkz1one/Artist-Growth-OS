from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from app.schemas.rendering import DeterministicRenderPlan


class RenderError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FFmpegRenderer:
    def render(self, plan: DeterministicRenderPlan, output_path: Path) -> str:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        duration_s = plan.duration_ms / 1000
        video_start = plan.video.start_ms / 1000

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{video_start:.3f}",
            "-i",
            plan.video.path,
        ]

        if plan.audio:
            cmd += [
                "-ss",
                f"{plan.audio.start_ms / 1000:.3f}",
                "-i",
                plan.audio.path,
            ]

        vf = (
            f"scale={plan.width}:{plan.height}:force_original_aspect_ratio=increase,"
            f"crop={plan.width}:{plan.height},fps={plan.fps},format=yuv420p"
        )
        cmd += [
            "-t",
            f"{duration_s:.3f}",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-threads",
            "1",
        ]

        if plan.audio:
            cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-an"]

        cmd += [
            "-map_metadata",
            "-1",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RenderError(proc.stderr.strip() or "ffmpeg failed")
        return sha256_file(output_path)
