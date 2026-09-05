# Artist Growth OS

Rights-aware, multi-artist creative publication spine for curated music-growth accounts.

This repository intentionally begins with the internal Phase 1 closed loop. Trend Radar, ML optimization, and production social publishing are later phases.

## Current slice

`Artist -> Track -> TrackSegment -> RightsGrant -> Asset -> SeedPost -> CreativeConcept -> AudioUsePlan -> RenderPlan -> FFmpeg -> QC -> Candidate -> FakePublisher -> Publication`

The code is organized as a modular monolith. Platform-specific behavior is behind adapter interfaces; domain logic does not depend on a social platform SDK.

## Local prerequisites

- Python 3.13+
- Node 22+
- FFmpeg / ffprobe
- Docker (for PostgreSQL)

## Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
uvicorn app.main:app --reload
```

## Web

```bash
cd apps/web
npm install
npm run dev
```

## Database

```bash
docker compose up -d db
cd backend
alembic upgrade head
```

## Architectural invariants

1. Multi-artist is native; platform account IDs never live on Artist.
2. Rights fail closed: UNKNOWN/EXPIRED/RESTRICTED cannot autonomously publish.
3. Creative plans are structured and renderer execution is deterministic.
4. Platform quirks stay behind adapter/capability interfaces.
5. Publications are idempotent and carry full lineage.
6. Raw observations remain separate from derived/normalized outcomes.
