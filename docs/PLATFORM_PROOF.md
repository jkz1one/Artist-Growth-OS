# Platform proof harness

The proof harness turns platform/API assumptions into account-specific evidence before a real publisher adapter is trusted with autonomous work.

## Contract

Each proof adapter implements four operations only:

1. inspect capabilities for one owned/authorized platform account;
2. perform one controlled video publication;
3. reconcile publication status without blindly publishing again;
4. retrieve the raw post metrics actually exposed to that account/API path.

Multi-step adapters may emit **durable remote checkpoints** during operation 2. Checkpoints are not extra platform operations; they persist safe remote references (for example an Instagram container ID) so a crash at the public side-effect boundary can be reconciled instead of retried.

Capability values are `SUPPORTED`, `UNSUPPORTED`, `UNKNOWN`, or `REQUIRES_PROOF`. Documentation can justify a proposed capability, but account behavior must still be captured by a controlled proof before the path is promoted to autonomous publication.

## Safety invariants

- A proof run has a stable account-scoped `proof_key` and idempotency key.
- Capability refresh is allowed only before the remote publication boundary; it cannot reopen a published run.
- Safe intermediate remote references are persisted in `remote_context` before irreversible platform calls when possible.
- A post-remote database/transport ambiguity becomes `RECOVERY_REQUIRED`, never an automatic second publish.
- Metrics failure returns the proof to `PUBLISHED`; metrics can be retried without reposting.
- Proof evidence/checkpoints are rejected if they contain authorization headers, cookies, passwords, access/refresh tokens, client secrets, API keys, bearer strings, or credential-bearing URLs.
- Proof events are append-only and sequence-unique per run.
- Raw platform responses are evidence, not normalized product analytics. Normalization belongs to the later metrics layer.

## Instagram — proof-only adapter implemented

The first real proof adapter targets the current **Instagram API with Instagram Login / Business Login for Instagram** path. It deliberately does not implement a production `Publisher` yet.

Current official Meta documentation (verified 2026-09-06) says professional accounts can publish content through `graph.instagram.com`; the publishing path uses an Instagram User access token with `instagram_business_basic` and `instagram_business_content_publish`. Reels/video publishing creates a media container from a publicly accessible `video_url`, polls the container's `status_code`, and then calls `media_publish`. Meta documents `IN_PROGRESS`, `FINISHED`, `ERROR`, `EXPIRED`, and `PUBLISHED` container states and recommends polling about once per minute for no more than five minutes. The same current docs expose `/content_publishing_limit` and describe a 100 API-published-post rolling 24-hour limit for this publishing path.

Insights are also documented for professional accounts. With Instagram Login, the current guide lists `instagram_business_basic` and `instagram_business_manage_insights`; media insights include Reel-relevant metrics such as views, reach, likes, comments, shares, saved, watch-time metrics, and skip rate where applicable to the media/account.

Official sources:
- https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api
- https://www.postman.com/meta/instagram/folder/830j7my/reels-publishing
- https://www.postman.com/meta/instagram/folder/23987686-f659d7d1-d74c-44e4-9192-9b1e8694c511

### What the adapter proves

`InstagramProofAdapter`:

- requires an explicit API version instead of hard-coding one;
- keeps the access token only in runtime configuration and sends it via `Authorization: Bearer ...`;
- requires proof media to be HTTPS and on a configured controlled-host allowlist;
- probes the configured account, `/content_publishing_limit`, and account insights before marking publish/metric capabilities supported;
- creates a `REELS` container from the public proof video URL;
- durably checkpoints the container ID before final publication;
- performs bounded status polling;
- calls `media_publish` exactly once after `FINISHED`;
- checkpoints the returned media ID immediately;
- treats final-publish transport/5xx ambiguity as recovery-required;
- reconciles a known media ID by reading the published media object/permalink;
- if only a container is known, reads container status but never guesses a media ID or republishes automatically;
- fetches a conservative media-insight set and preserves the raw response.

### Still empirical / intentionally unimplemented

- native Instagram music/catalog attachment;
- artist-owned sound behavior versus baked audio;
- Trial Reels API/account exposure;
- synthetic-media disclosure fields for this exact API/account path;
- the exact insight set returned to the real curation account;
- real access-token/app-review behavior;
- a real public proof post.

These remain `UNKNOWN` or `REQUIRES_PROOF` until a controlled owned account demonstrates them.

## TikTok

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

## YouTube

The YouTube Data API documents `videos.insert` for uploads and `videos.list` with `processingDetails` for owner-visible processing status. The video resource exposes status/statistics, and the YouTube Analytics API supplies authenticated analytics. Current documentation states that uploads from unverified API projects created after July 28, 2020 are private by default until the API project passes audit.

Sources:
- https://developers.google.com/youtube/v3/docs/videos
- https://developers.google.com/youtube/v3/docs/videos/insert
- https://developers.google.com/youtube/v3/guides/implementation/videos
- https://developers.google.com/youtube/v3/docs/videos/list

Still empirical:
- Content ID behavior for artist-owned masters on a separate curation channel;
- Shorts classification/processing behavior for our exact uploads;
- analytics dimensions/latency available to the authenticated channel;
- synthetic-media metadata behavior in our exact app/account setup.

## Promotion rule

A capability registry entry preserves where its evidence came from. Documentation-derived assumptions remain `UNKNOWN`/`REQUIRES_PROOF` when account behavior can differ. A proof run becomes `PASSED` only after a controlled post has a durable platform ID/status and raw metrics have been retrieved without a second publication call.
