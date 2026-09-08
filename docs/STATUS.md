# Implementation status

## Current foundation state

Artist Growth OS remains in the foundation / controlled-proof phase. Autonomous social publishing is disabled.

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
- independent FastAPI bearer capabilities for control-plane reads and background-job API access
- authenticated GET-only control-plane proof API backed by `ProofInspector`
- reproducible Next.js frontend with committed npm lockfile and dedicated Frontend CI
- private-alpha Next.js operator wall using server-only credentials and fail-closed configuration
- COMMAND / SYSTEM dashboard with repository-backed software facts plus server-to-server durable proof reads; backend bearer credentials never enter browser JavaScript

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
- post-PR #11 `main`: **121 tests passed**
- PR #14 / default-deny API auth boundaries: **130 tests passed**
- PR #15 / authenticated read-only proof API: **137 tests passed**
- post-PR #15 `main` (`0012a1e68df32cd077242af817cc6faddb2bcafa`): Ruff, compileall, all **137 tests**, SQLite migration round-trip, and PostgreSQL 17 migration round-trip passed

The two current pytest warnings are upstream FastAPI/Starlette deprecation warnings, not failing application tests.

### Frontend

Frontend CI uses Node.js 22 and requires:

- `npm ci --no-audit --no-fund`
- TypeScript typecheck
- real Next.js production build
- workflow permissions limited to `contents: read`

Evidence progression:

- PR #12 established the committed npm lockfile and reproducible frontend baseline
- PR #13 COMMAND / SYSTEM control-plane shell passed locked install, TypeScript, and production build
- PR #16 private-alpha Next.js operator wall passed the same exact gate before merge and again on `main`
- PR #17 protected server-to-server proof reads passed locked install, TypeScript, and production build with live backend credentials absent
- post-PR #17 `main` (`2741fc3493d05b883dc6594d432f67c4d373a1a0`): locked install, TypeScript, and production build passed

## Platform proof boundary

No social adapter is production-ready merely because official documentation describes an endpoint or mocked contract tests pass.

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

`ProofInspector` remains query-only. It can list durable proof runs and reconstruct account, capability snapshot, remote context/result, and ordered proof events. The entire projection passes through the credential/evidence safety checker.

The CLI exposes only:

- `artist-growth-proof-inspect list`
- `artist-growth-proof-inspect show --run-id <UUID>`

The FastAPI control-plane exposes only authenticated GET reads:

- `GET /v1/control-plane/session`
- `GET /v1/control-plane/proofs`
- `GET /v1/control-plane/proofs/{run_id}`

The control-plane read token and job API token are independent capabilities. A read principal reports `publication_authority=false`; the read credential cannot access job routes and the job credential cannot access control-plane reads.

The private-alpha web surface is protected before rendering by Next.js Proxy. `WEB_OPERATOR_USERNAME` and `WEB_OPERATOR_PASSWORD` are server-only and missing configuration fails closed. This Basic-auth wall is an alpha boundary and must run behind HTTPS; it is not the eventual multi-user identity system.

After the operator wall succeeds, the Next.js server may call the authenticated proof API using server-only `API_BASE_URL` and `CONTROL_PLANE_READ_TOKEN`. The browser never receives the backend bearer credential. Reads use `cache: "no-store"`, a bounded timeout, runtime response validation, and explicit degraded states. If proof data is unavailable or misconfigured, the dashboard shows repository-backed software facts and no fabricated proof records.

## Current safety invariant

- autonomy: **OFF**
- rights/policy/distinctness/ambiguous delivery: **fail closed**
- generic proof operator live publish: **disabled by default**
- Instagram live proof: explicit runner enablement + exact human confirmation only
- YouTube/TikTok: proof-only, no live runner
- proof inspector: read-only
- control-plane API: authenticated GET-only proof reads
- background-job API: separate credential from control-plane reads
- private-alpha web: authenticated before rendering; backend read token remains server-only
- dashboard: read-only durable proof visibility; no publish, reconcile, metrics, or job action controls

## Next engineering increment

Do not add more social adapters for their own sake and do not broaden live publication authority.

The next control-plane slice should deepen **read-only proof observability**: add a protected proof-detail view that consumes the existing `GET /v1/control-plane/proofs/{run_id}` projection and exposes durable capability snapshot, remote context/result, and ordered proof events without adding mutation controls. Keep all social credentials server-side and preserve explicit degraded/error states.

After proof detail is visible, the next operational milestone is the first deliberate owned-account Instagram proof using separately provisioned credentials and controlled media. That remains an empirical/manual gate, not a coding assumption. YouTube/TikTok live runners, Trend Radar, autonomous creative generation, portfolio learning, and broad dashboard actions remain downstream.
