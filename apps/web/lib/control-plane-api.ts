export type ProofReadState =
  | "CONNECTED"
  | "NOT_CONFIGURED"
  | "AUTH_FAILED"
  | "BACKEND_UNAVAILABLE"
  | "INVALID_RESPONSE";

export type ProofRunSummary = {
  id: string;
  proofKey: string;
  platform: string;
  status: string;
  displayName: string | null;
  accountActive: boolean;
  createdAt: string;
  attentionState: string;
  attentionReason: string;
};

export type ProofReadModel = {
  state: ProofReadState;
  source: string;
  proofs: ProofRunSummary[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseProof(value: unknown): ProofRunSummary | null {
  if (!isRecord(value) || !isRecord(value.attention)) return null;

  const requiredStrings = [
    value.id,
    value.proof_key,
    value.platform,
    value.status,
    value.created_at,
    value.attention.state,
    value.attention.reason,
  ];
  if (!requiredStrings.every((item) => typeof item === "string")) return null;
  if (typeof value.account_active !== "boolean") return null;
  if (value.display_name !== null && typeof value.display_name !== "string") return null;

  return {
    id: value.id as string,
    proofKey: value.proof_key as string,
    platform: value.platform as string,
    status: value.status as string,
    displayName: value.display_name as string | null,
    accountActive: value.account_active,
    createdAt: value.created_at as string,
    attentionState: value.attention.state as string,
    attentionReason: value.attention.reason as string,
  };
}

function configured(): { baseUrl: string; token: string } | null {
  const baseUrl = process.env.API_BASE_URL?.replace(/\/$/, "");
  const token = process.env.CONTROL_PLANE_READ_TOKEN;
  if (!baseUrl || !token || token.length < 32) return null;
  return { baseUrl, token };
}

export async function loadProofReadModel(limit = 12): Promise<ProofReadModel> {
  const config = configured();
  if (!config) {
    return {
      state: "NOT_CONFIGURED",
      source: "Repository fixture — live proof read is not configured on the web server",
      proofs: [],
    };
  }

  let response: Response;
  try {
    response = await fetch(`${config.baseUrl}/v1/control-plane/proofs?limit=${limit}`, {
      headers: { Authorization: `Bearer ${config.token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
  } catch {
    return {
      state: "BACKEND_UNAVAILABLE",
      source: "Repository fixture — authenticated proof backend is unavailable",
      proofs: [],
    };
  }

  if (response.status === 401 || response.status === 403) {
    return {
      state: "AUTH_FAILED",
      source: "Repository fixture — web server proof credential was rejected",
      proofs: [],
    };
  }

  if (!response.ok) {
    return {
      state: "BACKEND_UNAVAILABLE",
      source: `Repository fixture — proof backend returned HTTP ${response.status}`,
      proofs: [],
    };
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return {
      state: "INVALID_RESPONSE",
      source: "Repository fixture — proof backend returned invalid JSON",
      proofs: [],
    };
  }

  if (!Array.isArray(payload)) {
    return {
      state: "INVALID_RESPONSE",
      source: "Repository fixture — proof backend returned an unexpected shape",
      proofs: [],
    };
  }

  const proofs = payload.map(parseProof);
  if (proofs.some((proof) => proof === null)) {
    return {
      state: "INVALID_RESPONSE",
      source: "Repository fixture — proof backend response failed the web read-model contract",
      proofs: [],
    };
  }

  return {
    state: "CONNECTED",
    source: "Authenticated durable proof state — fetched server-to-server",
    proofs: proofs as ProofRunSummary[],
  };
}
