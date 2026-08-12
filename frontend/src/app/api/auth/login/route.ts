/**
 * Static-password login. Phase 2 gates access with a single shared secret;
 * the session mechanics (encrypted cookie, per-user id, TTL) are already the
 * production ones, so swapping in OIDC/Auth.js later only replaces the
 * credential check below.
 */
import { randomUUID, timingSafeEqual } from "node:crypto";
import { NextRequest } from "next/server";

import { getSession } from "@/lib/auth";
import {
  PlaceholderCredentialError,
  assertNoPlaceholderCredentials,
} from "@/lib/startup-checks";

export const dynamic = "force-dynamic";

function constantTimeEquals(a: string, b: string): boolean {
  const left = Buffer.from(a, "utf8");
  const right = Buffer.from(b, "utf8");
  // timingSafeEqual throws on length mismatch, which would itself leak length;
  // compare fixed-size digests instead of raw buffers.
  if (left.length !== right.length) {
    // Still burn a comparison so the failure path costs the same.
    timingSafeEqual(left, left);
    return false;
  }
  return timingSafeEqual(left, right);
}

export async function POST(req: NextRequest) {
  // R1.2. A published login password is worse than no password: it looks like
  // authentication. Refuse before comparing anything.
  try {
    assertNoPlaceholderCredentials();
  } catch (err) {
    if (err instanceof PlaceholderCredentialError) {
      console.error(err.message);
      return Response.json({ detail: err.message }, { status: 500 });
    }
    throw err;
  }

  const expected = process.env.AUTH_PASSWORD ?? "";
  if (!expected) {
    return Response.json(
      { detail: "Login is not configured (AUTH_PASSWORD unset)." },
      { status: 500 }
    );
  }

  let password = "";
  try {
    const body = (await req.json()) as { password?: string };
    password = body.password ?? "";
  } catch {
    return Response.json({ detail: "Malformed request." }, { status: 400 });
  }

  if (!password || !constantTimeEquals(password, expected)) {
    return Response.json({ detail: "Invalid password." }, { status: 401 });
  }

  const session = await getSession();
  session.authenticated = true;
  session.userId = randomUUID(); // per-login identity for backend rate limiting
  session.createdAt = Date.now();
  await session.save();

  return Response.json({ ok: true });
}
