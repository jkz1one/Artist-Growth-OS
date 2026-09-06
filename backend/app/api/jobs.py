from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_job_store
from app.schemas.jobs import JobReceipt, JobStatusResponse, PublicationJobCommand
from app.services.jobs import BackgroundJobStore, IdempotencyConflict, JobNotFound

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])
PUBLICATION_JOB_TYPE = "PUBLICATION_SPINE"


@router.post(
    "/publication",
    response_model=JobReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_publication(
    command: PublicationJobCommand,
    store: Annotated[BackgroundJobStore, Depends(get_job_store)],
) -> JobReceipt:
    # Candidate identity is the publication-command idempotency boundary. Callers cannot
    # bypass dedupe by choosing a different request key for the same candidate/platform.
    idempotency_key = f"publication:{command.candidate_id}:{command.target_platform}"
    try:
        result = store.enqueue(
            job_type=PUBLICATION_JOB_TYPE,
            payload=command.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            max_attempts=3,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    job = result.job
    return JobReceipt(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        reused=result.reused,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        next_attempt_at=job.next_attempt_at,
    )


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    job_id: UUID,
    store: Annotated[BackgroundJobStore, Depends(get_job_store)],
) -> JobStatusResponse:
    try:
        job = store.get(job_id)
    except JobNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found") from exc

    return JobStatusResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        next_attempt_at=job.next_attempt_at,
        lease_expires_at=job.lease_expires_at,
        last_error=job.last_error,
        result=job.result_json,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )
