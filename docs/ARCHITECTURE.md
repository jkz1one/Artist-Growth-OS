# Architecture — Phase 1

## Repository shape

```text
artist-growth-os/
├── apps/
│   └── web/                 # Next.js control plane shell
├── backend/
│   ├── app/
│   │   ├── api/             # HTTP boundary
│   │   ├── db/              # SQLAlchemy base/session
│   │   ├── domain/          # shared enums/value language
│   │   ├── models/          # persistence models
│   │   ├── platforms/       # Publisher adapters
│   │   ├── rendering/       # FFmpeg + QC
│   │   ├── schemas/         # validated render/data contracts
│   │   └── services/        # rights/policy/distinctness/spine
│   ├── alembic/             # durable schema migrations
│   └── tests/               # closed-loop acceptance tests
├── docs/
├── infra/
└── var/media/               # local dev publication artifacts only
```

## Dependency direction

HTTP and workers may call application services. Application services depend on domain contracts and adapter interfaces. Platform adapters and persistence implement those contracts. Domain logic must not import a social SDK.

```text
API / Worker
    ↓
PublicationSpine
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
- Publishing: idempotency key derives from candidate + platform + rendered bytes; FakePublisher returns the same remote identity on retry.

## Intentionally not implemented yet

No Trend Radar, scraping, headless publishing, engagement automation, ML optimizer, contextual bandit, production OAuth, or real social platform adapter is present in Phase 1.
