from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.domain.enums import JobStatus
from app.models.jobs import BackgroundJob  # noqa: F401
from app.services.jobs import BackgroundJobStore, IdempotencyConflict, LeaseLost
from app.workers.base import DurableWorker, QuarantineJobError, RetryableJobError


@pytest.fixture
def job_store() -> BackgroundJobStore:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return BackgroundJobStore(factory)


def test_enqueue_reuses_only_identical_payload(job_store: BackgroundJobStore) -> None:
    first = job_store.enqueue(
        job_type="TEST",
        payload={"candidate_id": "a", "value": 1},
        idempotency_key="same-command",
    )
    second = job_store.enqueue(
        job_type="TEST",
        payload={"value": 1, "candidate_id": "a"},
        idempotency_key="same-command",
    )

    assert first.reused is False
    assert second.reused is True
    assert first.job.id == second.job.id

    with pytest.raises(IdempotencyConflict):
        job_store.enqueue(
            job_type="TEST",
            payload={"candidate_id": "a", "value": 2},
            idempotency_key="same-command",
        )


def test_expired_lease_can_be_reclaimed_but_stale_worker_cannot_commit(
    job_store: BackgroundJobStore,
) -> None:
    now = datetime(2026, 9, 6, 16, 0, tzinfo=UTC)
    job = job_store.enqueue(
        job_type="TEST",
        payload={"x": 1},
        idempotency_key="lease-reclaim",
        now=now,
    ).job

    first = job_store.claim_next(worker_id="worker-a", lease_seconds=10, now=now)
    assert first is not None
    assert first.job_id == job.id
    assert first.attempt_count == 1
    assert job_store.claim_next(worker_id="worker-b", now=now + timedelta(seconds=5)) is None

    second = job_store.claim_next(
        worker_id="worker-b",
        lease_seconds=10,
        now=now + timedelta(seconds=11),
    )
    assert second is not None
    assert second.job_id == job.id
    assert second.attempt_count == 2
    assert second.lease_token != first.lease_token

    with pytest.raises(LeaseLost):
        job_store.complete(job_id=job.id, lease_token=first.lease_token, result={"bad": True})

    status = job_store.complete(
        job_id=job.id,
        lease_token=second.lease_token,
        result={"ok": True},
        now=now + timedelta(seconds=12),
    )
    assert status == JobStatus.SUCCEEDED
    persisted = job_store.get(job.id)
    assert persisted.result_json == {"ok": True}
    assert persisted.lease_token is None


class AlwaysRetry:
    def handle(self, payload):
        raise RetryableJobError("temporary failure", delay_seconds=10)


class AlwaysQuarantine:
    def handle(self, payload):
        raise QuarantineJobError("remote acceptance is ambiguous")


def test_worker_retry_is_delayed_and_bounded(job_store: BackgroundJobStore) -> None:
    now = datetime(2026, 9, 6, 17, 0, tzinfo=UTC)
    job = job_store.enqueue(
        job_type="TEST",
        payload={"x": 1},
        idempotency_key="bounded-retry",
        max_attempts=2,
        now=now,
    ).job
    worker = DurableWorker(
        store=job_store,
        worker_id="worker-a",
        handlers={"TEST": AlwaysRetry()},
        lease_seconds=30,
    )

    first = worker.run_once(now=now)
    assert first is not None and first.status == JobStatus.RETRYABLE
    assert worker.run_once(now=now + timedelta(seconds=5)) is None

    second = worker.run_once(now=now + timedelta(seconds=11))
    assert second is not None and second.status == JobStatus.FAILED
    persisted = job_store.get(job.id)
    assert persisted.attempt_count == 2
    assert persisted.completed_at is not None
    assert persisted.last_error == "temporary failure"


def test_quarantined_job_is_not_automatically_retried(job_store: BackgroundJobStore) -> None:
    now = datetime(2026, 9, 6, 18, 0, tzinfo=UTC)
    job = job_store.enqueue(
        job_type="TEST",
        payload={"x": 1},
        idempotency_key="quarantine",
        now=now,
    ).job
    worker = DurableWorker(
        store=job_store,
        worker_id="worker-a",
        handlers={"TEST": AlwaysQuarantine()},
    )

    result = worker.run_once(now=now)
    assert result is not None and result.status == JobStatus.QUARANTINED
    assert worker.run_once(now=now + timedelta(days=1)) is None
    persisted = job_store.get(job.id)
    assert persisted.attempt_count == 1
    assert "ambiguous" in (persisted.last_error or "")


def test_expired_lease_cannot_commit_even_before_reclaim(job_store: BackgroundJobStore) -> None:
    now = datetime(2026, 9, 6, 19, 0, tzinfo=UTC)
    job = job_store.enqueue(
        job_type="TEST",
        payload={"x": 1},
        idempotency_key="expired-cannot-commit",
        now=now,
    ).job
    lease = job_store.claim_next(worker_id="worker-a", lease_seconds=5, now=now)
    assert lease is not None

    with pytest.raises(LeaseLost):
        job_store.complete(
            job_id=job.id,
            lease_token=lease.lease_token,
            result={"late": True},
            now=now + timedelta(seconds=6),
        )


def test_crash_reclaims_are_bounded_by_max_attempts(job_store: BackgroundJobStore) -> None:
    now = datetime(2026, 9, 6, 20, 0, tzinfo=UTC)
    job = job_store.enqueue(
        job_type="TEST",
        payload={"x": 1},
        idempotency_key="crash-bounded",
        max_attempts=1,
        now=now,
    ).job
    lease = job_store.claim_next(worker_id="worker-a", lease_seconds=5, now=now)
    assert lease is not None and lease.attempt_count == 1

    assert job_store.claim_next(worker_id="worker-b", now=now + timedelta(seconds=6)) is None
    persisted = job_store.get(job.id)
    assert persisted.status == JobStatus.FAILED
    assert persisted.completed_at is not None
    assert persisted.last_error == "lease expired after maximum attempts"


def test_specialized_worker_does_not_sweep_other_job_types(job_store: BackgroundJobStore) -> None:
    now = datetime(2026, 9, 6, 21, 0, tzinfo=UTC)
    other = job_store.enqueue(
        job_type="OTHER",
        payload={"x": 1},
        idempotency_key="other-expired",
        max_attempts=1,
        now=now,
    ).job
    lease = job_store.claim_next(
        worker_id="other-worker",
        lease_seconds=5,
        job_types=["OTHER"],
        now=now,
    )
    assert lease is not None

    assert job_store.claim_next(
        worker_id="test-worker",
        job_types=["TEST"],
        now=now + timedelta(seconds=6),
    ) is None
    assert job_store.get(other.id).status == JobStatus.RUNNING

    assert job_store.claim_next(
        worker_id="other-worker-2",
        job_types=["OTHER"],
        now=now + timedelta(seconds=6),
    ) is None
    assert job_store.get(other.id).status == JobStatus.FAILED
