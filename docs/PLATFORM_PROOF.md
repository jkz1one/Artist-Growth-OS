# Platform proof harness

The proof harness exists to turn platform/API assumptions into account-specific evidence before a real publisher adapter is trusted with autonomous work.

## Contract

Each proof adapter implements four operations only:

1. inspect capabilities for one owned/authorized platform account;
2. perform one controlled video publication;
3. reconcile publication status without blindly publishing again;
4. retrieve the raw post metrics actually exposed to that account/API path.

Capability values are `SUPPORTED`, `UNSUPPORTED`, `UNKNOWN`, or `REQUIRES_PROOF`. Documentation can justify a proposed capability, but only an account-level proof should promote uncertain audio, disclosure, analytics, or native experiment behavior into a trusted capability snapshot.

## Safety invariants

- A proof run has a stable account-scoped `proof_key` and idempotency key.
- Capability refresh is allowed only before the remote publication boundary; it cannot reopen a published run.
- A post-remote database failure becomes `RECOVERY_REQUIRED`, never an automatic second publish.
- Metrics failure returns the proof to `PUBLISHED`; metrics can be retried without reposting.
- Proof evidence is rejected if it contains authorization headers, cookies, passwords, access/refresh tokens, client secrets, API keys, bearer strings, or credential-bearing URLs.
- Proof events are append-only and sequence-unique per run.
- Raw platform responses are evidence, not normalized product analytics. Normalization belongs to the later metrics layer.

## Current official documentation findings (verified 2026-09-06)

### Instagram

Meta's official Instagram Postman workspace documents server-side Reels publishing for professional accounts: create a Reel media container from a `video_url`, poll the container `status_code`, then call `media_publish` and receive an Instagram media ID. The same official collection documents professional-account/media insights.

Sources:
- https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api
- https://www.postman.com/meta/instagram/folder/830j7my/reels-publishing

Documented enough to build a proof adapter:
- professional account authorization path;
- remote video URL ingestion;
- container processing status;
- final media publication ID;
- media/account insight APIs.

Still empirical for Artist Growth OS:
- exact native music/catalog attachment behavior for our curation accounts;
- whether owned artist audio is treated as desired under the actual account/app configuration;
- exact insight fields granted to our app/account;
- Trial Reels/API exposure for our account;
- synthetic-media disclosure fields supported by the chosen API path.

### TikTok

TikTok API for Business documents the Organic API as the product for brands managing their organic TikTok presence. Its current reference includes public video publishing to an owned account, publishing-status lookup, account/post insights, and Discovery APIs. TikTok also requires video URLs used by the business publish endpoint to come from a verified URL property (with a documented test URL exception for testing).

Sources:
- https://ads.tiktok.com/gateway/docs/index?doc_id=1735712062490625
- https://ads.tiktok.com/gateway/docs/index?doc_id=1735713875563521
- https://ads.tiktok.com/gateway/docs/index?doc_id=1769324038780930

This is the TikTok path to prove for Artist Growth OS. The creator-oriented Content Posting API should not be treated as the default internal-owned-account publication path.

Still empirical:
- artist-owned/native sound strategy;
- exact account scopes and approval path;
- insight fields/latency;
- disclosure capabilities;
- verified media-domain workflow in our environment.

### YouTube

The YouTube Data API documents `videos.insert` for uploads and `videos.list` with `processingDetails` for owner-visible processing status. The video resource exposes status/statistics, and the YouTube Analytics API supplies authenticated analytics. Current documentation states that uploads from unverified API projects created after July 28, 2020 are private by default until the API project passes audit.

Sources:
- https://developers.google.com/youtube/v3/docs/videos
- https://developers.google.com/youtube/v3/docs/videos/insert
- https://developers.google.com/youtube/v3/guides/implementation/videos
- https://developers.google.com/youtube/v3/docs/videos/list

Still empirical:
- Content ID behavior for artist-owned masters on a separate curation channel;
- Shorts classification/processing behavior for our exact uploads;
- analytics dimensions/latency that are available to the authenticated channel;
- synthetic-media metadata behavior in our exact app/account setup.

## Promotion rule

A capability registry entry must preserve where its evidence came from. Documentation-derived assumptions remain `UNKNOWN`/`REQUIRES_PROOF` when account behavior can differ. A proof run becomes `PASSED` only after a controlled post has a durable platform ID/status and raw metrics have been retrieved without a second publication call.
