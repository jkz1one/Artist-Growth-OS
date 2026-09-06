from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.enums import JobStatus
from app.services.jobs import BackgroundJobStore


class JobHandler(Protocol):
    def handle(self, payload: dict[str, Any]) -> dict[str, Any] | None: ...


class RetryableJobError(RuntimeError):
    def __init__(self, message: str, *, delay_seconds: int = 30) -> None:
        super().__init__(message)
        self.delay_seconds = delay_seconds


class FatalJobError(RuntimeError):
    pass


class QuarantineJobError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerResult:
    job_id: UUID
    status: JobStatus


class DurableWorker:
    def __init__(
        self,
        *,
        store: BackgroundJobStore,
        worker_id: str,
        handlers: dict[str, JobHandler],
        lease_seconds: int = 600,
    ) -> None:
        self.store = store
        self.worker_id = worker_id
        self.handlers = handlers
        self.lease_seconds = lease_seconds

    def run_once(self, *, now: datetime | None = None) -> WorkerResult | None:
        lease = self.store.claim_next(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            job_types=self.handlers.keys(),
            now=now,
        )
        if lease is None:
            return None
        handler = self.handlers.get(lease.job_type)
        if handler is None:
            status = self.store.fail(
                job_id=lease.job_id,
                lease_token=lease.lease_token,
                error=f"no handler registered for {lease.job_type}",
                now=now,
            )
            return WorkerResult(lease.job_id, status)

        try:
            result = handler.handle(lease.payload)
        except QuarantineJobError as exc:
            status = self.store.quarantine(
                job_id=lease.job_id,
                lease_token=lease.lease_token,
                error=str(exc),
                now=now,
            )
        except FatalJobError as exc:
            status = self.store.fail(
                job_id=lease.job_id,
                lease_token=lease.lease_token,
                error=str(exc),
                now=now,
            )
        except RetryableJobError as exc:
            status = self.store.retry(
                job_id=lease.job_id,
                lease_token=lease.lease_token,
                error=str(exc),
                delay_seconds=exc.delay_seconds,
                now=now,
            )
        except Exception as exc:  # bounded fail-safe for unexpected transient faults
            delay = min(30 * (2 ** max(lease.attempt_count - 1, 0)), 300)
            status = self.store.retry(
                job_id=lease.job_id,
                lease_token=lease.lease_token,
                error=f"{type(exc).__name__}: {exc}",
                delay_seconds=delay,
                now=now,
            )
        else:
            status = self.store.complete(
                job_id=lease.job_id,
                lease_token=lease.lease_token,
                result=result,
                now=now,
            )
        return WorkerResult(lease.job_id, status)
