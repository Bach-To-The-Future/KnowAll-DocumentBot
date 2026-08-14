# Final end-to-end verification

2026-08-13. Twelve unexercised changes since the last full audit — three
dependency bumps including a starlette major, four R1 guards, the R2 output
pipeline, new provenance fields, and the memory and concurrency changes — run
together for the first time.

**Five findings, all five now closed.** The assembled system did not come up
clean, which was the expected result and the reason for running it.

---

## What was verified end to end

| # | item | result |
|---|---|---|
| 1 | cold start from a clean clone | **pass** — 37.5 min build+up, nothing hand-copied |
| 2 | startup guards on a real deployment | **pass** — every guard forced, verdicts captured |
| 3 | full user journey through the browser | **pass**, after fixing the defect it exposed |
| 4 | R2 output pipeline, both request paths | **pass** — fence 0/18, trailing 0/18 |
| 5 | starlette major under stress | **pass** — disconnect, admission, burst |
| 6 | failure and recovery | **pass** — all four paths |
| 7 | provenance and eval | **partial** — classification verified; clean-room ingest **blocked** |
| 8 | memory and concurrency | **pass** — 11.5 of 11.68 GiB declared |

### 1. Cold start

`git clone` → build → serve, with **no hand-copying**. The four files that
P0-1 restored are present in a fresh clone, which is the check that matters: a
`git show` proves a blob exists, a clone proves the tree builds.

    build + up      2252.6 s  (37.5 min)   documented ~45 min
    7/7 services healthy, exit 0

Layers: repository, volumes, models and `.env` genuinely cold; **Docker's layer
cache warm** — the images are 10 GB each and an empty cache is not feasible
here, so this is "warm layer cache, cold project", the same scoping as the
audit's 43-minute figure.

`.env.example` now requires replacing **ten** placeholders including the four
MinIO ones, so R1.3 is exercised by the setup walk rather than asserted.

### 2. Startup guards

    INFO:core.admission_limits:admission ceiling 1 needs ~3.87 GiB of 5.00 GiB (77%) for 'llama3.2:1b'.
    INFO:core.admission_limits:declared memory 11.5 GiB fits the 11.7 GiB host.

| guard | forced result |
|---|---|
| admission ceiling set to 4 | **REFUSED** — "does not fit this container's memory limit" |
| placeholders, 5 credentials × 2 entry points | **10/10 REFUSED**, each naming its variable |
| web-tier placeholder, via the user path | **HTTP 500**; login returns 200 after restore |
| port/trust, declaration absent | **REFUSED** — fails closed |
| port/trust, published | **REFUSED** |
| port/trust, loopback | started |

The worker runs its checks, which is R1.2's actual defect confirmed fixed on a
real deployment.

### 3. User journey

401 → login → three uploads with `queued → running → completed` → list →
non-streaming with correct citations (10.7 s) → streaming
`citations → token ×56 → done` → English anaphora → **French anaphora** →
unanswerable → delete → post-delete abstention.

Rewrites resolved correctly in both languages:
*"What happens if it is violated during that period?"* →
*"What happens when a newly approved vendor violates its probation?"*

### 4. R2, both paths

**Mechanical first.** Both call sites confirmed in the running image
(`query.py:535` blocking, `:602` streaming), then:

    stage ran on 16 generations, 11 WARNING lines
    corrections: scaffolding 9 · appended_decline 5 · leading_citations 2
                 · header_page_mismatch 2

| | fence | trailing | header |
|---|---|---|---|
| FR baseline → now | 2/9 → **0/9** | 0/9 → **0/9** | 1/9 → 4/9 |
| EN baseline → now | 3/9 → **0/9** | 1/9 → **0/9** | 1/9 → **0/9** |

**The four surviving headers were interpreted, not counted.** All name real
ingested documents, so the stripper correctly left them — only never-retrieved
sources are fabrications. Two were caught as **page mismatches** (`Page: 2` on
single-page PDFs): real document, impossible page, counted not stripped. That
counter exists because the previous survivor interpretation found a
documentation/implementation divergence, and it has now caught the case it was
built for.

### 5. Starlette 1.6 under stress

The highest-risk area, since the bump's acceptance tested streaming only at
concurrency 1 on a happy path.

    client disconnect mid-stream, 11 tokens delivered:
      tracebacks / GeneratorExit / unhandled : NONE
      telemetry recorded                     : "answer_chars": 223

The `finally` block still runs, so partial turns are still recorded. Had this
broken, nothing would have errored — rows would simply be missing.

Admission at ceiling 1: 5× `503` + `retry-after: 5`, 1× `200`; burst gives 1×
`200` and 2× clean `ServiceOverloadedError`. No hangs, no empty bodies.

### 6. Failure and recovery

| scenario | result |
|---|---|
| ollama stopped, both paths | 502 in 8 s, structured `EmbeddingError`, stream body **not** empty |
| worker SIGKILLed mid-ingest | `Startup sweep: failed 1 orphaned job(s)`, status `failed` with a legible reason |
| corrupt PDF | 3 attempts, dead-lettered, **trace `finalverify1234` carried browser → DLQ** |
| API restart under load | no silent-empty responses |

Caveat: at ceiling 1 the restart-under-load test is weaker than it was at
ceiling 4 — three of four requests are rejected before the restart lands.

### 7. Provenance and eval

Classification verified **in the shipped image**:

| | retrieval | full |
|---|---|---|
| OCR settings | hard | hard |
| denominators | hard | hard |
| generation flags | cosmetic | semantic |
| `require_support_quotes` | cosmetic | hard |

Retrieval-mode metrics are **identical** to the R4-era measurement —
`recall 1.0, hit 0.867, mrr 0.867, false_abstention 0.133, n_answerable 15` — so
retrieval quality is unchanged across all twelve changes.

### 8. Memory and concurrency

    host available   11.68 GiB
    declared         11.5 GiB   (ollama 4 + worker 2 + api 5 + web 0.5)
    api cgroup       5 GiB

All bumps confirmed in the running image: `fastapi 0.141.1`, `starlette 1.6.0`,
`llama-index-core 0.13.6`, `pyarrow 23.0.1`, `python-multipart 0.0.30`,
`cryptography 50.0.0` — with `pillow 11.3.0` and `fastembed 0.7.1` correctly
unmoved, which is the documented blocker rather than an oversight.

---

## Findings

### F1 — truncated closing fence bypassed the output guard · FIXED `d94f010`

A French answer reached the user as:

    <<<PASSAGE 1>> [1]  <<<PASSAGE 2>> [2][3]  <<<PASSAGE 3>> [3]

Three fences, and the guard had **run** — `"scaffolding": 0` in the trace. The
model emitted **two** closing brackets; the pattern required exactly three.

The instructive part is the earlier fix: the audit saw
`<<<DATA supplied by user>>` — also two brackets — and handled it with `>?>?>?`
**on that alternative alone**. The specific instance was patched instead of the
class, so every other fence form stayed brittle for two phases. The opening
`<<<` now identifies scaffolding and the closing run may be short; a test pins
that `std::vector<<int>>` and `a << b << c` survive.

Unit tests could not have found this: the fixtures were written from the forms
already observed.

### F2 — the eval could not run from a clean clone · FIXED `7053b15`

The corpus integrity gate failed on a fresh Windows clone: **7 of 13 tier-B
documents mismatched**, so the harness could not run at all.

    manifest        a54bedf70f18d6689e70826e2b898581ff44d54597e56bcb93acfabf01b469a5
    on disk         9b3fff1c2b1db43b04cdbb2fd08f7f272d2aaf83c28bc76703f3a9b533f4ccea
    CR removed  ->  a54bedf7...   the manifest value, exactly

No `.gitattributes`, `core.autocrlf=true`, so git rewrote LF→CRLF on checkout
and every corpus document changed bytes. **The gate was correct; the corpus was
genuinely drifted — by the checkout.** Invisible for the whole engagement
because every prior eval ran in a tree that already had the files.

Verified by cloning fresh: `corpus OK: 13 documents verified`.

### F3 — the eval corpus cannot be ingested by the code that ships · FIXED `35ec4a2`

    b04-wide-row.csv -> 1 chunk, 13,308 chars, ~4,828 tokens
                        against a 2,048-token embedding limit

The only tier-B document over the limit. It is a single CSV row wider than
`table_chunk_char_budget`, and row-based chunking cannot split *within* a row,
so the budget is unenforceable for it and the guard refuses the document rather
than admit a silently-truncated vector.

**The guard is right and the fixture is unembeddable**, and they have coexisted
the whole time because the eval collection was never rebuilt from scratch after
the token-budget guard landed. **Every baseline in `eval/baselines/` was produced
against a collection today's code refuses to create.**

The irony is exact: **that fixture was authored to prove finding #19's
oversized-row path was reachable, and the guard built for #19 now refuses to
ingest it.**

Resolved by option 2, approved: `ingest: false` in the manifest — verified,
hashed and kept, never embedded. Option 3 (raise the boundary) was wrong: 2,048
is the model's real limit and raising it reinstates the silent truncation that is
finding #19 itself. Option 1 (split oversized rows at chunking) was **not**
taken, and is now filed as its own open question — it is a retrieval-quality
decision and is untestable until a corpus of real wide tables exists.

The proposal missed one thing: four golden entries depend on b04, so excluding it
without touching the golden set would have baked two guaranteed false abstentions
and one free correct-abstention into the reference baseline. `run_eval.py` now
drops entries whose required documents are not indexed, derived from the manifest.

The eval corpus now ingests from scratch: **17 chunks, 12 documents, 1 kept as a
fixture** — the first time this has ever succeeded on the shipping code.

### F4 — `up -d --wait` reports healthy before the system can serve · FIXED `9f821b3`

    docker compose up -d --wait   ->  exit 0, 7/7 "Healthy"
    ollama list                   ->  llama3.2:1b ABSENT
    any query                     ->  502, "404 ... /api/generate"

`--wait` waits for healthchecks; ollama's healthcheck is `ollama list`, which
passes as soon as the server answers, not when models exist. The documented
`ollama pull` steps mask it by blocking — but anyone trusting `--wait`,
scripting a deploy on health status, or restarting onto a fresh volume hits it.
Same shape as the `/ready` finding: a health signal reporting on the wrong thing.

### F5 — the generator-identity guard is a no-op during the pull window · FIXED `9f821b3`

    WARNING:core.model_identity:Ollama does not list model 'llama3.2:1b'; digest unknown.

Non-fatal by design, but it means that on a cold start the guard cannot compare a
digest it could not read — inactive during exactly the window when a fresh deploy
is most likely to have pulled something new. **A guard that passes because the
thing it checks is not loaded yet is presence-not-invocation in a new location.**

**Fix (shared with F4).** Readiness now includes model availability: the
healthcheck requires both models to be resident, using the same pair the
entrypoint already hardcodes, with `start_period` raised 30s → 900s so that a
cold ~1.6 GB pull is treated as *expected* rather than *broken*. Forced both
ways:

    model removed  -> "starting"  (never "healthy", so --wait BLOCKS)
    model restored -> "healthy"   (--wait returns)

The difference that matters: a user now sees the stack wait, instead of being
told it is ready and getting a 502 on the first question. The identity guard now
runs when a digest exists to read.

### Also recorded: no committed baseline is comparable any more

All four baselines in `eval/baselines/` predate the R4 provenance fields, so the
comparator now **refuses to diff** any of them against a current run:

    REFUSING TO DIFF — these baselines do not measure the same thing:
      n_answerable: old None -> new 15
      enable_ocr:   old None -> new True

That is correct — a baseline that never recorded its denominators cannot be shown
to measure the same population — but it meant the regression gate was
**configured, correct, and referenceless**.

**Closed.** Two reference baselines are now recorded (`d2c0185`), retrieval and
full, 46 provenance fields each with nothing `"unknown"` or `"unpinned"`. All
three comparator outcomes were forced against them — `COMPARABLE` on a repeat
run, `INCOMPARABLE` against a pre-R4 file, `FAIL` on a planted regression. The
first of those had never been run: a reference nobody has diffed is a reference
nobody has tested.

Recording them surfaced one more gap. A full-mode baseline pinned its generator
by `llama3.2:1b` — a **moving tag** — and nothing else, while `run_eval.py`
already read the digest and discarded it. `llm_model_digest` is now a hard field
in full mode (`17e8fd6`). Third instance of the class already on record: the
comparator only catches drift in fields someone thought to include.

---

## What could not be verified

- ~~**The eval from a clean clone**, blocked by F3.~~ **Now possible** — the
  corpus ingests from scratch (17 chunks / 12 documents) since `35ec4a2`.
- ~~**Full-mode eval.** Not run.~~ **Now recorded** as a reference baseline:
  2 runs, `ENABLE_ANSWER_CACHE=false`, generator pinned by digest, spread 0.000.
- **A genuinely cold Docker layer cache.** ~20 GB of layers; infeasible here.
- **First-run model pull times on a metered link.** Measured 1.5 s / 1.3 s,
  implausibly fast; a lower bound, not a general number.
- **Restart-under-load at a realistic ceiling.** At 1, most requests are rejected
  before the restart lands.

## Has anything changed since the audit's verdict?

**The verdict stands, with one clause now satisfied and one new caveat.**

The audit's verdict was: *the system works end to end on the shipping
configuration, and the shipping configuration cannot be obtained from the
repository.* The second half is now **false in the way that matters** — a clean
clone builds, serves, and answers, verified by doing it.

But F2 and F3 add a narrower version of the same shape: **the repository still
does not contain a working evaluation path.** A clean clone could not run the
eval at all (F2, fixed), and still cannot build the eval corpus from scratch
(F3, open). The system is reproducible; its instrument is not yet.

Everything the audit confirmed — failure and recovery, guard behaviour, the user
journey — survived twelve changes intact, including a starlette major. Retrieval
quality is unchanged by value. The three defects found were all in paths nobody
had run: a fence shape nobody had emitted, a checkout nobody had performed, and
a corpus ingest nobody had attempted.

**Gates at close:** ruff clean, mypy clean, **387 passed / 1 skipped**. Tree
clean, `0 0` against origin.
