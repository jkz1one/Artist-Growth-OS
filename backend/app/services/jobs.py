from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.enums import JobStatus
from app.models.jobs import BackgroundJob


class JobError(RuntimeError):
    pass


class JobNotFound(JobError):
    pass


class IdempotencyConflict(JobError):
    pass


class LeaseLost(JobError):
    pass


@dataclass(frozen=True)
class EnqueueResult:
    job: BackgroundJob
    reused: bool


@dataclass(frozen=True)
class JobLease:
    job_id: UUID
    job_type: str
    payload: dict[str, Any]
    attempt_count: int
    max_attempts: int
    lease_token: str


def utcnow() -> datetime:
    return datetime.now(UTC)


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class BackgroundJobStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def enqueue(
        self,
        *,
        job_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        max_attempts: int = 3,
        now: datetime | None = None,
    ) -> EnqueueResult:
        if not job_type.strip():
            raise ValueError("job_type is required")
        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

        now = now or utcnow()
        payload_hash = canonical_payload_hash(payload)
        with self.session_factory() as session:
            existing = self._find_by_key(session, job_type, idempotency_key)
            if existing is not None:
                return self._existing_result(session, existing, payload_hash)

            job = BackgroundJob(
                job_type=job_type,
                payload=payload,
                payload_hash=payload_hash,
                status=JobStatus.PENDING,
                attempt_count=0,
                max_attempts=max_attempts,
                next_attempt_at=now,
                idempotency_key=idempotency_key,
            )
            session.add(job)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = self._find_by_key(session, job_type, idempotency_key)
                if existing is None:
                    raise
                return self._existing_result(session, existing, payload_hash)
            session.refresh(job)
            session.expunge(job)
            return EnqueueResult(job=job, reused=False)

    def get(self, job_id: UUID) -> BackgroundJob:
        with self.session_factory() as session:
            job = session.get(BackgroundJob, job_id)
            if job is None:
                raise JobNotFound(str(job_id))
            session.expunge(job)
            return job

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 600,
        job_types: Iterable[str] | None = None,
        now: datetime | None = None,
    ) -> JobLease | None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        now = now or utcnow()
        allowed = tuple(job_types) if job_types is not None else None
        if allowed == ():
            return None

        with self.session_factory() as session:
            # A worker that repeatedly dies while holding a lease must not create an
            # unbounded crash/reclaim loop. Exhausted expired leases become terminal.
            sweep = update(BackgroundJob).where(
                BackgroundJob.status == JobStatus.RUNNING,
                BackgroundJob.lease_expires_at.is_not(None),
                BackgroundJob.lease_expires_at <= now,
                BackgroundJob.attempt_count >= BackgroundJob.max_attempts,
            )
            if allowed is not None:
                sweep = sweep.where(BackgroundJob.job_type.in_(allowed))
            session.execute(
                sweep.values(
                    status=JobStatus.FAILED,
                    last_error="lease expired after maximum attempts",
                    completed_at=now,
                    lease_expires_at=None,
                    leased_by=None,
                    lease_token=None,
                    updated_at=now,
                )
            )
            session.commit()

            eligible = or_(
                and_(
                    BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RETRYABLE]),
                    BackgroundJob.next_attempt_at <= now,
                ),
                and_(
                    BackgroundJob.status == JobStatus.RUNNING,
                    BackgroundJob.lease_expires_at.is_not(None),
                    BackgroundJob.lease_expires_at <= now,
                ),
            )
            stmt = select(BackgroundJob).where(eligible)
            if allowed is not None:
                stmt = stmt.where(BackgroundJob.job_type.in_(allowed))
            stmt = stmt.order_by(BackgroundJob.next_attempt_at, BackgroundJob.created_at).limit(1)
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                stmt = stmt.with_for_update(skip_locked=True)

            job = session.scalar(stmt)
            if job is None:
                return None

            token = uuid4().hex
            job.status = JobStatus.RUNNING
            job.attempt_count += 1
            job.leased_by = worker_id
            job.lease_token = token
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.updated_at = now
            session.commit()
            return JobLease(
                job_id=job.id,
                job_type=job.job_type,
                payload=dict(job.payload),
                attempt_count=job.attempt_count,
                max_attempts=job.max_attempts,
                lease_token=token,
            )

    def renew_lease(
        self,
        *,
        job_id: UUID,
        lease_token: str,
        lease_seconds: int = 600,
        now: datetime | None = None,
    ) -> None:
        now = now or utcnow()
        with self.session_factory() as session:
            job = self._owned_running_job(session, job_id, lease_token, now)
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.updated_at = now
            session.commit()

    def complete(
        self,
        *,
        job_id: UUID,
        lease_token: str,
        result: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> JobStatus:
        now = now or utcnow()
        with self.session_factory() as session:
            job = self._owned_running_job(session, job_id, lease_token, now)
            job.status = JobStatus.SUCCEEDED
            job.result_json = result or {}
            job.last_error = None
            job.completed_at = now
            self._clear_lease(job)
            job.updated_at = now
            session.commit()
            return job.status

    def retry(
        self,
        *,
        job_id: UUID,
        lease_token: str,
        error: str,
        delay_seconds: int,
        now: datetime | None = None,
    ) -> JobStatus:
        now = now or utcnow()
        with self.session_factory() as session:
            job = self._owned_running_job(session, job_id, lease_token, now)
            job.last_error = error[:4000]
            if job.attempt_count >= job.max_attempts:
                job.status = JobStatus.FAILED
                job.completed_at = now
            else:
                job.status = JobStatus.RETRYABLE
                job.next_attempt_at = now + timedelta(seconds=max(delay_seconds, 0))
            self._clear_lease(job)
            job.updated_at = now
            session.commit()
            return job.status

    def fail(
        self,
        *,
        job_id: UUID,
        lease_token: str,
        error: str,
        now: datetime | None = None,
    ) -> JobStatus:
        return self._terminal_failure(
            job_id=job_id,
            lease_token=lease_token,
            error=error,
            status=JobStatus.FAILED,
            now=now,
        )

    def quarantine(
        self,
        *,
        job_id: UUID,
        lease_token: str,
        error: str,
        now: datetime | None = None,
    ) -> JobStatus:
        return self._terminal_failure(
            job_id=job_id,
            lease_token=lease_token,
            error=error,
            status=JobStatus.QUARANTINED,
            now=now,
        )

    def _terminal_failure(
        self,
        *,
        job_id: UUID,
        lease_token: str,
        error: str,
        status: JobStatus,
        now: datetime | None,
    ) -> JobStatus:
        now = now or utcnow()
        with self.session_factory() as session:
            job = self._owned_running_job(session, job_id, lease_token, now)
            job.status = status
            job.last_error = error[:4000]
            job.completed_at = now
            self._clear_lease(job)
            job.updated_at = now
            session.commit()
            return job.status

    @staticmethod
    def _find_by_key(session: Session, job_type: str, idempotency_key: str) -> BackgroundJob | None:
        return session.scalar(
            select(BackgroundJob).where(
                BackgroundJob.job_type == job_type,
                BackgroundJob.idempotency_key == idempotency_key,
            )
        )

    @staticmethod
    def _existing_result(
        session: Session, existing: BackgroundJob, payload_hash: str
    ) -> EnqueueResult:
        if existing.payload_hash != payload_hash:
            raise IdempotencyConflict(
                "idempotency key already belongs to a different command payload"
            )
        session.expunge(existing)
        return EnqueueResult(job=existing, reused=True)

    @staticmethod
    def _owned_running_job(
        session: Session, job_id: UUID, lease_token: str, now: datetime
    ) -> BackgroundJob:
        job = session.scalar(
            select(BackgroundJob).where(
                BackgroundJob.id == job_id,
                BackgroundJob.status == JobStatus.RUNNING,
                BackgroundJob.lease_token == lease_token,
                BackgroundJob.lease_expires_at.is_not(None),
                BackgroundJob.lease_expires_at > now,
            )
        )
        if job is not None:
            return job
        if session.get(BackgroundJob, job_id) is None:
            raise JobNotFound(str(job_id))
        raise LeaseLost(f"worker no longer owns an active lease for job {job_id}")

    @staticmethod
    def _clear_lease(job: BackgroundJob) -> None:
        job.leased_by = None
        job.lease_token = None
        job.lease_expires_at = None
