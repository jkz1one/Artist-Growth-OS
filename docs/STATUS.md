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

## Evidence

- Backend test suite: 12 passed
- Python compileall: passed
- Alembic initial + transactional migrations: upgrade → downgrade → upgrade succeeded using a SQLite compatibility database
- Post-migration inspection confirms Candidate.render_id is nullable, DistinctnessDecision.rule_version exists, and both publication uniqueness constraints are present
- Ruff is declared as a dev dependency but was not installed in the execution environment, so lint has not yet been executed here
- Frontend source scaffold exists, but dependency installation/build remains unverified in this execution environment

## Current safety invariant

A publication in an ambiguous remote-delivery state is never blindly retried. If the process restarts while a Publication is UPLOADING or PROCESSING, the coordinator raises a recovery-required state instead of risking a duplicate post. Real platform adapters will later implement remote reconciliation/status lookup before such a publication can continue.

## Next engineering increment

Expose the durable Phase-1 spine through a narrow application/API command boundary and a DB-backed worker/job record so the same persisted workflow can be invoked outside tests without coupling HTTP requests to FFmpeg or platform calls. Keep the real social adapters out until the platform proof harness is ready.
