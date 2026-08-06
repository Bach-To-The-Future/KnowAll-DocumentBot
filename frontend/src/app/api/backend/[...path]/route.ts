/**
 * Auth-injecting reverse proxy to the FastAPI backend.
 *
 * The browser talks same-origin to /api/backend/* (no CORS); this handler
 * adds the API key server-side, so no key ever reaches the client.
 * Responses stream through untouched, which keeps the NDJSON /query/stream
 * tokens flowing without buffering.
 *
 * Security model (Lockdown Phase 1):
 *   1. Session gate      — enforceSession() before anything is forwarded.
 *   2. Privilege split   — read paths carry API_QUERY_KEY (read-only scope on
 *                          the backend); write paths carry API_KEY.
 *   3. Payload ceiling   — Content-Length over MAX_BODY_BYTES → 413, before
 *                          a single byte is relayed upstream.
 */
import { NextRequest } from "next/server";

import { verifySession } from "@/lib/auth";

export const dynamic = "force-dynamic";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const ADMIN_KEY = process.env.API_KEY ?? "";
// Falls back to the admin key only if no read-only key is configured, so a
// misconfigured deploy degrades to "works" rather than "silently 401s".
const QUERY_KEY = process.env.API_QUERY_KEY || ADMIN_KEY;

const MAX_BODY_BYTES = 100 * 1024 * 1024; // 100 MB — mirrored server-side

// Read-only surface: must stay in sync with READONLY_PATH_PREFIXES in
// backend/api/dependencies.py, which enforces the same split independently.
const READ_ONLY: RegExp[] = [
  /^query$/,
  /^query\/stream$/,
  /^list_documents$/,
  /^stats$/,
  /^ingest\/status\/[0-9a-fA-F-]+$/,
  /^health$/,
];

// Write surface: mutates storage or the index — always the admin key.
const WRITE: RegExp[] = [/^upload$/, /^ingest_from_minio$/, /^delete_documents$/];

type Scope = "read" | "write" | null;

function classify(path: string): Scope {
  if (READ_ONLY.some((re) => re.test(path))) return "read";
  if (WRITE.some((re) => re.test(path))) return "write";
  return null; // not on the allowlist at all
}

async function proxy(
  req: NextRequest,
  params: Promise<{ path: string[] }>
): Promise<Response> {
  // Cryptographic verification of the encrypted session cookie. No key is
  // attached to anything that fails here.
  const auth = await verifySession();
  if (!auth.ok) {
    return Response.json({ detail: "Unauthenticated." }, { status: 401 });
  }

  const { path } = await params;
  const joined = path.join("/");
  const scope = classify(joined);
  if (scope === null) {
    return Response.json({ detail: `Unknown API path: ${joined}` }, { status: 404 });
  }

  // Reject oversized uploads at the edge — never relay them upstream.
  const declaredLength = Number(req.headers.get("content-length") ?? 0);
  if (declaredLength > MAX_BODY_BYTES) {
    return Response.json(
      { detail: `Payload too large: limit is ${MAX_BODY_BYTES} bytes.` },
      { status: 413 }
    );
  }

  // FastAPI's upload route is declared with a trailing slash; Next strips it.
  const target = joined === "upload" ? "upload/" : joined;

  const headers = new Headers();
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType); // keeps multipart boundaries
  const key = scope === "read" ? QUERY_KEY : ADMIN_KEY;
  if (key) headers.set("x-api-key", key);

  // Identity for per-user rate limiting. The backend keys its limiter on
  // these because request.client.host is always this container; they are
  // trustworthy only because we set them AFTER verifying the session and
  // the backend requires an API key that only this proxy holds.
  headers.set("x-user-id", auth.userId);
  const clientIp =
    req.headers.get("x-forwarded-for") ?? req.headers.get("x-real-ip");
  if (clientIp) headers.set("x-forwarded-for", clientIp);

  // Phase 4.2: forward the browser's trace id unchanged so an upload can be
  // followed into worker logs and, if it fails, into the DLQ entry. UNLIKE
  // x-user-id above this is NOT an identity and carries no trust — the API
  // sanitises it and mints a replacement if it is malformed. It is relayed
  // verbatim precisely so correlation survives; nothing authorises on it.
  const traceId = req.headers.get("x-trace-id");
  if (traceId) headers.set("x-trace-id", traceId);

  const init = {
    method: req.method,
    headers,
    body: req.body, // streamed through — uploads are never buffered in Node
    cache: "no-store",
    duplex: "half", // required by undici when body is a stream
    // Propagate client disconnects upstream: without this, an abandoned
    // /query/stream can leave the backend LLM generating to completion.
    signal: req.signal,
  } as RequestInit & { duplex: "half" };

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND_URL}/${target}${req.nextUrl.search}`, init);
  } catch (error) {
    // Aborts are the client's own doing — not a backend fault worth logging.
    if (req.signal.aborted) return new Response(null, { status: 499 });
    console.error(`Proxy to ${target} failed:`, error);
    return Response.json({ detail: "Backend unreachable." }, { status: 502 });
  }

  // Allowlist rather than blanket copy: hop-by-hop and auth-bearing headers
  // must not be relayed, but backpressure signals must be — a 429/503 whose
  // Retry-After is stripped is a client that cannot back off correctly.
  // x-trace-id is echoed back so the browser can log the id the server
  // actually used, which differs from the one it sent when that was
  // malformed or absent.
  const PASS_THROUGH = ["content-type", "retry-after", "content-disposition",
                        "x-trace-id"];
  const responseHeaders = new Headers();
  for (const name of PASS_THROUGH) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, ctx.params);
}

export function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, ctx.params);
}

export function DELETE(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, ctx.params);
}
