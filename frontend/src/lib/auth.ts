/**
 * Session handling for the backend proxy — iron-session (encrypted,
 * signed, stateless cookies; nothing to store server-side).
 *
 * This is the enforcement point that closes the credential-relay bypass:
 * the proxy attaches a backend API key ONLY after the cookie has been
 * cryptographically verified here.
 */
import { getIronSession, type SessionOptions } from "iron-session";
import { cookies } from "next/headers";

export const SESSION_COOKIE = "knowall_session";

// Enforcement is on by default. Disabling it re-opens anonymous relay, so it
// exists only as an explicit, deliberate local-dev escape hatch.
export const AUTH_REQUIRED = process.env.AUTH_REQUIRED !== "false";

export interface SessionData {
  authenticated?: boolean;
  /** Stable per login; forwarded to the backend for per-user rate limiting. */
  userId?: string;
  createdAt?: number;
}

const SESSION_TTL_SECONDS = 60 * 60 * 24; // 24h, matches backend session TTL

function sessionPassword(): string {
  const secret = process.env.SESSION_SECRET ?? "";
  // iron-session needs >=32 chars to derive its key. Failing loudly here beats
  // booting with a weak/absent secret and silently accepting forged cookies.
  if (AUTH_REQUIRED && secret.length < 32) {
    throw new Error(
      "SESSION_SECRET must be at least 32 characters when AUTH_REQUIRED is on."
    );
  }
  return secret.padEnd(32, "0"); // dev-only padding; unreachable when enforcing
}

export function sessionOptions(): SessionOptions {
  return {
    password: sessionPassword(),
    cookieName: SESSION_COOKIE,
    cookieOptions: {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: SESSION_TTL_SECONDS,
      // Must be true behind TLS. Left configurable because a `secure` cookie
      // is silently dropped by browsers over plain http:// (LAN deploys).
      secure: process.env.COOKIE_SECURE === "true",
    },
  };
}

export async function getSession() {
  return getIronSession<SessionData>(await cookies(), sessionOptions());
}

export interface AuthResult {
  ok: boolean;
  userId: string;
}

/** Verifies the encrypted cookie. Never trusts mere cookie presence. */
export async function verifySession(): Promise<AuthResult> {
  if (!AUTH_REQUIRED) return { ok: true, userId: "anonymous" };
  try {
    const session = await getSession();
    if (session.authenticated && session.userId) {
      return { ok: true, userId: session.userId };
    }
  } catch {
    // Tampered/undecryptable cookie, or a rotated SESSION_SECRET.
  }
  return { ok: false, userId: "" };
}
