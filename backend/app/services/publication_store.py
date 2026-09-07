from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.enums import CandidateStatus, DecisionStatus, PublicationStatus
from app.models.decision_event import DecisionEvent
from app.models.spine import (
    Candidate,
    DistinctnessDecision,
    PolicyDecision,
    Publication,
    PublicationAttempt,
    Render,
    RightsDecision,
    RightsGrant,
)
from app.services.rights import GrantEvidence


def _status_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


class PublicationStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def find_publication(self, candidate_id: UUID, platform: str) -> Publication | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(Publication).where(
                    Publication.candidate_id == candidate_id,
                    Publication.platform == platform,
                )
            )
            if row is not None:
                session.expunge(row)
            return row

    def list_decision_events(self, candidate_id: UUID) -> tuple[DecisionEvent, ...]:
        with self.session_factory() as session:
            events = session.scalars(
                select(DecisionEvent)
                .where(DecisionEvent.candidate_id == candidate_id)
                .order_by(DecisionEvent.sequence)
            ).all()
            for event in events:
                session.expunge(event)
            return tuple(events)

    def ensure_candidate(
        self,
        *,
        candidate_id: UUID,
        artist_id: UUID,
        concept_id: UUID,
        audio_use_plan_id: UUID,
        target_platform: str,
        lineage: dict[str, Any],
    ) -> Candidate:
        with self.session_factory() as session:
            candidate = session.get(Candidate, candidate_id)
            if candidate is None:
                candidate = Candidate(
                    id=candidate_id,
                    artist_id=artist_id,
                    concept_id=concept_id,
                    render_id=None,
                    audio_use_plan_id=audio_use_plan_id,
                    status=CandidateStatus.PLANNED,
                    target_platform=target_platform,
                    lineage=lineage,
                )
                session.add(candidate)
                session.flush()
            else:
                expected = (
                    candidate.artist_id,
                    candidate.concept_id,
                    candidate.audio_use_plan_id,
                    candidate.target_platform,
                )
                actual = (artist_id, concept_id, audio_use_plan_id, target_platform)
                if expected != actual:
                    raise ValueError("candidate identity does not match persisted lineage")

            self._append_decision_event(
                session,
                candidate_id=candidate.id,
                event_key="candidate:created",
                event_type="CANDIDATE_CREATED",
                status=candidate.status,
                payload={
                    "artist_id": str(candidate.artist_id),
                    "concept_id": str(candidate.concept_id),
                    "audio_use_plan_id": str(candidate.audio_use_plan_id),
                    "target_platform": candidate.target_platform,
                },
            )
            session.commit()
            session.refresh(candidate)
            session.expunge(candidate)
            return candidate

    def load_grants(self, subject_ids: list[UUID]) -> tuple[GrantEvidence, ...]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(RightsGrant).where(RightsGrant.subject_id.in_(subject_ids))
            ).all()
            return tuple(
                GrantEvidence(
                    subject_type=row.subject_type,
                    subject_id=str(row.subject_id),
                    category=row.category,
                    status=row.status,
                    platforms=tuple(row.platforms),
                    starts_on=row.starts_on,
                    expires_on=row.expires_on,
                )
                for row in rows
            )

    def persist_gate_decisions(
        self,
        *,
        candidate_id: UUID,
        rights: Any,
        rights_rule_version: str,
        policy: Any,
        policy_rule_version: str,
        distinctness: Any,
        distinctness_rule_version: str,
    ) -> None:
        with self.session_factory() as session:
            rights_report = {
                "missing": list(rights.missing),
                "restricted": list(rights.restricted),
                "expired": list(rights.expired),
            }
            if session.scalar(
                select(RightsDecision).where(
                    RightsDecision.candidate_id == candidate_id,
                    RightsDecision.rule_version == rights_rule_version,
                )
            ) is None:
                session.add(
                    RightsDecision(
                        candidate_id=candidate_id,
                        status=rights.status,
                        rule_version=rights_rule_version,
                        report=rights_report,
                    )
                )

            policy_report = {"reasons": list(policy.reasons)}
            if session.scalar(
                select(PolicyDecision).where(
                    PolicyDecision.candidate_id == candidate_id,
                    PolicyDecision.rule_version == policy_rule_version,
                )
            ) is None:
                session.add(
                    PolicyDecision(
                        candidate_id=candidate_id,
                        status=policy.status,
                        rule_version=policy_rule_version,
                        report=policy_report,
                    )
                )

            distinctness_report = {"reasons": list(distinctness.reasons)}
            if session.scalar(
                select(DistinctnessDecision).where(
                    DistinctnessDecision.candidate_id == candidate_id,
                    DistinctnessDecision.rule_version == distinctness_rule_version,
                )
            ) is None:
                session.add(
                    DistinctnessDecision(
                        candidate_id=candidate_id,
                        status=distinctness.status,
                        rule_version=distinctness_rule_version,
                        novelty_score=distinctness.novelty_score,
                        semantic_similarity=0.0,
                        visual_similarity=0.0,
                        audio_overlap=0.0,
                        report=distinctness_report,
                    )
                )

            candidate = session.get(Candidate, candidate_id)
            if candidate is None:
                raise RuntimeError("candidate disappeared during gate persistence")
            if any(
                status != DecisionStatus.CLEAR
                for status in (rights.status, policy.status, distinctness.status)
            ):
                candidate.status = CandidateStatus.REJECTED

            self._append_decision_event(
                session,
                candidate_id=candidate_id,
                event_key=f"rights:{rights_rule_version}",
                event_type="RIGHTS_EVALUATED",
                status=rights.status,
                rule_version=rights_rule_version,
                payload=rights_report,
            )
            self._append_decision_event(
                session,
                candidate_id=candidate_id,
                event_key=f"policy:{policy_rule_version}",
                event_type="POLICY_EVALUATED",
                status=policy.status,
                rule_version=policy_rule_version,
                payload=policy_report,
            )
            self._append_decision_event(
                session,
                candidate_id=candidate_id,
                event_key=f"distinctness:{distinctness_rule_version}",
                event_type="DISTINCTNESS_EVALUATED",
                status=distinctness.status,
                rule_version=distinctness_rule_version,
                payload={
                    **distinctness_report,
                    "novelty_score": distinctness.novelty_score,
                },
            )
            session.commit()

    def persist_render(
        self,
        *,
        candidate_id: UUID,
        render_plan_id: UUID,
        artifact_uri: str,
        sha256: str,
        qc_status: DecisionStatus,
        qc_report: dict[str, Any],
    ) -> Render:
        with self.session_factory() as session:
            render = session.scalar(
                select(Render).where(
                    Render.render_plan_id == render_plan_id,
                    Render.sha256 == sha256,
                )
            )
            if render is None:
                render = Render(
                    render_plan_id=render_plan_id,
                    artifact_uri=artifact_uri,
                    sha256=sha256,
                    qc_status=qc_status,
                    qc_report=qc_report,
                )
                session.add(render)
                session.flush()

            candidate = session.get(Candidate, candidate_id)
            if candidate is None:
                raise RuntimeError("candidate disappeared during render persistence")
            candidate.render_id = render.id
            candidate.status = (
                CandidateStatus.ELIGIBLE
                if qc_status == DecisionStatus.CLEAR
                else CandidateStatus.QUARANTINED
            )
            self._append_decision_event(
                session,
                candidate_id=candidate_id,
                event_key=f"render:{render.id}:qc",
                event_type="RENDER_QC_EVALUATED",
                status=qc_status,
                payload={
                    "render_id": str(render.id),
                    "render_plan_id": str(render_plan_id),
                    "sha256": render.sha256,
                    "candidate_status": candidate.status.value,
                },
            )
            session.commit()
            session.refresh(render)
            session.expunge(render)
            return render

    def load_render(self, render_id: UUID) -> Render | None:
        with self.session_factory() as session:
            render = session.get(Render, render_id)
            if render is not None:
                session.expunge(render)
            return render

    def reserve_publication(
        self,
        *,
        candidate_id: UUID,
        platform: str,
        idempotency_key: str,
    ) -> Publication:
        with self.session_factory() as session:
            publication = session.scalar(
                select(Publication).where(
                    Publication.candidate_id == candidate_id,
                    Publication.platform == platform,
                )
            )
            if publication is None:
                publication = Publication(
                    candidate_id=candidate_id,
                    platform=platform,
                    idempotency_key=idempotency_key,
                    status=PublicationStatus.SCHEDULED,
                )
                session.add(publication)
                session.flush()
            elif publication.idempotency_key != idempotency_key:
                raise ValueError(
                    "candidate/platform publication already exists with a different idempotency key"
                )

            self._append_decision_event(
                session,
                candidate_id=candidate_id,
                event_key=f"publication:{publication.id}:reserved",
                event_type="PUBLICATION_RESERVED",
                status=publication.status,
                payload={
                    "publication_id": str(publication.id),
                    "platform": publication.platform,
                    "idempotency_key": publication.idempotency_key,
                },
            )
            session.commit()
            session.refresh(publication)
            session.expunge(publication)
            return publication

    def start_attempt(self, publication_id: UUID, request_fingerprint: str) -> PublicationAttempt:
        with self.session_factory() as session:
            publication = session.get(Publication, publication_id)
            if publication is None:
                raise RuntimeError("publication reservation disappeared")
            next_number = session.scalar(
                select(func.coalesce(func.max(PublicationAttempt.attempt_number), 0)).where(
                    PublicationAttempt.publication_id == publication_id
                )
            )
            attempt = PublicationAttempt(
                publication_id=publication_id,
                attempt_number=int(next_number or 0) + 1,
                request_fingerprint=request_fingerprint,
                status=PublicationStatus.UPLOADING,
            )
            publication.status = PublicationStatus.UPLOADING
            session.add(attempt)
            session.flush()
            self._append_decision_event(
                session,
                candidate_id=publication.candidate_id,
                event_key=f"publication-attempt:{attempt.id}:started",
                event_type="PUBLISH_ATTEMPT_STARTED",
                status=PublicationStatus.UPLOADING,
                payload={
                    "publication_id": str(publication.id),
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                    "request_fingerprint": attempt.request_fingerprint,
                },
            )
            session.commit()
            session.refresh(attempt)
            session.expunge(attempt)
            return attempt

    def quarantine_attempt(self, publication_id: UUID, attempt_id: UUID, error: str) -> None:
        with self.session_factory() as session:
            publication = session.get(Publication, publication_id)
            attempt = session.get(PublicationAttempt, attempt_id)
            if publication is not None:
                publication.status = PublicationStatus.QUARANTINED
            if attempt is not None:
                attempt.status = PublicationStatus.QUARANTINED
                attempt.error = error
            if publication is not None and attempt is not None:
                self._append_decision_event(
                    session,
                    candidate_id=publication.candidate_id,
                    event_key=f"publication-attempt:{attempt.id}:quarantined",
                    event_type="PUBLISH_ATTEMPT_QUARANTINED",
                    status=PublicationStatus.QUARANTINED,
                    payload={
                        "publication_id": str(publication.id),
                        "attempt_id": str(attempt.id),
                        "attempt_number": attempt.attempt_number,
                    },
                )
            session.commit()

    def complete_attempt(
        self,
        *,
        publication_id: UUID,
        attempt_id: UUID,
        platform_post_id: str,
        status: PublicationStatus,
        published_at: Any,
        canonical_url: str,
    ) -> Publication:
        with self.session_factory() as session:
            publication = session.get(Publication, publication_id)
            attempt = session.get(PublicationAttempt, attempt_id)
            if publication is None or attempt is None:
                raise RuntimeError("publication reservation disappeared")
            publication.platform_post_id = platform_post_id
            publication.status = status
            publication.published_at = published_at
            publication.canonical_url = canonical_url
            attempt.status = status
            self._append_decision_event(
                session,
                candidate_id=publication.candidate_id,
                event_key=f"publication-attempt:{attempt.id}:completed",
                event_type="PUBLISH_ATTEMPT_COMPLETED",
                status=status,
                payload={
                    "publication_id": str(publication.id),
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                    "platform_post_id": platform_post_id,
                    "canonical_url": canonical_url,
                },
            )
            session.commit()
            session.refresh(publication)
            session.expunge(publication)
            return publication

    @staticmethod
    def _append_decision_event(
        session: Session,
        *,
        candidate_id: UUID,
        event_key: str,
        event_type: str,
        status: Any = None,
        rule_version: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> DecisionEvent:
        candidate_exists = session.scalar(
            select(Candidate.id)
            .where(Candidate.id == candidate_id)
            .with_for_update()
        )
        if candidate_exists is None:
            raise RuntimeError("candidate disappeared during decision event persistence")

        existing = session.scalar(
            select(DecisionEvent).where(
                DecisionEvent.candidate_id == candidate_id,
                DecisionEvent.event_key == event_key,
            )
        )
        if existing is not None:
            return existing

        next_sequence = session.scalar(
            select(func.coalesce(func.max(DecisionEvent.sequence), 0)).where(
                DecisionEvent.candidate_id == candidate_id
            )
        )
        event = DecisionEvent(
            candidate_id=candidate_id,
            sequence=int(next_sequence or 0) + 1,
            event_key=event_key,
            event_type=event_type,
            status=_status_value(status),
            rule_version=rule_version,
            payload=payload or {},
        )
        session.add(event)
        session.flush()
        return event
