# Architecture — Phase 1

## Repository shape

```text
artist-growth-os/
├── apps/
│   └── web/                 # Next.js control plane shell
├── backend/
│   ├── app/
│   │   ├── api/             # HTTP command/status boundary
│   │   ├── db/              # SQLAlchemy base/session
│   │   ├── domain/          # shared enums/value language
│   │   ├── models/          # persistence + proof evidence
│   │   ├── platforms/       # Publisher + platform-proof adapter contracts
│   │   ├── rendering/       # FFmpeg + QC
│   │   ├── schemas/         # validated render/job contracts
│   │   ├── services/        # rights/policy/distinctness/spine/jobs/proofs
│   │   └── workers/         # DB-backed durable job execution
│   ├── alembic/             # durable schema migrations
│   └── tests/               # closed-loop acceptance tests
├── docs/
├── infra/
└── var/media/               # local dev publication artifacts only
```

## Dependency direction

HTTP enqueues durable commands; it does not perform FFmpeg or platform work inline. Workers lease jobs from PostgreSQL and call application services. Application services depend on domain contracts and adapter interfaces. Platform adapters and persistence implement those contracts. Domain logic must not import a social SDK.

```text
HTTP command → BackgroundJob → DurableWorker → PublicationJobHandler
                                             ↓
                                PersistentPublicationSpine
                                  ├─ rights / policy / distinctness
                                  ├─ FFmpeg → QC
                                  └─ Publisher protocol

Controlled platform proof
    ↓
PlatformProofHarness
    ├─ PlatformAccount
    ├─ PlatformCapabilitySnapshot
    ├─ PlatformProofRun + append-only events
    └─ PlatformProofAdapter
         ├─ inspect capabilities
         ├─ one controlled publish
         ├─ reconcile status
         └─ retrieve raw metrics
```

## Current safety behavior

- Required rights evidence must be currently effective and `CLEAR`; policy classification is required; exact RenderPlan duplicates block; technical QC validates playable target media.
- Publication idempotency derives from immutable candidate/platform/render identity and is enforced by database uniqueness.
- `PUBLISHED` work is reused; ambiguous `UPLOADING`/`PROCESSING` work requires reconciliation and is never blindly resubmitted.
- Background jobs use payload-hash idempotency, opaque lease tokens, bounded attempts, delayed retry, and quarantine. Expired/stale workers cannot commit results.
- HTTP callers cannot choose render output paths; workers derive them under the configured render root.
- Platform proofs are separate from production publication. Capability snapshots preserve uncertainty instead of converting documentation assumptions into booleans.
- Proof capability refresh is pre-publication only. Once the remote boundary is crossed, the run cannot be reset to a publishable state.
- Multi-step proof adapters durably checkpoint safe remote references in `PlatformProofRun.remote_context` before irreversible calls when possible.
- A remote publish followed by a local persistence failure becomes `RECOVERY_REQUIRED`; the next action is reconciliation, not another upload.
- Metrics can be retried independently of publication.
- Tokens, authorization headers, cookies, secrets, passwords, API keys, and credential-bearing URLs are forbidden in persisted proof evidence/events.

## Instagram proof adapter

The first real proof-only adapter uses the Instagram API with Instagram Login. It is configured with an explicit Graph API version, an access token held only at runtime, and a controlled-media host allowlist. The adapter creates a Reel container, checkpoints the container ID, performs bounded status polling, calls `media_publish` once, checkpoints the media ID, reconciles via media/container reads, and fetches raw media insights. Any ambiguity after the final remote call is a recovery state, not a retry signal.

## Intentionally not implemented yet

No production Instagram/TikTok/YouTube publisher, autonomous platform OAuth, Trend Radar, scraping, headless publishing, engagement automation, ML optimizer, or contextual bandit is present. The next adapters are proof-only until their real accounts pass controlled publication/status/metrics checks.
