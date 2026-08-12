/**
 * Web-tier placeholder refusal — R1.2.
 *
 * `.env.example` ships ten `REPLACE_ME_BEFORE_ANY_DEPLOY` placeholders. The
 * backend enforces the five it can see (core/startup_checks.py); these three
 * exist ONLY in this tier, so nothing checked them at all:
 *
 *   AUTH_PASSWORD   the shared browser login secret
 *   SESSION_SECRET  the cookie encryption key
 *   API_QUERY_KEY   the read-only backend credential this proxy presents
 *
 * A published login password is worse than no password, because it looks like
 * authentication. `AUTH_REQUIRED=false` is still an explicit opt-out; a
 * placeholder is not.
 *
 * Called from the request paths that consume these values rather than a
 * process-start hook: Next.js route handlers are lazily initialised, so a
 * module-load side effect would fire at an unpredictable moment and, in dev,
 * possibly never.
 */

const PLACEHOLDERS = new Set(["REPLACE_ME", "REPLACE_ME_BEFORE_ANY_DEPLOY"]);

const DEV_MODE_VAR = "KNOWALL_INSECURE_DEV_MODE";
const DEV_MODE_VALUE = "i-understand-this-disables-authentication";

export class PlaceholderCredentialError extends Error {}

function devModeEnabled(): boolean {
  return process.env[DEV_MODE_VAR] === DEV_MODE_VALUE;
}

/** Names of web-tier credentials still set to a shipped placeholder. */
export function placeholderCredentials(
  env: NodeJS.ProcessEnv = process.env
): string[] {
  return ["AUTH_PASSWORD", "SESSION_SECRET", "API_QUERY_KEY"].filter((name) => {
    const value = (env[name] ?? "").trim();
    return value !== "" && PLACEHOLDERS.has(value);
  });
}

/**
 * Throws unless every web-tier credential has been replaced.
 *
 * Reports every offender at once. An operator who fixes one, restarts, and is
 * then told about the next will reasonably conclude the guard is broken.
 */
export function assertNoPlaceholderCredentials(
  env: NodeJS.ProcessEnv = process.env
): void {
  const offenders = placeholderCredentials(env);
  if (offenders.length === 0) return;

  const listed = offenders.join(", ");
  if (devModeEnabled()) {
    console.warn(
      `INSECURE DEV MODE: web-tier credentials are still shipped placeholders: ${listed}`
    );
    return;
  }

  throw new PlaceholderCredentialError(
    `Refusing to serve: ${offenders.length} web-tier credential(s) are still the ` +
      `shipped placeholder (${listed}). These are published in the repository, so ` +
      `anyone can read them. Replace them in .env. If this is genuinely a local ` +
      `development run, set ${DEV_MODE_VAR}=${DEV_MODE_VALUE}.`
  );
}
