/**
 * NDJSON stream consumer for POST /query/stream.
 *
 * The backend emits one JSON object per line: a `citations` event first,
 * then `token` events (the typewriter effect), then `done` — or an `error`
 * event mid-stream (the HTTP status is already committed by then).
 */
import type { ApiErrorBody, Citation, QueryRequest, StreamEvent } from "@/types/api";

export interface StreamHandlers {
  onCitations: (citations: Citation[], standaloneQuestion: string, traceId: string) => void;
  onToken: (text: string) => void;
  onError: (detail: string) => void;
  onDone: () => void;
}

export async function streamQuery(
  body: QueryRequest,
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch("/api/backend/query/stream", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok || !res.body) {
    let detail = `Query failed (${res.status})`;
    try {
      const errorBody = (await res.json()) as ApiErrorBody;
      if (errorBody.detail) detail = errorBody.detail;
    } catch {
      // fall through with the generic message
    }
    handlers.onError(detail);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatch = (line: string): void => {
    let event: StreamEvent;
    try {
      event = JSON.parse(line) as StreamEvent;
    } catch {
      // One corrupt line must not kill an otherwise healthy stream.
      console.warn("Skipping malformed stream line:", line.slice(0, 120));
      return;
    }
    switch (event.type) {
      case "citations":
        handlers.onCitations(event.citations, event.standalone_question, event.trace_id);
        break;
      case "token":
        handlers.onToken(event.text);
        break;
      case "error":
        handlers.onError(event.detail);
        break;
      case "done":
        handlers.onDone();
        break;
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newline = buffer.indexOf("\n");
    while (newline >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) dispatch(line);
      newline = buffer.indexOf("\n");
    }
  }
  // Trailing line without a newline (defensive — the backend always ends
  // lines with \n).
  const rest = buffer.trim();
  if (rest) dispatch(rest);
}
