const nav = ["COMMAND", "ARTISTS", "MUSIC", "CREATIVE", "RADAR", "DISTRIBUTION", "EXPERIMENTS", "PERFORMANCE", "SYSTEM"];

export default function Home() {
  return (
    <main className="shell">
      <aside className="rail">
        <div className="brand">AGO</div>
        <nav>{nav.map((item, index) => <div className={index === 0 ? "nav active" : "nav"} key={item}>{item}</div>)}</nav>
      </aside>
      <section className="content">
        <header>
          <p className="eyebrow">ARTIST GROWTH OS / FOUNDATION</p>
          <h1>Creative Publication Spine</h1>
          <p className="lede">Phase 1 is deliberately narrow: deterministic render, fail-closed rights, QC, candidate eligibility, and idempotent publication adapters.</p>
        </header>
        <div className="grid">
          <article className="panel span2">
            <span className="label">CURRENT AUTONOMY</span>
            <strong>OFF / FOUNDATION BUILD</strong>
            <p>No autonomous social publishing is enabled in this phase.</p>
          </article>
          <article className="panel">
            <span className="label">PUBLISHER</span>
            <strong>FakePublisher</strong>
            <p>Exercises the production adapter contract without a social API.</p>
          </article>
          <article className="panel">
            <span className="label">RIGHTS</span>
            <strong>FAIL CLOSED</strong>
            <p>Unknown, restricted, or expired required grants stop the candidate.</p>
          </article>
          <article className="panel span2 flow">
            <span className="label">VERTICAL SLICE</span>
            <div>Artist → Track → Segment → Rights → Asset → Seed → Concept → Audio Plan → Render Plan → FFmpeg → QC → Candidate → Publication</div>
          </article>
        </div>
      </section>
    </main>
  );
}
