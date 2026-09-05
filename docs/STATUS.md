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

## Evidence

- Backend test suite: 8 passed
- Alembic: initial migration generated successfully
- Alembic smoke test: upgrade → downgrade → upgrade succeeded using SQLite compatibility test DB
- Python compileall: passed
- Frontend source scaffold created, but package installation/build was not completed in this execution environment because dependency installation exceeded the available command window. Do not treat frontend build as verified yet.

## Next engineering increment

Persist the service-level loop transactionally: create a Candidate and immutable decision rows, store Render metadata, create Publication/PublicationAttempt under a database uniqueness constraint, and prove idempotency across process restart rather than only inside FakePublisher memory.
