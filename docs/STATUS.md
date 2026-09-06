# Implementation status

## Completed foundation increments

- Standalone modular-monolith scaffold, deterministic FFmpeg renderer/QC, fail-closed rights/policy/distinctness gates, Publisher protocol, FakePublisher, and Next.js control-plane shell.
- Transactional publication spine with persisted gate decisions, render/publication uniqueness, durable PublicationAttempt rows, source-lineage verification, restart-safe published-result reuse, and fail-closed ambiguous delivery recovery.
- DB-backed BackgroundJob execution with payload hashes, attempt budgets, scheduling, lease owner/token/expiry, PostgreSQL `FOR UPDATE SKIP LOCKED`, stale-worker rejection, bounded crash/retry loops, worker-owned render paths, API enqueue/status endpoints, and quarantine of ambiguous publication recovery.
- Empirical platform-proof harness with PlatformAccount, capability snapshots, proof runs/events, credential-safe evidence, controlled publish/reconcile/metrics contract, and fake adapter.

## Instagram proof-only adapter increment

- Uses the current Instagram Login / `graph.instagram.com` publishing family rather than hard-coding an old Graph version.
- API version and access token are runtime configuration; access tokens never enter proof evidence or URLs.
- Proof media must be HTTPS and match a controlled media-host allowlist.
- Account/content-publishing-limit/insights probes capture account-specific capability evidence.
- Reels use public `video_url` -> media container -> bounded status polling -> one `media_publish` call.
- Durable `remote_context` checkpoints preserve the container ID before final publish and media ID immediately after successful publish.
- Final `media_publish` transport errors, server errors, unreadable success responses, or post-publish checkpoint failures become ambiguous recovery states rather than retries.
- Reconciliation with a known media ID verifies the media object/permalink; a container-only recovery never guesses an ID or republishes automatically.
- Media insights preserve raw platform data while extracting a conservative metric map.
- Graph/API errors redact the runtime access token before they can reach durable errors/events.
- Native music, owned-sound behavior, Trial Reels, and synthetic-media disclosure remain `UNKNOWN`/`REQUIRES_PROOF`.

## Evidence

- Compatibility workspace backend suite: 32 tests passed (8 original Phase-1 tests + 12 proof-harness tests + 12 Instagram/checkpoint tests).
- Python compileall: passed.
- Alembic full chain through `f6a1d9e240bc`: upgrade -> downgrade base -> upgrade passed on the SQLite compatibility database.
- Post-migration inspection confirms `platform_proof_runs.remote_context` exists and is non-null.
- Docker is not installed in the current execution environment, so the new migration has **not** been claimed as exercised against a live PostgreSQL server here.
- Ruff remains declared but unavailable in the execution environment; obvious line-length issues in the modified adapter/harness/tests were manually removed, but lint is not claimed as executed.
- Frontend dependency installation/build remains unverified in this execution environment.

## Current safety invariant

No real social adapter is production-ready merely because official documentation describes an endpoint. Instagram now has a proof-only implementation, but it remains barred from autonomous publishing until a real owned professional account passes: capability capture -> one controlled public Reel -> durable media ID/status reconciliation -> raw media insights, with no second publication call.

## Operator proof runner increment

- `start` creates/reuses the account/run and captures capabilities but has no publication path.
- `show` is database-only and requires no Instagram credential configuration.
- `publish` is the only live-publication command and requires the exact phrase `I_UNDERSTAND_THIS_WILL_POST_PUBLICLY`.
- `reconcile` and `metrics` resume an existing durable run by UUID without republishing.
- Instagram access-token fields are excluded from runtime-config `repr()` output.
- The operator runbook documents credential handling and the fail-closed recovery sequence.
- Full backend suite after the runner increment: 42 tests passed; Python compileall and the real CLI `--help` path passed. This increment has no schema changes.

## Next engineering increment

The software path for the first Instagram proof is now ready. The remaining blocker is empirical/environmental: configure an owned Instagram professional account and Meta app, migrate a real PostgreSQL database, host one controlled proof video on the approved public media domain, then execute `start` and inspect the captured capabilities before deliberately authorizing the single live `publish`.
