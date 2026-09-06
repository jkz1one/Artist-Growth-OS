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

## TikTok — proof-only adapter implemented

The third real proof adapter targets the current **TikTok API for Business / Organic API / Accounts API** path for a brand-owned TikTok account. It deliberately does not implement a production `Publisher` or a live proof runner.

Current official TikTok documentation (verified 2026-09-06) establishes the following platform mechanics:

- API for Business uses `https://business-api.tiktok.com/open_api` with current reference version `v1.3`;
- Accounts API exposes token-scope inspection, owned business-account profile data, account media, posting settings, public video publishing, and publishing-status lookup;
- public video publishing uses `/business/video/publish/` for an owned TikTok account;
- publish reconciliation uses `/business/publish/status/`;
- account post data/metrics are available through `/business/video/list/`;
- a video URL supplied to the publish endpoint must be covered by an owned verified URL property; TikTok blocks unverified URLs outside its documented testing exception;
- TikTok supports domain and URL-prefix verification for those media properties;
- beginning 2026-03-20, new app/scope requests involving TikTok Accounts require the Accounts API Access Application Form.

Official sources:
- https://ads.tiktok.com/gateway/docs/index?doc_id=1735712062490625
- https://ads.tiktok.com/gateway/docs/index?doc_id=1735713875563521
- https://ads.tiktok.com/gateway/docs/index?doc_id=1769324038780930
- https://www.postman.com/tiktok-business-api/tiktok-api-for-business/documentation/2c2o0ps/tiktok-api-for-business

### What the TikTok adapter proves in software

`TikTokProofAdapter`:

- keeps the runtime access token out of dataclass `repr()` and sends it only in the `Access-Token` header;
- inspects token scopes and the configured owned business account before publication;
- probes video publishing settings and business-video access before marking software-level publish/metric support;
- requires proof media to use HTTPS and match an operator-configured verified host or verified URL prefix;
- validates URL-prefix host/path boundaries so lookalike hosts cannot pass the allowlist;
- calls `/business/video/publish/` exactly once per proof attempt;
- durably checkpoints the returned publish task ID before waiting for completion;
- polls `/business/publish/status/` only within a bounded window;
- treats request transport ambiguity, server errors, a missing publish task ID, and unresolved bounded polling as recovery-required rather than issuing a second publish call;
- preserves raw status payloads and recognizes the known processing/completion/failure families used by the current API contract while failing closed on any unknown status;
- treats an inbox-routed upload as failure for the public-publication proof rather than silently accepting it;
- checkpoints a durable post ID immediately when status supplies one;
- reconciles only from a durable post ID or publish task ID; it never searches by caption/title and never republishes automatically;
- reads a known post through `/business/video/list/` and exposes a conservative proof-level metric map while preserving the raw platform response;
- strips explicit credential-like fields and redacts the configured access token before raw platform evidence can be persisted.

The configured verified host/prefix is only an operator claim until TikTok itself accepts the URL in a controlled proof. `can_use_verified_media_url` therefore remains `REQUIRES_PROOF` even when local validation passes.

### TikTok remains empirical

- real Accounts API authorization and approved scopes for the owned curation account/app;
- the 2026 Accounts API Access Application outcome for our app;
- TikTok acceptance of the configured verified media-domain or URL-prefix property;
- the exact publish-status payload/state timing returned to our account;
- artist-owned/native sound strategy and commercial-music attachment behavior;
- synthetic-media disclosure capability for this exact API/account path;
- exact post-insight fields and reporting latency;
- a real controlled public post and raw metric retrieval.

## Promotion rule

A capability registry entry preserves where its evidence came from. Documentation-derived assumptions remain `UNKNOWN`/`REQUIRES_PROOF` when account behavior can differ. A proof run becomes `PASSED` only after a controlled post has a durable platform ID/status and raw metrics have been retrieved without a second publication call.
