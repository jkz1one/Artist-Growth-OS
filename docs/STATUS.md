# Implementation status

## Completed in first coding increment

- Standalone modular-monolith scaffold
- FastAPI application shell and health route
- SQLAlchemy Phase-1 persistence model
- Alembic initial migration
- Structured deterministic RenderPlan
- FFmpeg H.264/AAC renderer
- ffprobe technical QC
- Fail-closed rights engine with CLEAR / RESTRICTED / UNKNOWN / EXPIRED semantics
- Minimal fail-closed policy-classification gate
- Exact-plan distinctness guard
- Publisher protocol
- Idempotent FakePublisher
- End-to-end fake publication spine tests
- Next.js control-plane shell with no invented performance data
- PostgreSQL local Docker service

## Completed in transactional persistence increment

- Candidate can exist before render so rejected candidates retain lineage and gate decisions
- Immutable/versioned RightsDecision, PolicyDecision, and DistinctnessDecision rows
- Render uniqueness by RenderPlan + artifact SHA
- Durable Publication reservation with candidate/platform and platform/idempotency uniqueness
- Durable PublicationAttempt rows
- Restart-safe published-result reuse without a second publisher call
- Fail-closed handling for ambiguous UPLOADING / PROCESSING states
- Rights evidence loaded from persisted RightsGrant rows
- Source-lineage verification prevents cross-artist concept/audio/track/asset mixing before candidate creation
- Persisted rejected-rights decision before FFmpeg is allowed to run

## Completed in durable job/control-boundary increment

- BackgroundJob persistence with payload hash, attempt budget, next-attempt time, lease owner/token/expiry, result, and terminal error state
- Idempotent enqueue keyed by job type + command idempotency key
- Publication job idempotency is derived from candidate + target platform; callers cannot bypass dedupe with a different request key
- Payload mismatch for the same candidate/platform command fails with HTTP 409
- PostgreSQL claim path uses `FOR UPDATE SKIP LOCKED`; SQLite remains a compatibility-test path
- Expired worker leases are reclaimable while attempt budget remains
- Expired/stale lease tokens cannot commit, retry, fail, quarantine, or renew a job
- Crash/reclaim loops are bounded by max attempts
- Generic durable worker supports success, retryable failure, terminal failure, and quarantine
- Publication job handler resolves the persisted RenderPlan and owns the output path
- FastAPI `POST /v1/jobs/publication` enqueues work without running FFmpeg/platform calls in the request
- FastAPI `GET /v1/jobs/{job_id}` exposes durable job state for the future dashboard
- Ambiguous publication recovery is converted to QUARANTINED job state instead of an automatic repost

## Evidence

- Backend test suite: 20 passed
- Python compileall: passed
- Alembic full chain: upgrade → downgrade base → upgrade succeeded using a SQLite compatibility database
- Post-migration inspection confirms `background_jobs`, claim index, and `(job_type, idempotency_key)` uniqueness
- Focused tests cover enqueue idempotency, command conflict, lease expiry/reclaim, stale-worker rejection, bounded retry, bounded crash recovery, quarantine, status inspection, rejection of caller-controlled output paths, worker-owned render paths, and publication-recovery quarantine
- Ruff is declared as a dev dependency but is not installed in the execution environment, so lint has not yet been executed here
- Frontend source scaffold exists, but dependency installation/build remains unverified in this execution environment

## Current safety invariant

A publication in an ambiguous remote-delivery state is never blindly retried. If the process restarts while a Publication is UPLOADING or PROCESSING, the publication spine requires reconciliation; the durable job layer converts that state into QUARANTINED rather than creating an automatic repost loop.

## Next engineering increment

Add the platform-proof harness without yet committing to a production adapter: capability/proof records, adapter contract tests, and a controlled one-post proof CLI/path that can publish, poll status, and retrieve the metrics actually exposed by a current official API. Verify official documentation immediately before coding each real platform path.
