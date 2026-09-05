# Phase 1 domain freeze

This file records the minimum persistence boundaries implemented for the first closed loop. It is intentionally smaller than the long-term conceptual entity list.

## Implemented now

- Artist
- ArtistCreativeProfile
- Track
- TrackSegment
- RightsGrant
- Asset
- SeedPost
- CreativeConcept
- AudioUsePlan
- RenderPlan
- Render
- Candidate
- RightsDecision
- PolicyDecision
- DistinctnessDecision
- Publication
- PublicationAttempt

## Deferred until the slice needs them

CurationBrand, DistributionChannel, PlatformAccount, PlatformCapabilitySnapshot, Campaign, ReferenceAsset, SyntheticMediaProvenance, TrendSignal/Observation, FormatDefinition/Version, MetricSnapshot, NormalizedOutcome, Experiment/Assignment, DecisionEvent, AuditEvent, BackgroundJob.

Deferral is not removal. The boundaries remain reserved by the product source of truth; we avoid empty tables before behavior exists.

## Intentional choices

### Generic RightsGrant subject

V1 uses `subject_type + subject_id` rather than separate grant tables for Track/Asset/etc. This keeps the grant model extensible while the rights engine remains explicit about required categories. The service fails closed when evidence is missing.

### Platform-independent core

`AudioUsePlan.target_platform` and `Candidate.target_platform` carry target context, but platform behavior is not embedded in Artist, Track, or creative models.

### Renderer contract

The first deterministic renderer supports a single source clip plus an optional audio slice. The JSON plan boundary is designed to expand to scenes, overlays, typography, and effects without changing Publication lineage.

### Policy/distinctness records before full engines

The decision records exist because eligibility lineage is core. Their sophisticated evaluators are intentionally deferred; no autonomous path may treat missing evaluation as CLEAR.
