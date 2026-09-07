# Implementation status

## Current foundation state

Artist Growth OS is still in the foundation / controlled-proof phase. Autonomous social publishing remains disabled.

Implemented foundation:

- modular-monolith FastAPI backend, PostgreSQL domain persistence, Alembic migrations, and deterministic FFmpeg/ffprobe media pipeline
- fail-closed rights, policy, distinctness, QC, and publication eligibility boundaries
- transactional publication spine with durable decisions, render/publication lineage, PublicationAttempt recovery, and idempotency protection
- DB-backed background jobs with bounded retries, leases, PostgreSQL `FOR UPDATE SKIP LOCKED`, stale-worker rejection, and quarantine of ambiguous publication outcomes
- platform-proof harness with PlatformAccount, capability snapshots, durable proof runs/events, remote recovery context, and credential-safe evidence
- proof-only Instagram, YouTube, and TikTok adapter contracts behind the same proof boundary
- shared `PlatformProofOperator`; generic live publishing is disabled by default and an opted-in runner still requires the exact phrase `I_UNDERSTAND_THIS_WILL_POST_PUBLICLY`
- Instagram guarded operator runner; YouTube and TikTok do not have live operator runners
- read-only `ProofInspector` service plus credential-free `artist-growth-proof-inspect list|show` CLI
- reproducible Next.js frontend with committed npm lockfile and dedicated Frontend CI
- first COMMAND / SYSTEM control-plane shell using typed repository fixture data only; no live credentials, network fetches, or action authority

## Current remote validation baseline

### Backend

GitHub Actions is the authoritative backend acceptance gate. It runs with read-only repository permissions and requires:

- editable backend install
- Ruff
- Python compileall
- full pytest suite
- SQLite `upgrade -> downgrade base -> upgrade`
- PostgreSQL 17 `upgrade -> downgrade base -> upgrade`

Evidence progression:

- PR #6 baseline: **58 tests passed**
- PR #7 / YouTube proof adapter: **71 tests passed**
- PR #8 / TikTok proof adapter: **88 tests passed**
- PR #9 / shared proof operator: **96 tests passed**
- PR #10 / proof inspector: **113 tests passed**
- post-PR #11 `main` (`36179e251f0fd121cd25c73f1abbf52092c6ebfd`): **121 tests passed**, Ruff/compileall passed, SQLite and PostgreSQL 17 migration round-trips passed

The two current pytest warnings are upstream FastAPI/Starlette deprecation warnings, not failing application tests.

### Frontend

PR #12 removed the earlier frontend verification gap.

- committed npm lockfile: present
- Node.js: 22 in CI
- install: `npm ci --no-audit --no-fund`
- TypeScript: passed
- Next.js production build: passed
- workflow permissions: `contents: read`
- post-merge Frontend CI on `main` (`c52b73fde54b0a2e44795048d65c3aecd7ffe5e6`): passed

PR #13 control-plane code head `600163e158df5bb01ec0da54bdc951bb3ccac829` also passed locked install, TypeScript, and production build before this status update.

## Platform proof boundary

No real social adapter is production-ready merely because official documentation describes an endpoint or mocked contract tests pass.

Promotion requires empirical owned-account evidence:

`capability capture -> one controlled publication -> durable platform ID/status reconciliation -> raw metrics`

A blind second publish is never an acceptable recovery strategy.

### Instagram

- proof-only adapter uses the Instagram Login / `graph.instagram.com` publishing family
- public media URLs are constrained by operator-configured controlled media hosts
- durable container/media checkpoints support supervised reconciliation
- final-publish ambiguity becomes recovery work rather than automatic retry
- Instagram is the only platform with an explicitly enabled guarded operator publish path
- native/owned sound, Trial Reels, real insights behavior, and an owned-account controlled proof remain empirical

### YouTube

- proof adapter uses YouTube Data API v3 plus Analytics API v2
- resumable upload creates a session, performs one binary upload boundary, then durably checkpoints the video ID
- ambiguous upload outcomes never trigger an automatic second binary upload
- reconciliation requires durable owner-visible video identity
- public visibility, Shorts classification, Content ID behavior, exact analytics behavior, and owned-channel authorization remain empirical

### TikTok

- proof adapter targets TikTok API for Business Organic Accounts v1.3
- media URLs must be inside configured verified-domain / verified-prefix boundaries
- one publish request is followed by bounded status polling and durable task/post checkpoints
- unknown or ambiguous publish state fails closed into recovery
- approval/scopes, verified-property acceptance, native/owned sound behavior, exact metrics behavior, and an owned-account controlled proof remain empirical

## Proof inspection and control-plane safety

`ProofInspector` is query-only. It can list durable proof runs and reconstruct account, capability snapshot, remote context/result, and ordered proof events. The entire projection passes through the credential/evidence safety checker.

The CLI exposes only:

- `artist-growth-proof-inspect list`
- `artist-growth-proof-inspect show --run-id <UUID>`

It exposes no publish, reconcile, or metrics command and constructs no social adapter.

The web control-plane currently uses typed repository fixture data rather than backend proof data. This is intentional: the FastAPI application does not yet have a deliberate operator-authentication boundary. Durable proof/admin data should not be exposed to the browser through a new HTTP route until that boundary exists and is tested.

## Current safety invariant

- autonomy: **OFF**
- rights/policy/distinctness/ambiguous delivery: **fail closed**
- generic proof operator live publish: **disabled by default**
- Instagram live proof: explicit runner enablement + exact human confirmation only
- YouTube/TikTok: proof-only, no live runner
- proof inspector: read-only / database-only
- control-plane web shell: fixture-backed / no platform credentials / no live actions

## Next engineering increment

Do not add more social adapters for their own sake.

The next backend/control-plane boundary should be **operator authentication and authorization before any proof-inspection HTTP endpoint is mounted**. Keep the first auth slice small and auditable: protect future control-plane read APIs, distinguish operator reads from publication authority, and test default-deny behavior. Do not couple authentication work to live social credentials or to enabling autonomous publication.

After an authenticated read boundary exists, the fixture-backed COMMAND / SYSTEM shell can be connected to a read-only proof API. Real Instagram empirical proof remains a separate operational gate and requires deliberately provisioned owned-account credentials and controlled media, never secrets pasted into source or chat.

Trend Radar, autonomous creative generation, portfolio learning, and broad live dashboard actions remain downstream.
