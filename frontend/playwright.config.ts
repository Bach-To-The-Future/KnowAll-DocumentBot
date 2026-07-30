/**
 * Targets the already-running compose stack (no webServer block).
 *
 * Run entirely in Docker (no host Node), on the compose network:
 *
 *   docker run --rm --network knowall-bot-networks \
 *     -e BASE_URL=http://knowall-web:3000 \
 *     -v "$PWD/frontend:/work" -w /work \
 *     mcr.microsoft.com/playwright:v1.53.0-jammy \
 *     bash -c "npm i --no-save @playwright/test@1.53.0 && npx playwright test"
 */
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
