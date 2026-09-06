# Platform proof harness

The proof harness turns platform/API assumptions into account-specific evidence before a real publisher adapter is trusted with autonomous work.

## Contract

Each proof adapter implements four operations only:

1. inspect capabilities for one owned/authorized platform account;
2. perform one controlled video publication;
3. reconcile publication status without blindly publishing again;
4. retrieve the raw post metrics actually exposed to that account/API path.

Multi-step adapters may emit **durable remote checkpoints** during operation 2. Checkpoints are not extra platform operations; they persist safe remote references so a crash at the public side-effect boundary can be reconciled instead of retried.

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
- A platform's remote idempotency behavior is never assumed from Artist Growth OS's local idempotency key.

## Instagram — proof-only adapter implemented

The first real proof adapter targets the current **Instagram API with Instagram Login / Business Login for Instagram** path. It deliberately does not implement a production `Publisher` yet.

Current official Meta documentation (verified 2026-09-06) says professional accounts can publish content through `graph.instagram.com`; the publishing path uses an Instagram User access token with `instagram_business_basic` and `instagram_business_content_publish`. Reels/video publishing creates a media container from a publicly accessible `video_url`, polls the container's `status_code`, and then calls `media_publish`. The same current docs expose `/content_publishing_limit` and professional-account insights.

Official sources:
- https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api
- https://www.postman.com/meta/instagram/folder/830j7my/reels-publishing
- https://www.postman.com/meta/instagram/folder/23987686-f659d7d1-d74c-44e4-9192-9b1e8694c511

### What the Instagram adapter proves

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

### Instagram remains empirical

- native Instagram music/catalog attachment;
- artist-owned sound behavior versus baked audio;
- Trial Reels API/account exposure;
- synthetic-media disclosure fields for this exact API/account path;
- the exact insight set returned to the real curation account;
- real access-token/app-review behavior;
- a real public proof post.

These remain `UNKNOWN` or `REQUIRES_PROOF` until a controlled owned account demonstrates them.

## YouTube — proof-only adapter implemented

The second real proof adapter targets **YouTube Data API v3** for channel identity, upload, processing/status, and immediate video statistics, plus **YouTube Analytics API v2** for owner analytics. It deliberately does not implement a production `Publisher` or a live proof runner yet.

Current official Google documentation (verified 2026-09-06) establishes the following platform mechanics:

- `channels.list` with `mine=true` returns the channel owned by the OAuth-authorized user;
- resumable video upload starts with `POST https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable`, returns a session URI in `Location`, and sends the binary content with `PUT`;
- a completed resumable upload returns the created video resource and its ID;
- interrupted uploads and `308 Resume Incomplete` can be queried/resumed using the session URI;
- `videos.list` exposes owner-visible `processingDetails.processingStatus` plus upload/status data;
- `status.containsSyntheticMedia` is a supported `videos.insert` / `videos.update` disclosure field;
- API projects created after 2020-07-28 that remain unverified can have API uploads restricted to private visibility until audit;
- YouTube Analytics `reports.query` accepts `channel==MINE`, a date window, metrics, and a `video==VIDEO_ID` filter; current reference documentation requires `youtube.readonly`, in addition to the Analytics authorization scope used for user-activity reports.

Official sources:
- https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol
- https://developers.google.com/youtube/v3/docs/videos
- https://developers.google.com/youtube/v3/guides/implementation/videos
- https://developers.google.com/youtube/v3/docs/channels/list
- https://developers.google.com/youtube/analytics/reference/reports/query
- https://developers.google.com/youtube/analytics/metrics

### What the YouTube adapter proves in software

`YouTubeProofAdapter`:

- requires an OAuth access token but excludes it from dataclass `repr()` and sends it only in the Authorization header;
- verifies the configured channel ID against `channels.list(mine=true)`;
- probes Analytics access without treating an empty analytics row set as an error;
- defaults controlled proof uploads to `private`;
- marks public-video capability and Shorts classification `REQUIRES_PROOF` rather than inferring them from documentation;
- accepts an existing local proof video file instead of fetching arbitrary remote media;
- creates a resumable upload session with deterministic proof metadata;
- never writes the resumable upload-session URL into durable checkpoints/evidence;
- performs one binary upload PUT in the autonomous proof attempt;
- treats binary transport ambiguity, 5xx responses, `308 Resume Incomplete`, unreadable success responses, and missing video IDs as supervised recovery rather than a second upload;
- durably checkpoints the YouTube video ID immediately after the upload response;
- performs bounded owner-visible processing polling;
- reconciles only by a known durable video ID; if no video ID survived the ambiguous boundary, it refuses search/title heuristics and refuses automatic re-upload;
- verifies that status/metric video resources belong to the configured channel;
- preserves raw Data API statistics and raw Analytics report data while exposing a small proof-level metric map.

The deliberate decision not to persist the resumable session URI means an interrupted upload cannot yet be automatically resumed by this proof adapter. Until Artist Growth OS has an encrypted/credential-appropriate store for resumable capability URLs, ambiguity fails closed instead of trading publication safety for convenience.

### YouTube remains empirical

- real `youtube.upload`, `youtube.readonly`, and `yt-analytics.readonly` authorization on the owned curation channel/app;
- whether the API project is audited sufficiently for the intended public visibility;
- actual `containsSyntheticMedia` write/read behavior on the configured project;
- Shorts classification/processing behavior for our exact vertical uploads;
- Content ID behavior for artist-owned masters on a separate curation channel;
- artist-owned/baked-audio claim behavior;
- exact Analytics metric availability and reporting latency;
- a real controlled upload and raw metric retrieval.

## TikTok

TikTok API for Business documents the Organic API as the product for brands managing their organic TikTok presence. Its current reference includes public video publishing to an owned account, publishing-status lookup, account/post insights, and Discovery APIs. TikTok also requires video URLs used by the business publish endpoint to come from a verified URL property (with a documented test URL exception for testing).

Sources:
- https://ads.tiktok.com/gateway/docs/index?doc_id=1735712062490625
- https://ads.tiktok.com/gateway/docs/index?doc_id=1735713875563521
- https://ads.tiktok.com/gateway/docs/index?doc_id=1769324038780930

Still empirical:
- artist-owned/native sound strategy;
- exact account scopes and approval path;
- insight fields/latency;
- disclosure capabilities;
- verified media-domain workflow in our environment.

## Promotion rule

A capability registry entry preserves where its evidence came from. Documentation-derived assumptions remain `UNKNOWN`/`REQUIRES_PROOF` when account behavior can differ. A proof run becomes `PASSED` only after a controlled post has a durable platform ID/status and raw metrics have been retrieved without a second publication call.
