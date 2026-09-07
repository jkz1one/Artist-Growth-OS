export type ProofPlatformStatus = "GUARDED_RUNNER" | "PROOF_ONLY";

export type ControlPlaneFact = {
  label: string;
  value: string;
  detail: string;
  tone: "stable" | "guarded" | "neutral";
};

export type PlatformProofFact = {
  platform: "Instagram" | "YouTube" | "TikTok";
  apiFamily: string;
  status: ProofPlatformStatus;
  evidence: string;
  empiricalBlockers: string[];
};

export const controlPlaneFixture = {
  source: "Repository fixture — no live credentials or platform calls",
  autonomy: "OFF",
  phase: "FOUNDATION / PROOF CONTROL PLANE",
  facts: [
    {
      label: "PUBLICATION BOUNDARY",
      value: "FAIL CLOSED",
      detail: "Unknown rights, policy, delivery state, or platform capability cannot silently advance.",
      tone: "guarded",
    },
    {
      label: "PROOF OPERATIONS",
      value: "READ ONLY BY DEFAULT",
      detail: "Durable proof runs are inspectable from the database without loading social credentials.",
      tone: "stable",
    },
    {
      label: "BACKEND GATE",
      value: "CI VERIFIED",
      detail: "Ruff, compileall, pytest, SQLite migrations, and PostgreSQL 17 migrations gate backend changes.",
      tone: "stable",
    },
    {
      label: "FRONTEND GATE",
      value: "LOCKED + VERIFIED",
      detail: "npm ci, TypeScript, and a production Next.js build run from the committed lockfile.",
      tone: "stable",
    },
  ] satisfies ControlPlaneFact[],
  platforms: [
    {
      platform: "Instagram",
      apiFamily: "Instagram Login / graph.instagram.com",
      status: "GUARDED_RUNNER",
      evidence: "Software contract + guarded operator path implemented; no production Publisher promotion.",
      empiricalBlockers: [
        "owned-account controlled public proof",
        "native / owned-sound behavior",
        "real insight availability and latency",
      ],
    },
    {
      platform: "YouTube",
      apiFamily: "YouTube Data API v3 + Analytics API v2",
      status: "PROOF_ONLY",
      evidence: "Resumable upload, durable video-ID recovery, and metrics contracts are mocked and CI-tested.",
      empiricalBlockers: [
        "owned-channel OAuth proof",
        "public visibility / project audit state",
        "Shorts + Content ID behavior",
      ],
    },
    {
      platform: "TikTok",
      apiFamily: "TikTok API for Business / Organic Accounts v1.3",
      status: "PROOF_ONLY",
      evidence: "Verified-property, one-publish, status reconciliation, and metrics contracts are CI-tested.",
      empiricalBlockers: [
        "Accounts API authorization / approval",
        "verified media-property acceptance",
        "artist-owned / native sound behavior",
      ],
    },
  ] satisfies PlatformProofFact[],
  pipeline: [
    "Artist",
    "Track + Segment",
    "Rights",
    "Creative Plan",
    "Deterministic Render",
    "QC",
    "Eligibility Gates",
    "Durable Publication",
    "Raw Metrics",
  ],
  inspector: {
    commands: ["list", "show"],
    attentionStates: [
      "SETUP_REQUIRED",
      "READY_FOR_GUARDED_PUBLISH",
      "RECONCILIATION_REQUIRED",
      "METRICS_PENDING",
      "RECOVERY_REQUIRED",
      "COMPLETE",
    ],
    constraint: "Inspection is database-only. No publish, reconcile, or metrics command is exposed by the inspector CLI.",
  },
} as const;
