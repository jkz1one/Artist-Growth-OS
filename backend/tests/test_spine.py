from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.domain.enums import DecisionStatus, RightsCategory
from app.platforms.fake import FakePublisher
from app.schemas.rendering import AudioSlice, DeterministicRenderPlan, SourceClip
from app.services.rights import GrantEvidence
from app.services.spine import PublicationSpine, SpineInput


def make_fixture_media(tmp_path: Path) -> tuple[Path, Path]:
    video = tmp_path / "source.mp4"
    audio = tmp_path / "track.wav"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=30",
            "-t", "1.2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "1.2", str(audio),
        ],
        check=True,
    )
    return video, audio


def grants() -> tuple[GrantEvidence, ...]:
    def g(subject_type: str, subject_id: str, category: RightsCategory) -> GrantEvidence:
        return GrantEvidence(subject_type, subject_id, category, DecisionStatus.CLEAR)

    return (
        g("TRACK", "track-1", RightsCategory.MASTER),
        g("TRACK", "track-1", RightsCategory.COMPOSITION),
        g("TRACK", "track-1", RightsCategory.AUDIOVISUAL_USE),
        g("ASSET", "asset-1", RightsCategory.PROMOTIONAL_USE),
        g("ASSET", "asset-1", RightsCategory.DERIVATIVE_EDIT),
    )


def build_input(tmp_path: Path, video: Path, audio: Path, output_name: str = "render.mp4") -> SpineInput:
    plan = DeterministicRenderPlan(
        width=360,
        height=640,
        duration_ms=1000,
        video=SourceClip(path=str(video), start_ms=0, end_ms=1100),
        audio=AudioSlice(path=str(audio), start_ms=0, end_ms=1100),
    )
    return SpineInput(
        candidate_id="candidate-1",
        track_id="track-1",
        asset_ids=("asset-1",),
        target_platform="FAKE",
        render_plan=plan,
        output_path=tmp_path / output_name,
        policy_classification={"classified": True},
        caption="test",
    )


def test_closed_loop_renders_qcs_and_publishes_idempotently(tmp_path: Path) -> None:
    video, audio = make_fixture_media(tmp_path)
    publisher = FakePublisher()
    spine = PublicationSpine(publisher=publisher)

    first = spine.execute(build_input(tmp_path, video, audio), grants())
    second = spine.execute(build_input(tmp_path, video, audio), grants())

    assert first.qc_status == DecisionStatus.CLEAR
    assert first.rights.status == DecisionStatus.CLEAR
    assert first.policy.status == DecisionStatus.CLEAR
    assert first.distinctness.status == DecisionStatus.CLEAR
    assert first.render_sha256 == second.render_sha256
    assert first.publication.platform_post_id == second.publication.platform_post_id
    assert first.idempotency_key == second.idempotency_key
    assert (tmp_path / "render.mp4").exists()


def test_unknown_rights_prevents_render_and_publish(tmp_path: Path) -> None:
    video, audio = make_fixture_media(tmp_path)
    publisher = FakePublisher()
    spine = PublicationSpine(publisher=publisher)
    incomplete = grants()[:-1]

    with pytest.raises(PermissionError, match="failed closed"):
        spine.execute(build_input(tmp_path, video, audio, "blocked.mp4"), incomplete)

    assert not (tmp_path / "blocked.mp4").exists()


def test_missing_policy_classification_fails_closed_before_render(tmp_path: Path) -> None:
    video, audio = make_fixture_media(tmp_path)
    spine = PublicationSpine(publisher=FakePublisher())
    data = build_input(tmp_path, video, audio, "policy-blocked.mp4")
    data = SpineInput(
        candidate_id=data.candidate_id,
        track_id=data.track_id,
        asset_ids=data.asset_ids,
        target_platform=data.target_platform,
        render_plan=data.render_plan,
        output_path=data.output_path,
        policy_classification={},
    )
    with pytest.raises(PermissionError, match="policy gate failed closed"):
        spine.execute(data, grants())
    assert not data.output_path.exists()


def test_exact_render_plan_duplicate_is_blocked(tmp_path: Path) -> None:
    video, audio = make_fixture_media(tmp_path)
    spine = PublicationSpine(publisher=FakePublisher())
    data = build_input(tmp_path, video, audio, "duplicate-blocked.mp4")
    data = SpineInput(
        candidate_id=data.candidate_id,
        track_id=data.track_id,
        asset_ids=data.asset_ids,
        target_platform=data.target_platform,
        render_plan=data.render_plan,
        output_path=data.output_path,
        policy_classification=data.policy_classification,
        recent_render_plan_hashes=(data.render_plan.stable_hash(),),
    )
    with pytest.raises(PermissionError, match="distinctness gate failed closed"):
        spine.execute(data, grants())
    assert not data.output_path.exists()
