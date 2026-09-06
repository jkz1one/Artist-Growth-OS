from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.models.spine import Artist, Asset, AudioUsePlan, CreativeConcept, RenderPlan, Track
from app.schemas.rendering import DeterministicRenderPlan


def verify_source_lineage(
    *,
    session_factory: sessionmaker[Session],
    artist_id: UUID,
    concept_id: UUID,
    audio_use_plan_id: UUID,
    render_plan_id: UUID,
    track_id: UUID | None,
    asset_ids: tuple[UUID, ...],
    render_plan: DeterministicRenderPlan,
) -> None:
    """Reject cross-artist or mismatched source lineage before Candidate creation."""
    with session_factory() as session:
        artist = session.get(Artist, artist_id)
        if artist is None or not artist.active:
            raise ValueError("artist is missing or inactive")

        concept = session.get(CreativeConcept, concept_id)
        if concept is None or concept.artist_id != artist_id:
            raise ValueError("concept does not belong to candidate artist")

        audio_plan = session.get(AudioUsePlan, audio_use_plan_id)
        if audio_plan is None or audio_plan.artist_id != artist_id:
            raise ValueError("audio use plan does not belong to candidate artist")
        if audio_plan.track_id != track_id:
            raise ValueError("audio use plan track does not match candidate track")

        persisted_plan = session.get(RenderPlan, render_plan_id)
        if persisted_plan is None:
            raise ValueError("persisted render plan is missing")
        if persisted_plan.concept_id != concept_id:
            raise ValueError("render plan concept does not match candidate concept")
        if persisted_plan.audio_use_plan_id != audio_use_plan_id:
            raise ValueError("render plan audio use does not match candidate audio use plan")
        if persisted_plan.deterministic_hash != render_plan.stable_hash():
            raise ValueError("render plan payload does not match persisted deterministic hash")

        if track_id is not None:
            track = session.get(Track, track_id)
            if track is None or track.artist_id != artist_id:
                raise ValueError("track does not belong to candidate artist")

        for asset_id in asset_ids:
            asset = session.get(Asset, asset_id)
            if asset is None or asset.artist_id != artist_id:
                raise ValueError("asset does not belong to candidate artist")
