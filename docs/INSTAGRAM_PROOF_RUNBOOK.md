# Instagram controlled proof runbook

This runbook is for the **proof-only** Instagram adapter. It does not make Instagram a production publisher and it does not enable autonomous posting.

## Runtime configuration

Use a migrated Artist Growth OS database and supply these values only at runtime:

- `INSTAGRAM_PROOF_API_VERSION` — the Graph API version currently approved for the Meta app.
- `INSTAGRAM_PROOF_ACCESS_TOKEN` — an Instagram User access token for the owned professional account.
- `INSTAGRAM_PROOF_MEDIA_HOSTS` — comma-separated hostnames that are allowed to serve the public proof video.

Do not put the access token in a command argument, proof key, media URL, caption, Git commit, issue, or log. A shell can load it without echoing it:

```bash
export INSTAGRAM_PROOF_API_VERSION='vXX.X'
export INSTAGRAM_PROOF_MEDIA_HOSTS='media.example.com'
read -s INSTAGRAM_PROOF_ACCESS_TOKEN
export INSTAGRAM_PROOF_ACCESS_TOKEN
```

The installed command is `artist-growth-instagram-proof`. From a source checkout, the equivalent is `python -m app.proofs.instagram_runner` from `backend/`.

## 1. Start — cannot publish

`start` creates/reuses the platform account and proof run, then performs only account/capability reads. It has no code path to `publish_once`.

```bash
artist-growth-instagram-proof start \
  --external-account-id '<instagram-user-id>' \
  --proof-key 'ig-proof-001' \
  --media-url 'https://media.example.com/proofs/ig-proof-001.mp4' \
  --caption 'Artist Growth OS controlled API proof'
```

Record the returned `run.id`. A successful start should end in `READY`; it does **not** create a Reel.

## 2. Inspect local state

`show` reads the database only. It intentionally does not construct an Instagram adapter and does not require Instagram credentials.

```bash
artist-growth-instagram-proof show --run-id '<run-uuid>'
```

## 3. Publish — explicit public-side-effect gate

This is the only runner command that can intentionally create a public Reel. It requires the exact confirmation phrase below:

```bash
artist-growth-instagram-proof publish \
  --run-id '<run-uuid>' \
  --confirm-live-publish I_UNDERSTAND_THIS_WILL_POST_PUBLICLY
```

Do not repeat `publish` after an ambiguous response. The proof harness will normally block it anyway, but the operator action after ambiguity is always `reconcile`.

## 4. Reconcile without reposting

Use this after a successful publish or any `RECOVERY_REQUIRED` state:

```bash
artist-growth-instagram-proof reconcile --run-id '<run-uuid>'
```

If a durable media ID exists, reconciliation reads that media object. If only the container ID survived, the adapter reads container state and stays fail-closed rather than issuing another `media_publish`.

## 5. Capture metrics

After the run is durably `PUBLISHED`:

```bash
artist-growth-instagram-proof metrics --run-id '<run-uuid>'
```

Metrics collection is independent of publication. If insights are temporarily unavailable, rerun `metrics`; do not rerun `publish`.

## Proof completion

A run is `PASSED` only after the controlled post has a durable platform media ID/status and raw media insights have been captured. Native catalog music, owned-sound behavior, Trial Reels, and synthetic-media disclosure remain separate empirical capabilities even after this basic proof succeeds.
