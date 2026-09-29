/* Typed client for the MarkText API. Every call throws ApiError with the
   server's message so screens can show it inline. */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, `The API at ${API_URL} is not reachable. Start it with: uvicorn api.main:app --port 8000`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.headers.get("content-type")?.includes("text/csv")) {
    return (await res.text()) as unknown as T;
  }
  return (await res.json()) as T;
}

export type Mode = "normal" | "watermarked";
export type Verdict =
  | "LIKELY MARKTEXT"
  | "POSSIBLE WATERMARK"
  | "NOT DETECTED"
  | "INCONCLUSIVE (short text)";

export interface Health {
  status: "ok" | "model_unavailable";
  model_id: string | null;
  device: string | null;
  key_is_public: boolean;
  notes: string[];
  load_error: string | null;
}

export interface Generation {
  text: string;
  mode: Mode;
  watermarked: boolean;
  cancelled: boolean;
  seed: number;
  max_new_tokens: number;
  new_tokens: number;
  model_id: string;
  device: string;
  temperature: number;
  top_p: number;
  top_k: number;
  repetition_penalty: number;
  watermark: Record<string, number | string>;
}

export interface Detection {
  num_tokens_scored: number;
  num_green_tokens: number;
  green_fraction: number;
  z_score: number;
  prediction: boolean;
  p_value: number;
  confidence: number;
  label: Verdict;
  input_tokens: number;
  device: string;
  watermark: Record<string, number | string>;
  run_id: string | null;
  log_error: string | null;
}

export interface HistoryRow {
  run_id: string;
  timestamp: string;
  source: string;
  filename: string;
  mode: string;
  batch_id: string;
  max_new_tokens: number | null;
  seed: number | null;
  gen_tokens: number | null;
  tokens_scored: number;
  green_tokens: number;
  green_pct: number;
  z_score: number;
  p_value: number | null;
  result: Verdict | string;
  bias: number | null;
  greenlist_ratio: number | null;
  seeding_scheme: string;
  context_width: number | null;
  device: string | null;
  note: string;
}

export interface HistoryResponse {
  total: number;
  kpis: { count: number; mean_z: number | null; flagged_rate: number | null; median_tokens: number | null };
  summary: Array<Record<string, string | number>>;
  rows: HistoryRow[];
  options: { results: string[]; sources: string[]; batches: string[] };
  thresholds: { detection_threshold: number; possible_threshold: number; min_tokens_for_verdict: number };
}

export interface HistoryFilters {
  result?: string[];
  source?: string[];
  batch_id?: string;
  q?: string;
  date_from?: string;
  date_to?: string;
  min_tokens?: number;
}

export interface BatchSummaryRow {
  mode: Mode;
  max_new_tokens: number;
  n: number;
  mean_z: number;
  mean_green_pct: number;
  flagged_rate: number;
  possible_or_above_rate: number;
  inconclusive_rate: number;
  retokenize_mismatch: number;
  rate_meaning: string;
}

export interface JobState {
  running: boolean;
  batch_id: string | null;
  done: number;
  total: number;
  last: { run_id: string; prompt_idx: number; length: number; mode: Mode; run: number; z: number; label: string } | null;
  error: string | null;
  started: number | null;
  finished: number | null;
}

export interface BatchDetail {
  batch_id: string;
  rows: number;
  settings: Record<string, unknown> | null;
  summary: BatchSummaryRow[];
  points: Array<{ run_id: string; mode: Mode; max_new_tokens: number; tokens_scored: number; z_score: number; result: string }>;
  job: JobState | null;
}

function qs(params: Record<string, string | number | string[] | undefined>) {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === "" || v === 0) continue;
    if (Array.isArray(v)) v.forEach((x) => u.append(k, x));
    else u.set(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

export const api = {
  health: () => request<Health>("/health"),
  config: () => request<Record<string, unknown>>("/config"),
  readme: () => request<{ markdown: string }>("/readme"),
  prompts: () => request<{ count: number; path: string; prompts: string[] }>("/prompts"),

  generate: (body: { prompt: string; max_new_tokens: number; mode: Mode; seed?: number | null }) =>
    request<Generation>("/generate", { method: "POST", body: JSON.stringify(body) }),
  save: (generation: Generation) =>
    request<{ text_path: string; sidecar_path: string }>("/generate/save", {
      method: "POST",
      body: JSON.stringify({ generation }),
    }),

  detect: (body: { text: string; filename?: string; source?: "manual" | "file"; extra?: Record<string, unknown> }) =>
    request<Detection>("/detect", { method: "POST", body: JSON.stringify(body) }),

  history: (f: HistoryFilters = {}) => request<HistoryResponse>(`/history${qs({ ...f })}`),
  exportHistoryUrl: (f: HistoryFilters = {}) => `${API_URL}/history/export${qs({ ...f })}`,
  record: (id: string) => request<HistoryRow>(`/history/${id}`),
  updateRecord: (id: string, body: { note?: string; filename?: string }) =>
    request<{ record: HistoryRow; backup: string }>(`/history/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteRecord: (id: string) =>
    request<{ deleted: string; backup: string }>(`/history/${id}`, { method: "DELETE" }),
  clearHistory: () => request<{ backup: string }>("/history/clear", { method: "POST" }),

  experiments: () =>
    request<{ batches: Array<{ batch_id: string; rows: number; settings: Record<string, unknown> | null }>; job: JobState }>(
      "/experiments",
    ),
  startExperiment: (body: { n_prompts: number; lengths: number[]; runs: number; seed_base: number; resume?: string | null }) =>
    request<JobState>("/experiments", { method: "POST", body: JSON.stringify(body) }),
  experiment: (id: string) => request<BatchDetail>(`/experiments/${id}`),
  stopExperiment: (id: string) => request<JobState>(`/experiments/${id}/stop`, { method: "POST" }),
  exportExperimentUrl: (id: string) => `${API_URL}/experiments/${id}/export`,
};
