/**
 * TypeScript contracts mirroring the FastAPI Pydantic models
 * (backend/models/schemas.py) and the operational endpoints.
 */

// --- Query -----------------------------------------------------------------

export interface QueryRequest {
  question: string;
  /** Optional filter by source filenames (basenames or full MinIO keys). */
  documents?: string[] | null;
  /** Enables conversation memory + follow-up rewriting on the backend. */
  session_id?: string | null;
}

export interface Citation {
  index: number;
  text: string;
  source: string;
  page_number: number | string;
  /** Cross-encoder relevance in [0, 1]. */
  score: number;
}

export interface QueryResponse {
  answer_with_refs: string;
  citations: Citation[];
  standalone_question: string;
  trace_id: string;
  cached: boolean;
}

/** The exact abstention string the backend's system prompt enforces. */
export const NO_ANSWER_MESSAGE =
  "I could not find this information in the provided documents.";

// --- /query/stream NDJSON events ----------------------------------------------

export interface CitationsEvent {
  type: "citations";
  citations: Citation[];
  standalone_question: string;
  trace_id: string;
}

export interface TokenEvent {
  type: "token";
  text: string;
}

export interface ErrorEvent {
  type: "error";
  detail: string;
}

export interface DoneEvent {
  type: "done";
}

export type StreamEvent = CitationsEvent | TokenEvent | ErrorEvent | DoneEvent;

// --- Ingestion ---------------------------------------------------------------

export interface IngestAccepted {
  job_id: string;
  status: string;
  status_url: string;
}

export type JobState = "queued" | "running" | "retrying" | "completed" | "failed";

export interface JobStatus {
  job_id: string;
  status: JobState;
  object_name?: string;
  bucket?: string;
  chunks_embedded?: number;
  error?: string;
  attempts?: number;
  updated_at?: string;
}

export interface ListDocumentsResponse {
  files: string[];
}

export interface DeleteDocumentsResponse {
  deleted: string[];
  errors: { file: string; error: string }[];
  message: string;
}

// --- Telemetry -----------------------------------------------------------------

export interface LatencyPercentiles {
  p50: number;
  p95: number;
}

export interface StatsResponse {
  n: number;
  abstention_rate?: number;
  cache_hit_rate?: number;
  window_start?: number;
  rewrite_ms?: LatencyPercentiles;
  expansion_ms?: LatencyPercentiles;
  retrieval_ms?: LatencyPercentiles;
  generation_ms?: LatencyPercentiles;
}

// --- Errors ------------------------------------------------------------------

/** Standardized error envelope from the backend's global handlers. */
export interface ApiErrorBody {
  detail: string;
  error?: { type: string; message: string; detail: string | null };
}
