export type ProofReadState =
  | "CONNECTED"
  | "NOT_CONFIGURED"
  | "AUTH_FAILED"
  | "BACKEND_UNAVAILABLE"
  | "INVALID_RESPONSE";

export type ProofDetailState = ProofReadState | "NOT_FOUND";

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

type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

export type ProofCapabilitySnapshot = {
  id: string;
  apiFamily: string;
  apiVersion: string | null;
  capabilities: Record<string, JsonValue>;
  evidence: Record<string, JsonValue>;
  capturedAt: string;
};

export type ProofEvent = {
  id: string;
  sequence: number;
  eventType: string;
  payload: Record<string, JsonValue>;
  createdAt: string;
};

export type ProofRunDetail = ProofRunSummary & {
  externalAccountId: string;
  accountType: string | null;
  apiFamily: string | null;
  mediaUri: string | null;
  platformPostId: string | null;
  canonicalUrl: string | null;
  lastError: string | null;
  publishedAt: string | null;
  completedAt: string | null;
  caption: string | null;
  idempotencyKey: string | null;
  remoteContext: Record<string, JsonValue>;
  result: JsonValue;
  capabilitySnapshot: ProofCapabilitySnapshot | null;
  events: ProofEvent[];
};

export type ProofDetailReadModel = {
  state: ProofDetailState;
  source: string;
  proof: ProofRunDetail | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isJsonValue(value: unknown): value is JsonValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return true;
  }
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isRecord(value) && Object.values(value).every(isJsonValue);
}

function asJsonRecord(value: unknown): Record<string, JsonValue> | null {
  if (!isRecord(value) || !Object.values(value).every(isJsonValue)) return null;
  return value as Record<string, JsonValue>;
}

function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
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
  if (!nullableString(value.display_name)) return null;

  return {
    id: value.id as string,
    proofKey: value.proof_key as string,
    platform: value.platform as string,
    status: value.status as string,
    displayName: value.display_name,
    accountActive: value.account_active,
    createdAt: value.created_at as string,
    attentionState: value.attention.state as string,
    attentionReason: value.attention.reason as string,
  };
}

function parseCapabilitySnapshot(value: unknown): ProofCapabilitySnapshot | null | undefined {
  if (value === null) return null;
  if (!isRecord(value)) return undefined;
  if (
    typeof value.id !== "string" ||
    typeof value.api_family !== "string" ||
    !nullableString(value.api_version) ||
    typeof value.captured_at !== "string"
  ) {
    return undefined;
  }
  const capabilities = asJsonRecord(value.capabilities);
  const evidence = asJsonRecord(value.evidence);
  if (!capabilities || !evidence) return undefined;
  return {
    id: value.id,
    apiFamily: value.api_family,
    apiVersion: value.api_version,
    capabilities,
    evidence,
    capturedAt: value.captured_at,
  };
}

function parseEvent(value: unknown): ProofEvent | null {
  if (!isRecord(value)) return null;
  if (
    typeof value.id !== "string" ||
    typeof value.sequence !== "number" ||
    !Number.isInteger(value.sequence) ||
    typeof value.event_type !== "string" ||
    typeof value.created_at !== "string"
  ) {
    return null;
  }
  const payload = asJsonRecord(value.payload);
  if (!payload) return null;
  return {
    id: value.id,
    sequence: value.sequence,
    eventType: value.event_type,
    payload,
    createdAt: value.created_at,
  };
}

function parseProofDetail(value: unknown): ProofRunDetail | null {
  const summary = parseProof(value);
  if (!summary || !isRecord(value)) return null;
  if (typeof value.external_account_id !== "string") return null;

  const nullableFields = [
    value.account_type,
    value.api_family,
    value.media_uri,
    value.platform_post_id,
    value.canonical_url,
    value.last_error,
    value.published_at,
    value.completed_at,
    value.caption,
    value.idempotency_key,
  ];
  if (!nullableFields.every(nullableString)) return null;

  const remoteContext = asJsonRecord(value.remote_context);
  if (!remoteContext || !isJsonValue(value.result)) return null;

  const capabilitySnapshot = parseCapabilitySnapshot(value.capability_snapshot);
  if (capabilitySnapshot === undefined || !Array.isArray(value.events)) return null;
  const events = value.events.map(parseEvent);
  if (events.some((event) => event === null)) return null;

  return {
    ...summary,
    externalAccountId: value.external_account_id,
    accountType: value.account_type as string | null,
    apiFamily: value.api_family as string | null,
    mediaUri: value.media_uri as string | null,
    platformPostId: value.platform_post_id as string | null,
    canonicalUrl: value.canonical_url as string | null,
    lastError: value.last_error as string | null,
    publishedAt: value.published_at as string | null,
    completedAt: value.completed_at as string | null,
    caption: value.caption as string | null,
    idempotencyKey: value.idempotency_key as string | null,
    remoteContext,
    result: value.result,
    capabilitySnapshot,
    events: events as ProofEvent[],
  };
}

function configured(): { baseUrl: string; token: string } | null {
  const baseUrl = process.env.API_BASE_URL?.replace(/\/$/, "");
  const token = process.env.CONTROL_PLANE_READ_TOKEN;
  if (!baseUrl || !token || token.length < 32) return null;
  return { baseUrl, token };
}

function degradedReadModel(state: ProofReadState, source: string): ProofReadModel {
  return { state, source, proofs: [] };
}

function degradedDetailModel(state: ProofDetailState, source: string): ProofDetailReadModel {
  return { state, source, proof: null };
}

export async function loadProofReadModel(limit = 12): Promise<ProofReadModel> {
  const config = configured();
  if (!config) {
    return degradedReadModel(
      "NOT_CONFIGURED",
      "Repository fixture — live proof read is not configured on the web server",
    );
  }

  let response: Response;
  try {
    response = await fetch(`${config.baseUrl}/v1/control-plane/proofs?limit=${limit}`, {
      headers: { Authorization: `Bearer ${config.token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
  } catch {
    return degradedReadModel(
      "BACKEND_UNAVAILABLE",
      "Repository fixture — authenticated proof backend is unavailable",
    );
  }

  if (response.status === 401 || response.status === 403) {
    return degradedReadModel(
      "AUTH_FAILED",
      "Repository fixture — web server proof credential was rejected",
    );
  }

  if (!response.ok) {
    return degradedReadModel(
      "BACKEND_UNAVAILABLE",
      `Repository fixture — proof backend returned HTTP ${response.status}`,
    );
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return degradedReadModel(
      "INVALID_RESPONSE",
      "Repository fixture — proof backend returned invalid JSON",
    );
  }

  if (!Array.isArray(payload)) {
    return degradedReadModel(
      "INVALID_RESPONSE",
      "Repository fixture — proof backend returned an unexpected shape",
    );
  }

  const proofs = payload.map(parseProof);
  if (proofs.some((proof) => proof === null)) {
    return degradedReadModel(
      "INVALID_RESPONSE",
      "Repository fixture — proof backend response failed the web read-model contract",
    );
  }

  return {
    state: "CONNECTED",
    source: "Authenticated durable proof state — fetched server-to-server",
    proofs: proofs as ProofRunSummary[],
  };
}

export async function loadProofDetail(runId: string): Promise<ProofDetailReadModel> {
  const config = configured();
  if (!config) {
    return degradedDetailModel(
      "NOT_CONFIGURED",
      "Live proof detail is not configured on the web server",
    );
  }

  let response: Response;
  try {
    response = await fetch(
      `${config.baseUrl}/v1/control-plane/proofs/${encodeURIComponent(runId)}`,
      {
        headers: { Authorization: `Bearer ${config.token}` },
        cache: "no-store",
        signal: AbortSignal.timeout(4000),
      },
    );
  } catch {
    return degradedDetailModel(
      "BACKEND_UNAVAILABLE",
      "Authenticated proof backend is unavailable",
    );
  }

  if (response.status === 401 || response.status === 403) {
    return degradedDetailModel(
      "AUTH_FAILED",
      "Web server proof credential was rejected",
    );
  }
  if (response.status === 404) {
    return degradedDetailModel("NOT_FOUND", "Durable proof run was not found");
  }
  if (!response.ok) {
    return degradedDetailModel(
      "BACKEND_UNAVAILABLE",
      `Proof backend returned HTTP ${response.status}`,
    );
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return degradedDetailModel("INVALID_RESPONSE", "Proof backend returned invalid JSON");
  }

  const proof = parseProofDetail(payload);
  if (!proof) {
    return degradedDetailModel(
      "INVALID_RESPONSE",
      "Proof detail failed the web read-model contract",
    );
  }

  return {
    state: "CONNECTED",
    source: "Authenticated durable proof detail — fetched server-to-server",
    proof,
  };
}
