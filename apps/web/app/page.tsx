import { controlPlaneFixture } from "../lib/control-plane";
import { loadProofReadModel } from "../lib/control-plane-api";

export const dynamic = "force-dynamic";

const nav = [
  "COMMAND",
  "ARTISTS",
  "MUSIC",
  "CREATIVE",
  "RADAR",
  "DISTRIBUTION",
  "EXPERIMENTS",
  "PERFORMANCE",
  "SYSTEM",
];

function statusLabel(status: "GUARDED_RUNNER" | "PROOF_ONLY") {
  return status === "GUARDED_RUNNER" ? "GUARDED RUNNER" : "PROOF ONLY";
}

function formatProofTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "UNKNOWN TIME";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(date);
}

export default async function Home() {
  const data = controlPlaneFixture;
  const proofRead = await loadProofReadModel();

  return (
    <main className="shell">
      <aside className="rail">
        <div className="brand">AGO</div>
        <nav>
          {nav.map((item) => (
            <div className={item === "COMMAND" ? "nav active" : "nav"} key={item}>
              {item}
            </div>
          ))}
        </nav>
        <div className="railFooter">
          <span className="statusDot" />
          <span>AUTONOMY {data.autonomy}</span>
        </div>
      </aside>

      <section className="content">
        <header className="hero">
          <div className="heroMeta">
            <p className="eyebrow">ARTIST GROWTH OS / COMMAND</p>
            <span className="modeBadge">READ-ONLY FOUNDATION</span>
          </div>
          <h1>Growth control plane.</h1>
          <p className="lede">
            The operating surface for creative lineage, publication proofs, platform readiness,
            and system safety. Platform credentials never enter browser JavaScript.
          </p>
          <div className="sourceNote">
            <span>SOFTWARE FACTS</span>
            <strong>{data.source}</strong>
          </div>
          <div className={`sourceNote proofSource ${proofRead.state.toLowerCase()}`}>
            <span>PROOF STATE</span>
            <strong>{proofRead.source}</strong>
          </div>
        </header>

        <section className="sectionBlock" aria-labelledby="command-state">
          <div className="sectionHeading">
            <div>
              <p className="eyebrow">COMMAND STATE</p>
              <h2 id="command-state">{data.phase}</h2>
            </div>
            <div className="autonomyFlag">
              <span>AUTONOMY</span>
              <strong>{data.autonomy}</strong>
            </div>
          </div>

          <div className="factGrid">
            {data.facts.map((fact) => (
              <article className={`factCard ${fact.tone}`} key={fact.label}>
                <span className="label">{fact.label}</span>
                <strong>{fact.value}</strong>
                <p>{fact.detail}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="sectionBlock" aria-labelledby="durable-proofs">
          <div className="sectionHeading compact">
            <div>
              <p className="eyebrow">DURABLE PROOF RUNS</p>
              <h2 id="durable-proofs">Owned-account evidence, not assumptions.</h2>
            </div>
            <div className={`connectionBadge ${proofRead.state.toLowerCase()}`}>
              {proofRead.state.replaceAll("_", " ")}
            </div>
          </div>

          {proofRead.state === "CONNECTED" ? (
            proofRead.proofs.length > 0 ? (
              <div className="proofRunGrid">
                {proofRead.proofs.map((proof) => (
                  <article className="proofRunCard" key={proof.id}>
                    <div className="platformTopline">
                      <div>
                        <span className="label">{proof.platform}</span>
                        <h3>{proof.displayName || proof.proofKey}</h3>
                      </div>
                      <span className="runStatus">{proof.status}</span>
                    </div>
                    <p className="proofKey">{proof.proofKey}</p>
                    <div className="attentionBox">
                      <span className="label">ATTENTION</span>
                      <strong>{proof.attentionState.replaceAll("_", " ")}</strong>
                      <p>{proof.attentionReason}</p>
                    </div>
                    <div className="proofRunMeta">
                      <span>{formatProofTime(proof.createdAt)}</span>
                      <span>{proof.accountActive ? "ACCOUNT ACTIVE" : "HISTORICAL ACCOUNT"}</span>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="emptyProofState">
                <strong>Authenticated proof store connected.</strong>
                <p>No durable proof runs exist yet. Nothing is synthesized to fill the empty state.</p>
              </div>
            )
          ) : (
            <div className="emptyProofState degraded">
              <strong>Live proof state is not available.</strong>
              <p>
                The dashboard is staying on repository-backed software facts only. Configure the
                server-side API URL and control-plane read token, or restore backend availability;
                no fallback proof records will be invented.
              </p>
            </div>
          )}
        </section>

        <section className="sectionBlock" aria-labelledby="platform-proofs">
          <div className="sectionHeading compact">
            <div>
              <p className="eyebrow">PLATFORM PROOF MATRIX</p>
              <h2 id="platform-proofs">Software-ready is not production-ready.</h2>
            </div>
            <p className="sectionAside">
              Promotion requires a real owned-account proof: capability capture → one controlled
              post → durable platform ID → reconciliation → raw metrics.
            </p>
          </div>

          <div className="platformGrid">
            {data.platforms.map((platform) => (
              <article className="platformCard" key={platform.platform}>
                <div className="platformTopline">
                  <h3>{platform.platform}</h3>
                  <span className={`proofBadge ${platform.status.toLowerCase()}`}>
                    {statusLabel(platform.status)}
                  </span>
                </div>
                <p className="apiFamily">{platform.apiFamily}</p>
                <p className="evidenceText">{platform.evidence}</p>
                <div className="blockerGroup">
                  <span className="label">EMPIRICAL BLOCKERS</span>
                  <ul>
                    {platform.empiricalBlockers.map((blocker) => (
                      <li key={blocker}>{blocker}</li>
                    ))}
                  </ul>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="sectionBlock" aria-labelledby="lineage">
          <div className="sectionHeading compact">
            <div>
              <p className="eyebrow">PUBLICATION LINEAGE</p>
              <h2 id="lineage">Every post must remain explainable.</h2>
            </div>
            <p className="sectionAside">
              The foundation preserves the path from artist intent through deterministic media and
              fail-closed eligibility to durable publication evidence.
            </p>
          </div>
          <div className="pipeline" role="list">
            {data.pipeline.map((stage, index) => (
              <div className="pipelineStage" role="listitem" key={stage}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{stage}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="sectionBlock systemBlock" id="system" aria-labelledby="system-state">
          <div className="sectionHeading compact">
            <div>
              <p className="eyebrow">SYSTEM / PROOF INSPECTOR</p>
              <h2 id="system-state">Read evidence. Never imply authority.</h2>
            </div>
            <span className="readOnlyPill">DATABASE ONLY</span>
          </div>

          <div className="systemGrid">
            <article className="systemPanel">
              <span className="label">INSPECTOR COMMANDS</span>
              <div className="commandList">
                {data.inspector.commands.map((command) => (
                  <code key={command}>artist-growth-proof-inspect {command}</code>
                ))}
              </div>
              <p>{data.inspector.constraint}</p>
            </article>

            <article className="systemPanel">
              <span className="label">ATTENTION STATES</span>
              <div className="stateList">
                {data.inspector.attentionStates.map((state) => (
                  <span key={state}>{state}</span>
                ))}
              </div>
            </article>
          </div>
        </section>
      </section>
    </main>
  );
}
