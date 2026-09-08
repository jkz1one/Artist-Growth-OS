import Link from "next/link";

import { JsonValue, loadProofDetail } from "../../../lib/control-plane-api";
import styles from "./page.module.css";

export const dynamic = "force-dynamic";

function formatTime(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(date);
}

function jsonText(value: JsonValue) {
  return JSON.stringify(value, null, 2);
}

export default async function ProofDetailPage(props: { params: Promise<{ runId: string }> }) {
  const { runId } = await props.params;
  const read = await loadProofDetail(runId);

  if (read.state !== "CONNECTED" || !read.proof) {
    return (
      <main className={styles.detailShell}>
        <Link className={styles.backLink} href="/">
          ← COMMAND
        </Link>
        <section className={styles.detailFailure}>
          <p className="eyebrow">ARTIST GROWTH OS / PROOF DETAIL</p>
          <h1>Evidence unavailable.</h1>
          <div className={`connectionBadge ${read.state.toLowerCase()}`}>
            {read.state.replaceAll("_", " ")}
          </div>
          <p>{read.source}</p>
          <p className={styles.detailConstraint}>
            This view never invents proof state and exposes no publish, reconcile, metrics, or job
            mutation controls.
          </p>
        </section>
      </main>
    );
  }

  const proof = read.proof;

  return (
    <main className={styles.detailShell}>
      <Link className={styles.backLink} href="/">
        ← COMMAND
      </Link>

      <header className={styles.detailHero}>
        <div className="heroMeta">
          <p className="eyebrow">ARTIST GROWTH OS / DURABLE PROOF</p>
          <span className="readOnlyPill">READ ONLY</span>
        </div>
        <h1>{proof.displayName || proof.proofKey}</h1>
        <p className="lede">
          Durable account, capability, publication, and event evidence returned through the
          authenticated control-plane read boundary.
        </p>
        <div className={styles.detailBadges}>
          <span>{proof.platform}</span>
          <span>{proof.status}</span>
          <span>{proof.accountActive ? "ACCOUNT ACTIVE" : "HISTORICAL ACCOUNT"}</span>
          <span>{proof.attentionState.replaceAll("_", " ")}</span>
        </div>
      </header>

      <section className={styles.detailSection} aria-labelledby="proof-identity">
        <div className={styles.detailSectionHeading}>
          <p className="eyebrow">IDENTITY / DURABILITY</p>
          <h2 id="proof-identity">One run, one explainable lineage.</h2>
        </div>
        <div className={styles.detailFacts}>
          <div><span>RUN ID</span><strong>{proof.id}</strong></div>
          <div><span>PROOF KEY</span><strong>{proof.proofKey}</strong></div>
          <div><span>EXTERNAL ACCOUNT</span><strong>{proof.externalAccountId}</strong></div>
          <div><span>ACCOUNT TYPE</span><strong>{proof.accountType || "—"}</strong></div>
          <div><span>API FAMILY</span><strong>{proof.apiFamily || "—"}</strong></div>
          <div><span>PLATFORM POST ID</span><strong>{proof.platformPostId || "—"}</strong></div>
          <div><span>CREATED</span><strong>{formatTime(proof.createdAt)}</strong></div>
          <div><span>PUBLISHED</span><strong>{formatTime(proof.publishedAt)}</strong></div>
          <div><span>COMPLETED</span><strong>{formatTime(proof.completedAt)}</strong></div>
        </div>
      </section>

      <section className={styles.detailSection} aria-labelledby="proof-attention">
        <div className={styles.detailSectionHeading}>
          <p className="eyebrow">OPERATOR ATTENTION</p>
          <h2 id="proof-attention">State without implied authority.</h2>
        </div>
        <div className={styles.detailAttention}>
          <strong>{proof.attentionState.replaceAll("_", " ")}</strong>
          <p>{proof.attentionReason}</p>
          {proof.lastError ? <pre>{proof.lastError}</pre> : null}
        </div>
      </section>

      <section className={styles.detailSection} aria-labelledby="proof-content">
        <div className={styles.detailSectionHeading}>
          <p className="eyebrow">PUBLICATION CONTENT</p>
          <h2 id="proof-content">Recorded inputs and durable outputs.</h2>
        </div>
        <div className={styles.detailTwoCol}>
          <article className={styles.jsonPanel}>
            <span className="label">CAPTION</span>
            <p className={styles.detailCopy}>{proof.caption || "—"}</p>
            <span className="label">MEDIA URI</span>
            <p className={styles.detailMono}>{proof.mediaUri || "—"}</p>
            <span className="label">CANONICAL URL</span>
            <p className={styles.detailMono}>{proof.canonicalUrl || "—"}</p>
          </article>
          <article className={styles.jsonPanel}>
            <span className="label">IDEMPOTENCY KEY</span>
            <p className={styles.detailMono}>{proof.idempotencyKey || "—"}</p>
            <span className="label">REMOTE CONTEXT</span>
            <pre>{jsonText(proof.remoteContext)}</pre>
            <span className="label">RESULT</span>
            <pre>{jsonText(proof.result)}</pre>
          </article>
        </div>
      </section>

      <section className={styles.detailSection} aria-labelledby="capability-snapshot">
        <div className={styles.detailSectionHeading}>
          <p className="eyebrow">CAPABILITY SNAPSHOT</p>
          <h2 id="capability-snapshot">What the system believed before publication.</h2>
        </div>
        {proof.capabilitySnapshot ? (
          <div className={styles.detailTwoCol}>
            <article className={styles.jsonPanel}>
              <span className="label">SNAPSHOT</span>
              <div className={styles.snapshotMeta}>
                <strong>{proof.capabilitySnapshot.apiFamily}</strong>
                <span>{proof.capabilitySnapshot.apiVersion || "VERSION UNSPECIFIED"}</span>
                <span>{formatTime(proof.capabilitySnapshot.capturedAt)}</span>
              </div>
              <pre>{jsonText(proof.capabilitySnapshot.capabilities)}</pre>
            </article>
            <article className={styles.jsonPanel}>
              <span className="label">EVIDENCE</span>
              <pre>{jsonText(proof.capabilitySnapshot.evidence)}</pre>
            </article>
          </div>
        ) : (
          <div className="emptyProofState">
            <strong>No capability snapshot is attached to this run.</strong>
          </div>
        )}
      </section>

      <section className={styles.detailSection} aria-labelledby="proof-events">
        <div className={styles.detailSectionHeading}>
          <p className="eyebrow">ORDERED EVENTS</p>
          <h2 id="proof-events">Durable event sequence.</h2>
        </div>
        {proof.events.length ? (
          <div className={styles.eventTimeline}>
            {proof.events.map((event) => (
              <article className={styles.eventCard} key={event.id}>
                <div className={styles.eventHeader}>
                  <span>#{String(event.sequence).padStart(3, "0")}</span>
                  <strong>{event.eventType}</strong>
                  <time>{formatTime(event.createdAt)}</time>
                </div>
                <pre>{jsonText(event.payload)}</pre>
              </article>
            ))}
          </div>
        ) : (
          <div className="emptyProofState">
            <strong>No durable events are recorded for this run.</strong>
          </div>
        )}
      </section>

      <footer className={styles.detailFooter}>
        <strong>READ-ONLY CONTROL PLANE</strong>
        <span>No action on this page can publish, reconcile, measure, enqueue jobs, or mutate proof state.</span>
      </footer>
    </main>
  );
}
