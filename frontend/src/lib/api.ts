/** Typed client for the same-origin backend proxy (/api/backend/*). */
import type {
  ApiErrorBody,
  DeleteDocumentsResponse,
  IngestAccepted,
  JobStatus,
  ListDocumentsResponse,
  StatsResponse,
} from "@/types/api";

const BASE = "/api/backend";

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store", ...init });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = (await res.json()) as ApiErrorBody;
      if (body.detail) detail = body.detail;
    } catch {
      // non-JSON error body: keep the generic message
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

export async function listDocuments(): Promise<string[]> {
  const data = await request<ListDocumentsResponse>("/list_documents");
  return data.files;
}

export function uploadDocument(file: File): Promise<IngestAccepted> {
  const form = new FormData();
  form.append("file", file); // field name must match FastAPI's UploadFile param
  return request<IngestAccepted>("/upload", { method: "POST", body: form });
}

export function getJobStatus(jobId: string): Promise<JobStatus> {
  return request<JobStatus>(`/ingest/status/${jobId}`);
}

export function deleteDocuments(objectNames: string[]): Promise<DeleteDocumentsResponse> {
  return request<DeleteDocumentsResponse>("/delete_documents", {
    method: "DELETE",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ object_names: objectNames }),
  });
}

export function getStats(): Promise<StatsResponse> {
  return request<StatsResponse>("/stats");
}
