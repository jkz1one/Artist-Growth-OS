# Implementation status

## Completed foundation increments

- Standalone modular-monolith scaffold, deterministic FFmpeg renderer/QC, fail-closed rights/policy/distinctness gates, Publisher protocol, FakePublisher, and Next.js control-plane shell.
- Transactional publication spine with persisted gate decisions, render/publication uniqueness, durable PublicationAttempt rows, source-lineage verification, restart-safe published-result reuse, and fail-closed ambiguous delivery recovery.
- DB-backed BackgroundJob execution with payload hashes, attempt budgets, scheduling, lease owner/token/expiry, PostgreSQL `FOR UPDATE SKIP LOCKED`, stale-worker rejection, bounded crash/retry loops, worker-owned render paths, API enqueue/status endpoints, and quarantine of ambiguous publication recovery.

## Platform-proof harness increment

- `PlatformAccount` records platform/account/API-family identity without coupling it to Artist.
- `PlatformCapabilitySnapshot` stores account-specific capability evidence using `SUPPORTED` / `UNSUPPORTED` / `UNKNOWN` / `REQUIRES_PROOF`.
- `PlatformProofRun` models one controlled proof with stable account-scoped idempotency.
- Append-only `PlatformProofEvent` rows make the proof sequence inspectable.
- Provider-neutral `PlatformProofAdapter` exposes only capability inspection, controlled publish, status reconciliation, and raw metric retrieval.
- Fake proof adapter exercises the full contract without pretending to prove a real platform.
- Capability capture cannot reset a run after the remote publish boundary.
- Failure after remote acceptance but before receipt persistence becomes `RECOVERY_REQUIRED`.
- Metric collection failure leaves the durable post published and retryable without reposting.
- Credential-bearing proof evidence fails closed before persistence.
- Current platform research is recorded in `docs/PLATFORM_PROOF.md`; native audio/catalog behavior remains empirical rather than assumed.

## Evidence

- Proof-harness compatibility workspace: 20 tests passed (8 original Phase-1 tests + 12 focused proof-harness tests).
- Python compileall: passed.
- Alembic full chain through `e5b7c2d3410a`: upgrade → downgrade base → upgrade passed on the SQLite compatibility database.
- Schema inspection confirmed proof-run uniqueness `(platform_account_id, proof_key)` and proof-event uniqueness `(proof_run_id, sequence)`.
- PR #2's merged durable-job increment independently had 20 backend tests passing before merge.
- Ruff remains declared but unavailable in the execution environment, so lint is not claimed as executed.
- Frontend dependency installation/build remains unverified in this execution environment.

## Current safety invariant

No real social adapter is production-ready merely because official documentation describes an endpoint. A real path must pass an account-level proof: capability capture → one controlled publish → durable platform ID/status reconciliation → raw metrics retrieval. Any ambiguous remote-delivery state fails closed rather than reposting.

## Next engineering increment

Implement the first real **proof-only** adapter for Instagram professional accounts using the currently documented Reels container → status → `media_publish` flow and media insights. Keep credentials outside proof/audit payloads, keep native music/Trial Reels/disclosure capabilities `UNKNOWN` or `REQUIRES_PROOF`, and do not promote the adapter to autonomous publishing until a real owned account passes the proof contract end to end.
