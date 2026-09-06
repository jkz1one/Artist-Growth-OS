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
│   │   ├── models/          # persistence models
│   │   ├── platforms/       # Publisher adapters
│   │   ├── rendering/       # FFmpeg + QC
│   │   ├── schemas/         # validated render/job contracts
│   │   ├── services/        # rights/policy/distinctness/spine/jobs
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
HTTP command
    ↓
BackgroundJob
    ↓ lease/token
DurableWorker
    ↓
PublicationJobHandler
    ↓
PersistentPublicationSpine
    ├── RightsEngine
    ├── FoundationPolicyEngine
    ├── FoundationDistinctnessEngine
    ├── FFmpegRenderer → MediaQC
    └── Publisher protocol → FakePublisher / future real adapters
```

## Current safety behavior

- Rights: required evidence must be currently effective and CLEAR.
- Policy: a structured classification is required; absence is UNKNOWN and blocks.
- Distinctness: exact RenderPlan duplicates block; richer perceptual/semantic comparison is deferred.
- QC: validates playable media, H.264 video, expected resolution, positive duration, and AAC when audio is expected.
- Publishing: idempotency key derives from candidate + platform + rendered bytes; database uniqueness also enforces one publication per candidate/platform.
- Restart safety: PUBLISHED work is reused from the database; ambiguous UPLOADING/PROCESSING work requires reconciliation and is never blindly resubmitted.
- Decision lineage: rights, policy, and distinctness decisions are versioned rows and are persisted even when a candidate is rejected before render.
- Job enqueue: `(job_type, idempotency_key)` is unique and may be reused only when the command payload hash is identical. Publication job keys are derived from candidate + target platform, not caller-controlled.
- Job ownership: leases have opaque tokens. Expired/stale workers cannot commit results, even before another worker reclaims the job.
- Crash recovery: expired RUNNING jobs are reclaimable only while attempt budget remains. Exhausted crash loops become FAILED.
- Retry safety: retries are delayed and bounded. QUARANTINED jobs are never automatically retried.
- Filesystem boundary: HTTP callers cannot select render output paths; workers derive publication artifact paths under the configured render root.

## Intentionally not implemented yet

No Trend Radar, scraping, headless publishing, engagement automation, ML optimizer, contextual bandit, production OAuth, or real social platform adapter is present in Phase 1.
