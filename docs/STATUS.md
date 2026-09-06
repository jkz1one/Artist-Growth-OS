# Implementation status

## Completed foundation increments

- Standalone modular-monolith scaffold, deterministic FFmpeg renderer/QC, fail-closed rights/policy/distinctness gates, Publisher protocol, FakePublisher, and Next.js control-plane shell.
- Transactional publication spine with persisted gate decisions, render/publication uniqueness, durable PublicationAttempt rows, source-lineage verification, restart-safe published-result reuse, and fail-closed ambiguous delivery recovery.
- DB-backed BackgroundJob execution with payload hashes, attempt budgets, scheduling, lease owner/token/expiry, PostgreSQL `FOR UPDATE SKIP LOCKED`, stale-worker rejection, bounded crash/retry loops, worker-owned render paths, API enqueue/status endpoints, and quarantine of ambiguous publication recovery.
- Empirical platform-proof harness with PlatformAccount, capability snapshots, proof runs/events, credential-safe evidence, controlled publish/reconcile/metrics contract, and fake adapter.
- Repository backend CI gate with installability, Ruff, compileall, pytest, SQLite migration round-trip, and PostgreSQL 17 migration round-trip.

## Remote validation baseline

PR #6 established the first repository-level backend gate and then passed again on `main` after merge.

- Editable backend package install: passed.
- Ruff: passed.
- Python compileall: passed.
- Full backend suite on the PR baseline: **58 tests passed**.
- Alembic full chain through `f6a1d9e240bc`: SQLite `upgrade -> downgrade base -> upgrade` passed.
- The same Alembic chain: PostgreSQL 17 `upgrade -> downgrade base -> upgrade` passed.
- Final workflow permissions are read-only (`contents: read`).
- Frontend dependency installation/build remains unverified in this execution environment and is not covered by the backend workflow yet.

The GitHub Actions workflow is now the authoritative acceptance gate for backend changes; local compatibility-workspace counts from earlier increments are historical evidence only.

## Instagram proof-only adapter

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

## Instagram operator proof runner

- `start` creates/reuses the account/run and captures capabilities but has no publication path.
- `show` is database-only and requires no Instagram credential configuration.
- `publish` is the only live-publication command and requires the exact phrase `I_UNDERSTAND_THIS_WILL_POST_PUBLICLY`.
- `reconcile` and `metrics` resume an existing durable run by UUID without republishing.
- Instagram access-token fields are excluded from runtime-config `repr()` output.
- The operator runbook documents credential handling and the fail-closed recovery sequence.

## YouTube proof-only adapter

The second real proof adapter exercises a materially different platform shape without adding a production Publisher or making a live call.

- Uses YouTube Data API v3 plus YouTube Analytics API v2 with runtime OAuth access tokens sent only in the Authorization header.
- Verifies the configured channel against the OAuth-authorized `channels.list(mine=true)` result.
- Defaults proof uploads to `private`; public visibility remains `REQUIRES_PROOF` because unverified API projects can be restricted to private uploads.
- Uses the official resumable `videos.insert` flow: create session -> one binary PUT -> durable video-ID checkpoint -> bounded processing polling.
- The resumable session URL is deliberately not persisted in proof evidence or `remote_context`.
- Once binary upload begins, transport failures, 5xx responses, `308 Resume Incomplete`, unreadable success responses, or missing video IDs become supervised recovery states rather than automatic second uploads.
- A known video ID is reconciled with owner-visible `videos.list` processing/status data; without a durable video ID, reconciliation refuses to search-and-reupload heuristics.
- Upload processing failures/rejections map to rejected proof status; in-progress uploads remain recovery/reconciliation work.
- Metrics combine owner-visible Data API statistics with a video-filtered Analytics API report while preserving both raw responses.
- The configured `containsSyntheticMedia` field maps to YouTube's current video status disclosure field, but actual account/app behavior remains `REQUIRES_PROOF` until exercised.
- Native/catalog music attachment is not provided by this Data API adapter; baked audio is the current proof path.
- Shorts classification, Content ID behavior, public visibility, exact analytics latency/fields, and live upload authorization remain empirical.

## Current safety invariant

No real social adapter is production-ready merely because official documentation describes an endpoint or mocked contract tests pass. Instagram and YouTube remain proof-only. Autonomous publication stays barred until an owned account completes capability capture -> one controlled publication -> durable platform ID/status reconciliation -> raw metrics, with no blind second publication call.

## Next engineering increment

Software can continue without pretending the environmental proof is complete, but the promotion gate does not move: the first platform to become a production Publisher must pass a real owned-account proof. Instagram remains the most prepared path because its guarded operator runner already exists. YouTube now provides a second adapter contract for validating that platform-proof abstractions remain platform-independent before dashboard work depends on them.
