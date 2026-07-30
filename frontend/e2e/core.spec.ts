/**
 * Three deterministic core flows. Backend responses are intercepted at the
 * browser boundary (page.route on /api/backend/*), so these validate the
 * frontend's real behavior — streaming assembly, polling state machine,
 * rendering — without depending on LLM latency or corpus content.
 */
import { expect, test, type Page } from "@playwright/test";

const stub = (page: Page, path: string, json: object, status = 200) =>
  page.route(`**/api/backend/${path}`, (route) => route.fulfill({ status, json }));

// Auth is enforced server-side; every flow starts from a real session.
test.beforeEach(async ({ page }) => {
  const res = await page.request.post("/api/auth/login", {
    data: { password: process.env.AUTH_PASSWORD ?? "knowall-dev-password-change-me" },
  });
  expect(res.ok()).toBeTruthy();
});

test("auth: unauthenticated visitors get the login screen, not the app", async ({ browser }) => {
  const anonymous = await browser.newContext(); // no session cookie
  const page = await anonymous.newPage();
  await page.goto("/");
  await expect(page.getByTestId("login-password")).toBeVisible();
  await expect(page.getByTestId("chat-input")).toHaveCount(0);
  // The proxy must refuse to attach a backend key for an anonymous caller.
  const relayed = await page.request.get("/api/backend/list_documents");
  expect(relayed.status()).toBe(401);
  await anonymous.close();
});

test("ingestion: upload → poll → Completed badge", async ({ page }) => {
  await stub(page, "list_documents", { files: ["existing.pdf"] });
  await stub(page, "upload", { job_id: "e2e-0001", status: "queued", status_url: "/ingest/status/e2e-0001" }, 202);

  let polls = 0;
  await page.route("**/api/backend/ingest/status/e2e-0001", (route) => {
    polls += 1; // first poll: still running; afterwards: done
    route.fulfill({
      json:
        polls < 2
          ? { job_id: "e2e-0001", status: "running" }
          : { job_id: "e2e-0001", status: "completed", chunks_embedded: 7 },
    });
  });

  await page.goto("/documents");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Choose files" }).click();
  await (await chooser).setFiles({ name: "tiny.txt", mimeType: "text/plain", buffer: Buffer.from("hello") });

  const row = page.getByTestId("job-row").filter({ hasText: "tiny.txt" });
  await expect(row.getByTestId("job-status")).toHaveText("completed", { timeout: 10_000 });
  await expect(row).toContainText("7 chunks");
});

test("chat: streamed tokens assemble + citation block expands", async ({ page }) => {
  await stub(page, "list_documents", { files: [] }); // source filter hidden
  const ndjson =
    [
      JSON.stringify({
        type: "citations",
        citations: [
          { index: 1, text: "PowerShell is not compatible with the Databricks platform.", source: "Mastering the Cloud.docx", page_number: "?", score: 0.91 },
        ],
        standalone_question: "Can Databricks be managed using PowerShell?",
        trace_id: "t-e2e",
      }),
      JSON.stringify({ type: "token", text: "No — " }),
      JSON.stringify({ type: "token", text: "PowerShell is not supported [1]." }),
      JSON.stringify({ type: "done" }),
    ].join("\n") + "\n";
  await page.route("**/api/backend/query/stream", (route) =>
    route.fulfill({ status: 200, contentType: "application/x-ndjson", body: ndjson })
  );

  await page.goto("/");
  await page.getByTestId("chat-input").fill("Can Databricks be managed using PowerShell?");
  await page.getByRole("button", { name: "Send" }).click();

  // Both token events concatenated proves the NDJSON assembly path.
  const answer = page.getByTestId("message-assistant");
  await expect(answer).toContainText("No — PowerShell is not supported [1].");

  const citations = answer.getByTestId("citation-block");
  await citations.locator("summary").click();
  await expect(citations).toContainText("Mastering the Cloud.docx");
  await expect(citations).toContainText("relevance 0.91");
});

test("telemetry: p50/p95 table renders from /stats", async ({ page }) => {
  await stub(page, "stats", {
    n: 12,
    abstention_rate: 0.1,
    cache_hit_rate: 0.25,
    retrieval_ms: { p50: 850, p95: 2100 },
    generation_ms: { p50: 4000, p95: 9000 },
  });

  await page.goto("/telemetry");
  await expect(page.getByText("10.0%")).toBeVisible(); // abstention tile

  const table = page.getByTestId("stats-table");
  const retrievalRow = table.getByRole("row").filter({ hasText: "Hybrid retrieval + rerank" });
  await expect(retrievalRow).toContainText("850");
  await expect(retrievalRow).toContainText("2,100");
  // Stages with no data yet degrade to em-dashes, not crashes.
  await expect(table.getByRole("row").filter({ hasText: "Query rewrite" })).toContainText("—");
});
