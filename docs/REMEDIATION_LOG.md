# Remediation Log — KnowAll DocumentBot

Resumable worklog. Appended after every task. If you are picking this up cold,
read Section 0 first: it is the verified state of the world, not the audit's
claims.

---

# Section 0 — Phase 0: Re-verify & Orient (READ-ONLY, no code edited)

Date: 2026-07-14 · Branch: `dock_contain` · HEAD: `e7c92b4 Two options for running models`

## 0.1 Repository state — **blocking issue found**

`git log --oneline -30` shows 17 commits, the newest being `e7c92b4`, which is
the **pre-refactor Streamlit application**. `git status --short` reports 49
entries:

- `backend/`, `frontend/`, `docs/`, `.github/`, `infra/`, `pyproject.toml`,
  `.env.example` — all **untracked (`??`)**
- the entire old `app/` tree — staged as deleted, uncommitted
- `docker-compose.yml`, `.gitignore` — modified, uncommitted

**The entire current architecture is uncommitted.** There is no commit that
represents the system this log describes.

Consequence for R4 ("one logical change per commit; each commit green"): there
is nothing to diff against. A baseline commit must exist before any remediation
commit is meaningful. See PROPOSAL P-0 below.

## 0.2 Verified finding backlog

Verdict key: **CONFIRMED** · **ALREADY FIXED** · **INCORRECT — actual state is X** · **CHANGED — now Y**

| # | Sev | Finding | Audit location | Current location | Verdict |
|---|-----|---------|----------------|------------------|---------|
| 1 | P0 | No lockfiles; `npm ci` in CI vs `npm install` in Dockerfile | `ci.yml:52,56,130`; `frontend/Dockerfile:7` | **unchanged** — `ci.yml:52,56,130`; `frontend/Dockerfile:7`; no `package-lock.json`, no `requirements.in` | **CONFIRMED** |
| 2 | P1 | No `embed_model` in vector payloads | ingestion/helper/qdrant_store | grep for `embed_model` across all three → **0 hits** | **CONFIRMED** |
| 3 | P1 | No token counting before context assembly | `query.py:141-148` | **`query.py:141-148`, byte-identical** | **CONFIRMED** (now quantified — see 0.4) |
| 4 | P1 | Prompt injection via ingested content | `query.py:146` | **`query.py:146`** — `f"[{idx}] (Source: …)\n{chunk.text}"`, no delimiting | **CONFIRMED** |
| 5 | P1 | Citations never verified | `query.py:32-37` | `SYSTEM_PROMPT` at `query.py:32-37`; no parser anywhere | **CONFIRMED** |
| 6 | P2 | Port 8000 published while `trust_proxy_identity=True` | compose:188-189; config:132 | `docker-compose.yml:189` (`"8000:8000"`); `core/config.py:132` | **CONFIRMED** |
| 7 | P2 | Eval not in CI, no committed baseline | `ci.yml`; `eval/` | zero `run_eval` refs in `ci.yml`; `eval/` holds only `golden_set.json`, `run_eval.py` | **CONFIRMED** |
| 8 | P2 | Undeclared `requests` dependency | `embeddings.py:12` | **`embeddings.py:12`**; absent from `backend/api/requirements.txt` | **CONFIRMED** |
| 9 | P2 | Reindex path destructive + unreferenced | `qdrant_store.py:332-336` | `qdrant_store.py:332-337`; `grep '\.reset()'` → **0 callers** | **CONFIRMED** |
| 10 | P3 | Payload-index failures swallowed at DEBUG | `qdrant_store.py:122-123` | **`qdrant_store.py:122-123`** | **CONFIRMED** |
| 11 | P3 | Metadata fields written, never filtered | audit §B3 | 7 optional fields set in `helper.py:53-65` + 6 base fields at `:44-51`; only 3 indexed (`qdrant_store.py:114-116`) | **CONFIRMED** |
| 12 | P3 | `helm.py` unreachable; legacy notebook/bat | `options.py:28`; `tests/` | `options.py:12,28` registers HELM; `DocumentDashboard.tsx:14` ACCEPTED list omits `.helm`; `tests/test_documents.ipynb`, `tests/test_ingestion.bat` present | **CONFIRMED** |
| 13 | P3 | `ingestion.py` imports from `services/query.py` | `ingestion.py:16` | **`ingestion.py:16`** → `CORPUS_VERSION_KEY` (defined `query.py:28`) | **CONFIRMED** |
| 14 | — | mypy/ruff never verified to pass | `pyproject.toml` | Now measured: **ruff 105 errors**, **mypy 26 errors / 16 files** | **CONFIRMED** |
| 15 | — | Two `# type: ignore` lies | `query.py:71`; `main.py:61-62` | `query.py:71` **CONFIRMED**. `main.py:59-60` → mypy reports **`Unused "type: ignore" comment`** | **PARTIALLY INCORRECT** — see 0.3 |
| 16 | — | Golden set too small | `eval/golden_set.json` | 23 entries (21 answerable / 2 abstention) | **CONFIRMED** |
| 17 | — | No generation retry or fallback | `llm_clients.py` | only `except httpx.HTTPError → GenerationError` at `:73,:84,:108`; no retry, no fallback model | **CONFIRMED** |
| 18 | — | Weak `.env.example` defaults; `api_key=None` disables auth | `.env.example`; `config.py:124` | `config.py:124`; `.env.example:17,37,38,39,42` ship functional `*-change-me` values | **CONFIRMED** |
| 19 | ⚠️ | Ollama embedding truncation unknown | audit §B4 | **RESOLVED** — see 0.4 | **RESOLVED** |
| 20 | ⚠️ | HNSW effective params never asserted | `qdrant_store.py:144-148` | **RESOLVED** — see 0.4 | **RESOLVED** |

### New findings not in the audit

| # | Sev | Finding | Evidence |
|---|-----|---------|----------|
| **21** | **P0** | Entire current architecture is uncommitted; HEAD is the pre-refactor Streamlit app | `git log`, `git status --short` (49 entries) |
| **22** | **P1** | Host `frontend/node_modules` is polluted with **glibc** binaries (`lightningcss-linux-x64-gnu`) installed by the Playwright `jammy` image in a prior session. Any lockfile generated from this tree would bake in the wrong platform's optional deps | `ls frontend/node_modules` → `lightningcss-linux-x64-gnu`; alpine build fails against it, clean-room build succeeds |
| 23 | P3 | pytest in-container emits `PytestCacheWarning: Permission denied: /app/.pytest_cache` — the non-root `appuser` cannot write the cache dir | container pytest output |
| **24** | **P1** | `nomic-embed-text:latest` is a moving tag and Ollama cannot pull or run by digest, so drift is undetectable. Fixed by ASSERTION (`core/model_identity.py`), not by reference | `/api/tags`; `ollama pull ...@sha256:` → `invalid model name` | **RESOLVED** |
| **25** | **P2** | Base images pinned by tag and fastembed model repos unpinned — no build was reproducible, so no baseline was either | `api/Dockerfile`, `frontend/Dockerfile` | **RESOLVED** (`4e43c04`) |
| 26 | P3 | apt-installed tesseract and its traineddata are unpinned; an OCR output change would leave no diff in this repository | `api/Dockerfile` apt layer | **CLOSED** — vendored tessdata 4.1.0, checksummed, build-time gate, resolution and content verified |
| **27** | **P1** | `rerank_score_floor` is an absolute cut on a cross-encoder score whose scale tracks chunk SHAPE (prose vs table/list/OCR). Correctly-ranked first-place chunks are discarded and the user sees an abstention | tier-B baseline: `recall@fetch=1.0` vs `hit@k=0.318`, all 15 failures returned 0 chunks; 3/21 on the real corpus, all table/list answers | **OPEN** — P1 (promoted from P2: the entire quality gap is post-retrieval). Diagnostics done, PROPOSAL P-2 pending, no knob touched |
| **28** | **P1** | Query-rewrite fallback catches exceptions, empty output and length overruns but NOT semantic drift. A records-retention follow-up rewritten as a hazardous-waste question is fluent, correctly sized, and passes every guard | full-mode run 2026-08-04; 3-5 distinct rewrites per input over 10 calls | **FIXED** (`b6a6f00`) — embedding-similarity guard + per-entry instrumentation |
| **29** | P2 | csv, xlsx and pptx chunks carry no `section_title` at all, so section expansion degraded to a ±1 window and the reranker saw bare row-groups | 13/22 rank-1 chunks on tier B had no section metadata | **FIXED** (`64b9a35`) |
| **30** | P2 | `_expand_context()` runs AFTER the score floor, so enrichment can never influence the discard decision | `retrieval.py:182` floor vs `:188` expand | **PINNED, not fixed** (`414de43`) — the fix IS P-2 candidate C1 |
| **31** | **P1** | A cross-encoder scores TOPICAL RELEVANCE, not ANSWER PRESENCE. Near-miss unanswerable queries score 0.70-0.997 — higher than most correct answers — so no absolute score bar can separate "about your question" from "answers your question". The GENERATOR does not catch them either: 0 of 4, two fabrications with citations and two degenerate outputs | C3 run scores 0.6986 / 0.9557 / 0.9568 / 0.9968; full-mode generator test declined on 2/10, both being entries where retrieval returned nothing | **OPEN, P1 confirmed** — converges with #5 |
| **32** | P2 | Degenerate generation: the model emits citation markers and nothing else (`[1] [1][3]`), which is neither an answer nor an abstention and reaches the user as an empty answer bubble | F31 generator test: 2 of 4 near-misses | **OPEN** — fix in 2.4 alongside finding #5's citation verification |
| **33** | P2 | The abstention/concision rules cost real answers. Same 15 answerable questions: stripped 2-rule prompt answered **15/15**, the shipped 4-rule prompt **12/15** | ceiling control 2026-08-05 | **OPEN, FILED NOT FIXED** — changing the generation prompt needs R5 approval |
| **35** | **P1** | Abstention is detected by VERBATIM comparison against `NO_ANSWER_MESSAGE`. A model that declines in its own words keeps its citations attached, is counted as a non-abstention in telemetry, and is cached as an answer | `query.py:371,443`; measured on qwen3.5:4b — "The provided context does not specify what happens to an incident after it escalates…" | **OPEN** — filed, not fixed |
| **36** | P2 | Ollama caches the KV prefill, so a repeated or near-identical query costs far less than a novel one. Production latency therefore depends on query DIVERSITY, and it interacts with the answer cache: a query that misses the exact-match answer cache can still hit the prefix cache and return fast. Two caching layers, different hit conditions, neither instrumented for the other | ladder run 1 with a fixed prompt: 218.5s at concurrency 1 then 19.0s at concurrency 2 | **OPEN** — documented, not instrumented |
| **37** | **P1** | `max_concurrent_queries=20` admits ~3x what `llm_read_timeout=300` tolerates. Measured worst-case full-context latency crosses 300s at concurrency ~6-7, so requests past the crossing are admitted only to time out — strictly worse than the 503 + `Retry-After` the semaphore already produces | concurrency ladder, cache-defeated: 48.3 / 91.4 / 140.9 / 182.1s at 1-4 | **OPEN** — config-only fix, lands regardless of generator |

## 0.3 Finding 15 — correction

The audit asserted both `# type: ignore` comments were masking real type errors.
Only one is:

- `services/query.py:71` — `request: QueryRequest = field(default=None)  # type: ignore[assignment]` — **CONFIRMED**, a genuine lie (`None` assigned to a non-optional field).
- `api/main.py:59-60` — mypy reports these as **`Unused "type: ignore" comment`**. Mechanism: `app.state.container` is typed `Any` by Starlette, so attribute access is unchecked and no error is raised to suppress. **The underlying design gap is still real** — `get_sparse_model()` and `warm()` are not on the `VectorStore` / `Reranker` ABCs — but mypy cannot see it, so the audit's stated symptom is wrong. Fix in 1.2 is still warranted; the justification is interface hygiene, not a mypy failure.

Full `# type: ignore` inventory (13 total): `main.py:59,60`; `config.py:52,57,73` (pydantic `computed_field`, legitimate); `llm_clients.py:151,163,175` (OpenAI SDK message types); `ingestion.py:157`; `query.py:71`; plus 3 in tests.

## 0.4 Runtime unknowns resolved

Both required a running stack. All 7 services came up healthy
(`docker compose up -d --wait` → exit 0).

### F19 — Ollama embedding truncation: **silent truncation at 2048 tokens**

```
nomic-bert.context_length   = 2048
nomic-bert.embedding_length = 768
```
Empirical test via `/api/embed`:

| Input | Result |
|---|---|
| `"hello world "×10` (~120 chars) | 768-d vector |
| `"hello world "×2000` (~24 k chars) | 768-d vector |
| `"hello world "×40000` (~480 k chars) | 768-d vector, **HTTP 200, no error** |
| 480 k-char vs 24 k-char embedding | **identical** |

Ollama silently discards everything past the model's 2048-token window.

**Current exposure: none by default.** `chunk_size=550` tokens, and table chunks
are capped at `table_chunk_char_budget=1600` chars (~400 tokens). But this is
**unguarded**: raising `chunk_size` or `table_chunk_char_budget` past ~2048
tokens would silently truncate with no error. One real edge case survives — a
single table row wider than the char budget yields `max(1, …)` = one row
(`helper.py:18-21`), which could exceed the window if a single cell is huge.

### F20 — live Qdrant index parameters

```
dense  : size=768, distance=Cosine, on_disk=None
sparse : modifier=IDF
hnsw   : m=16, ef_construct=100, full_scan_threshold=10000,
         max_indexing_threads=0, on_disk=False, payload_m=None
quant  : scalar int8, quantile=0.99, always_ram=True
points : 376
```
Defaults confirmed (never set in repo). `ef` at search time is not set anywhere
— Qdrant's runtime default applies. This is the input Phase 3.1 needs.

## 0.5 Fact-sheet drift

**No drift.** Every value in the audit's `rag_fact_sheet.yaml` matches
`backend/core/config.py` as it stands: chunk 550/100, fetch_k 20, top_n 5,
floor 0.25, ctx_mode `section`, neighbor_window 1, parent_char_budget 4000,
num_ctx 8192, temp 0.1, num_predict 1024, models `nomic-embed-text:latest` /
`llama3.2:1b` / `BAAI/bge-reranker-base` / `Qdrant/bm25`, expansion count 2,
memory 5 turns, cache TTL 3600.

Two fact-sheet entries previously `UNKNOWN` are now filled (0.4).

## 0.6 Toolchain — true current state

| Gate | Command | Result |
|---|---|---|
| ruff | `ruff check backend` | ❌ **105 errors** (76 auto-fixable) |
| mypy | `mypy --config-file pyproject.toml` | ❌ **26 errors in 16 files** (29 checked) |
| pytest | `docker compose exec api pytest -q` | ✅ **53 passed**, 1 warning (F23) |
| next build | clean-room `npm install && npm run build` | ✅ **compiled successfully**, 8 routes |
| next build | against host `node_modules` | ❌ webpack/CSS failure — **environment artifact (F22)**, not a code defect |
| stack | `docker compose up -d --wait` | ✅ exit 0, 7/7 healthy |

**ruff breakdown:** UP035 ×21, UP006 ×21, UP045 ×16, B008 ×15, I001 ×11,
F401 ×5, UP007 ×4, W292 ×3, UP015 ×3, B905 ×3, UP041 ×1, UP017 ×1, F811 ×1.

Note: the 15 `B008` are `Depends(...)` in FastAPI signatures — idiomatic and a
known false positive for this rule; expect to configure an ignore rather than
rewrite the handlers (that is a config change, not a silencing of a real defect,
and will be justified in the 1.2 entry).

**mypy highlights** (full list in the run output):
- 7 × `extraction/*.py` — `list[Document]` vs `Sequence[ChunkLike]` override mismatch
- `query.py:252-254` — `trace` dict inferred too narrowly
- `llm_clients.py:180` — `ChatCompletion | AsyncStream` union not async-iterable
- `documents.py:101` — `SpooledTemporaryFile[bytes]` vs `BinaryIO`
- `base.py:48` — `list[BaseNode]` vs `list[Document]`
- `main.py:59,60` — unused ignores (F15)

## 0.7 Corpus state

Qdrant holds **376 points** in `knowall_collection`. Provenance is a prior
session's ingest of `backend/documents/` (gitignored, 12 files). This is
**not a reproducible baseline corpus** — Phase 1.4 must define one explicitly.

---

## PROPOSAL P-0 — establish a baseline commit (blocks R4)

**Status: PROPOSAL-PENDING**

**What it changes.** Commit the current tree (backend/, frontend/, docs/,
.github/, infra/, pyproject.toml, compose, .gitignore; stage the `app/`
deletion) as a single baseline commit, so subsequent remediation commits are
diffable and each can be verified green independently.

**Why.** R4 requires one logical change per commit with a green tree. With 49
uncommitted entries and HEAD pointing at a different architecture, no
remediation commit can be reviewed or reverted in isolation.

**Blast radius.** Repository history only. No runtime effect. `.env` stays
untracked (verified: `git ls-files .env` → empty; `.gitignore` contains `*.env`).

**Migration path.** `git add -A` excluding `.env` and `frontend/node_modules`
(both already ignored), one commit, e.g.
`chore: baseline enterprise architecture (pre-remediation)`.

**Rollback.** `git reset --soft HEAD~1` — the working tree is unchanged.

**Decision needed because** it is unusual to commit ~6 400 LOC in one commit,
and the alternative (reconstructing a phased history) would be fabrication. It
also cannot be green at commit time: ruff and mypy currently fail (0.6). Options:
(a) commit as-is and let 1.2 turn it green, or (b) do 1.2 first and commit once.
**Recommendation: (a)** — a baseline must record reality, including that the
gates were red.

---

## Phase 0 exit status

Read-only pass complete. **No files edited**; this log is the only artifact
created. 20/20 backlog findings adjudicated (17 CONFIRMED, 1 partially
incorrect, 2 previously-unknown now resolved), 3 new findings recorded, drift
list empty, toolchain state measured, both runtime unknowns settled with
evidence.

**Blocked on:** P-0 decision (baseline commit) before Phase 1 commits can
satisfy R4. Phase 1.1 additionally requires deleting the polluted host
`node_modules` (F22) before generating a lockfile — otherwise the lockfile
captures glibc-only optional dependencies.

---

# Section 1 — Phase 1: Restore the Safety Net

## Backlog amendments (directed by maintainer, 2026-07-14)

- **F19 re-graded ⚠️ → P1, moved to Phase 2**, merged with **F3** under a single
  shared token-counting utility enforced at BOTH boundaries: the 2048-token
  embedding window (F19) and the 8192-token generation context (F3).
- **F23 (P2) added** — `app.state.container` is typed `Any`, which disables type
  checking at every call site reached through it (this is also why the
  `main.py:59-60` ignores read as "unused" — see 0.3). Fix in 1.2 via a typed
  accessor.
- **F24** — renumbered from the F23 assigned in Section 0 (pytest cache
  permission warning), to free F23 for the maintainer's finding.
- **Phase 3 reordered**: `recall_at_fetch` measurement first; HNSW/`ef` tuning
  last and deferred until the corpus exceeds the indexing threshold.
- **1.4 blocked** until `eval/corpus/` is defined with checksums + manifest.

## [Phase 0.x] Baseline commit (PROPOSAL P-0 — APPROVED)
Status: DONE
Finding ref: #21 (verdict: CONFIRMED — entire architecture uncommitted)
Change: Tagged prior HEAD `pre-refactor-streamlit`; committed the current tree
as one untested snapshot; hardened `.gitignore`.
Files: `.gitignore`, 143 staged paths
Evidence: `git log` → `0bf2874`; `git status --short` → 0 entries (clean tree);
`git check-ignore` verified for `.env`, `node_modules/**`, `.pytest_cache/**`,
`documents/**`, `*.onnx`, `*.safetensors`; `.env.example` explicitly un-ignored.
Commit: `0bf2874 chore: baseline enterprise architecture snapshot (UNTESTED)`
Notes: Two surprises during the `git add -An` review, both reported before
committing:
  1. `.gitignore` did **not** cover `.pytest_cache` (it was only self-ignored by
     pytest's own generated `.gitignore`) nor any model-weight pattern. Both added.
  2. A `frontend/package-lock.json` **existed**, created by my own Phase 0
     `npm install` inside a glibc container. It contained gnu-only
     `lightningcss`/`oxide` entries (77 packages). Deleted together with
     `node_modules` and regenerated in 1.1.
Gates at commit time were RED by design (ruff 105 / mypy 26); 1.2 turns them green.

## [Phase 1.1] Lockfiles
Status: DONE
Finding ref: #1 (verdict: CONFIRMED), #22 (verdict: CONFIRMED)
Change: Generated platform-complete `frontend/package-lock.json` and a
hash-pinned `backend/api/requirements.txt` compiled from a new
`requirements.in`; switched the frontend Dockerfile to `npm ci`.
Files: `frontend/package-lock.json` (new), `frontend/Dockerfile:1-11`,
`backend/api/requirements.in` (renamed from requirements.txt),
`backend/api/requirements.txt` (now generated)
Evidence:
  - Lockfile generated in `node:22-alpine` via `npm install --package-lock-only`
    (no node_modules materialized). **127 packages**, and platform coverage
    verified to include BOTH variants for every native dep:
    `lightningcss-linux-x64-{gnu,musl}`, `@tailwindcss/oxide-linux-x64-{gnu,musl}`,
    `@next/swc-linux-x64-{gnu,musl}`. The polluted lockfile had 77 packages and
    gnu-only entries.
  - `docker compose build web` → `npm ci` → `added 74 packages in 32s` →
    `✓ Compiled successfully in 7.0s`. **This is the first time `npm ci` has
    ever succeeded in this repo.**
  - `uv pip compile api/requirements.in --generate-hashes` → **124 pinned
    packages, 2703 hashes**.
  - `docker compose build api` → `Successfully installed …` (124 packages)
    under pip's implicit `--require-hashes`. BUILD_OK.
  - `docker compose up -d --wait` → 7/7 healthy on the new images.
Eval: n/a (no retrieval behavior touched)
Commit: see below
Notes:
  - CI `cache-dependency-path` values (`frontend/package-lock.json`,
    `backend/api/requirements.txt`) now both resolve to real files.
  - The compiled lockfile pins `requests==2.34.2` transitively, but F8 still
    stands: `integrations/embeddings.py:12` imports it as a **direct**
    dependency without declaring it. 1.3 addresses that.
  - `tiktoken==0.13.0` arrives transitively via llama-index-core — available
    for Phase 2.2, though llama3.2 does not use a tiktoken BPE (see 2.2).
  - **Deviation from R4 acknowledged:** this commit does not leave ruff/mypy
    green, because it precedes 1.2 by design. Recorded rather than hidden.

## [Phase 3 gate] Corpus scale measured (directed)
Status: DONE (measurement only)
Change: none — read-only verification.
Evidence: live Qdrant `knowall_collection`:
```
points_count          : 376
indexed_vectors_count : 372
full_scan_threshold   : 10000   (KB, Qdrant default)
segments status       : green
hnsw                  : m=16 ef_construct=100 on_disk=False
```
372 × 768 dims × 4 B ≈ **1.1 MB**, far below the 10 000 KB full-scan threshold.
**Conclusion: HNSW/`ef` tuning is not measurable at this corpus size** — Qdrant
prefers full scan for segments under the threshold, so `m`/`ef_construct`/`ef`
changes would produce no observable delta. Phase 3.1 (HNSW) should stay deferred
until the corpus exceeds the threshold by a wide margin; `recall_at_fetch` is
the correct first measurement.

## [Phase 1.2] Make ruff, mypy and pytest pass
Status: DONE
Finding ref: #14 (CONFIRMED), #15 (PARTIALLY INCORRECT — see 0.3), #23 (CONFIRMED)
Change: Configured bugbear for FastAPI's dependency idiom, applied ruff
autofixes, and resolved all 26 mypy errors without adding a single new
`# type: ignore`.
Files: `pyproject.toml`, `core/interfaces.py`, `api/dependencies.py`,
`api/main.py`, `integrations/{qdrant_store,reranker,cache_stores,object_storage,llm_clients}.py`,
`extraction/{base,helper,options,pdf,pptx}.py`, `services/{query,ingestion,retrieval}.py`,
plus 19 files touched by autofix
Evidence:
```
ruff check backend      →  All checks passed!          (was 105 errors)
mypy --config-file …    →  Success: no issues found in 29 source files   (was 26 errors / 16 files)
pytest -q (container)   →  53 passed                   (unchanged — no behavior change)
docker compose build    →  BUILD_OK; 7/7 healthy
```
Eval: n/a — no retrieval/generation behavior touched (R2: the evidence here is
the three gates flipping red→green with tests unchanged).
Commit: see below
Notes — decisions worth knowing:
  - **B008 was NOT ignored.** `flake8-bugbear.extend-immutable-calls` declares
    `fastapi.Depends/File/Header/Body/Query/Path/Form` immutable. A blanket
    `ignore = ["B008"]` would also have hidden real mutable-default bugs.
  - **B905 (3 × `zip()` without `strict=`) was fixed, not suppressed**, and the
    fix *strengthens* an invariant: `qdrant_store.upsert`, `ingestion._embed_chunks`
    and `retrieval._rerank_pool` all zip sequences that must be equal length.
    `strict=True` turns a silent misalignment into a loud `ValueError` — the
    same class of defect the text↔vector alignment guard exists for (R6).
  - **F23 fixed** — `api/dependencies.container_from_app()` is a typed accessor
    with an `isinstance` gate. This is the root cause of the "unused ignore"
    puzzle in 0.3: `app.state.container` was `Any`, so nothing downstream of it
    was checked.
  - **The `# type: ignore[attr-defined]` pair in main.py is gone for the right
    reason.** A `Warmable` mixin now declares `warm()` on the `VectorStore` and
    `Reranker` interfaces (default no-op); `QdrantVectorStore.warm()` loads the
    BM25 model. The lifespan calls a typed contract instead of an `Any` lookup.
  - **`ChunkLike` is now a read-only Protocol.** Root cause of the 7 extractor
    override errors: llama_index exposes `text` as a property, which cannot
    satisfy a mutable-attribute Protocol. Verified at runtime that `Document`
    and `TextNode` share **no** nominal supertype carrying `.text`
    (`Document.__mro__` = Document → Node → BaseNode; `BaseNode` has no `text`
    field), so the structural Protocol is the only accurate annotation — this
    is exactly what it was introduced for. Consumers only read `.text` and
    mutate the dict returned by `.metadata`, so read-only is truthful.
  - `# type: ignore` count: 13 → 10, and the 3 removed were the misleading ones.
    The remainder are pydantic `computed_field` (3) and OpenAI SDK message
    types (3), both third-party stub limitations, plus 3 in tests and 1 in
    `ingestion.py:157`.
  - F24 (pytest cache permission warning) still present; cosmetic, deferred.

## [Phase 1.3] Port embeddings.py off `requests` to httpx
Status: DONE
Finding ref: #8 (verdict: CONFIRMED)
Change: Replaced the undeclared `requests` dependency with the pooled
`httpx.Client` the rest of the service already uses.
Files: `integrations/embeddings.py:7-12,60-70,78-90`, `tests/test_embedding.py`
Evidence:
```
grep -rn "^import requests" backend  →  no matches
ruff / mypy                          →  clean
pytest -q (container)                →  53 passed
python tests/test_embedding.py       →  200, 2 embeddings, dim=768   (live)
```
Eval: n/a — same endpoint, same payload, same prefixes.
Commit: see below
Notes: chose the port over declaring the dependency (maintainer preference:
one HTTP stack). The client is now instance-scoped and pooled rather than
`requests.post` opening a fresh connection per batch. Timeout made explicit
(connect 5 / read 120 / write 30 / pool 5) instead of a bare `timeout=120`.


## [Phase 1.4a] Corpus infrastructure + tier B
Status: DONE (tier B only - tier A blocked, see PROPOSAL P-1)
Change: Added eval/corpus/ with a manifest contract, an integrity gate, and 12
synthetic tier-B documents covering every extractor path.
Files: eval/corpus/MANIFEST.yaml, eval/corpus/verify.py,
eval/corpus/generate_tier_b.py, eval/corpus/tier-b/ (12 files)
Evidence:
    verify.py      -> corpus OK: 12 documents verified (tier b: 12)
                      manifest_sha256: 307e5d3b2060a9fd0cc5087a900f5a37a76d1d0c3f58dce4937ee0ebc27972e8
    negative test  -> append 1 byte to b01 -> CORPUS VERIFICATION FAILED, exit 1
Coverage (tier B): txt, md, csv, oversized-single-row csv, xlsx (multi-sheet),
docx (headings + in-position table), pptx, pdf (text layer), pdf (image-only ->
OCR path), plus 3 topical distractors with no answers.

b04-wide-row.csv is the one that matters most: a ~13,000-char single row.
dynamic_rows_per_chunk clamps with max(1, ...) (helper.py:18-21), so the row
bypasses table_chunk_char_budget entirely, and finding #19's 2048-token
embedding window then silently drops its tail. This turns that from a
theoretical defect into a measurable one.

Notes - A CLAIM I MADE AND THEN DISPROVED:
  I asserted the generator was byte-deterministic. It is not. Measured by
  running it twice and diffing:
      byte-identical : .txt .md .csv .docx .pptx  (zip mtime normalisation works)
      NOT identical  : .xlsx .pdf
  openpyxl and PyMuPDF embed time-varying state that survived pinned docProps
  timestamps and pinned CreationDate, ModDate and ID. I stopped chasing it
  because byte-stable REGENERATION is not what protects a baseline - pinning the
  COMMITTED bytes is, which the manifest + verify.py do. The module docstring
  now states the measured behaviour rather than the intent.

## PROPOSAL P-1 - tier A cannot be populated by me
Status: PROPOSAL-PENDING (blocks 1.4 baseline, 1.5 golden set, 1.6 CI gate)

What is blocked. Tier A is specified as REAL bilingual EN/FR parallel documents
(Government of Canada, EU) with per-file license, source_url and retrieved
provenance. I cannot produce it:

 1. I cannot fetch them. No network retrieval of arbitrary URLs is available to
    me, and the instruction correctly rules out a fetch script.
 2. I must not substitute backend/documents/. It is gitignored and contains
    third-party copyrighted material - ABC DELF junior A2.pdf is a commercial
    language-exam textbook. Committing it would be a licensing violation, and I
    could not write truthful license/source_url/retrieved fields for any file in
    that directory.
 3. I will not author fake provenance. Synthesising Government of Canada
    documents and labelling them with a gc.ca source_url would fabricate exactly
    the evidence this engagement exists to establish.

Options (maintainer decision required):
  A. You supply tier A - drop real bilingual PDFs/DOCX into eval/corpus/tier-a/
     with licence + URL + date; I write the manifest entries, checksums and
     matched question pairs. Meets the spec exactly. PREFERRED.
  B. I author synthetic EN/FR parallel documents, labelled license CC0-1.0,
     source_url generated, tier a-synthetic. Removes the language/difficulty
     confound (genuinely parallel content), but the headline baseline then
     measures a synthetic corpus. Honest labelling, weaker claim.
  C. Public-domain text reproduced from memory. Provenance unverifiable and
     reproduction may be imperfect - NOT RECOMMENDED.

Blast radius. Without tier A there is no headline baseline, so 1.5's golden set
has no real documents to draw >=60 entries from, and 1.6's regression tolerance
has no variance to measure. Tier B alone is adversarial by design and would
produce a misleading headline.
Rollback. None needed - nothing committed presumes tier A.
What would settle it: your choice of A or B. If A, I need only the files plus
their licence, URL and date.

## F24 - the prescribed fix is NOT ACHIEVABLE (counter-proposal)
Status: PROPOSAL-PENDING
Finding ref: #24 (P1) - unpinned nomic-embed-text:latest

Measured, not assumed:
    /api/tags  -> nomic-embed-text:latest
                  sha256:0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f
               -> llama3.2:1b
                  sha256:baf6a787fdffd633537aa2eb51cfd54cb93ff08e28040095462bb63daf552878
    /api/show  -> NO digest field at all
    ollama pull nomic-embed-text@sha256:0a109f422b47  ->  Error: invalid model name

Ollama 0.9.3 cannot pull or run a model by digest. name:tag is the only
reference form, so pin-to-a-digest cannot be implemented as written.

Counter-proposal - pin by ASSERTION instead of by reference. The harm in F24 is
not that the tag can move; it is that it can move UNDETECTABLY. That is fixable:
 1. Add expected_embed_model_digest to settings.
 2. On startup and at the top of every eval run, query /api/tags, compare, and
    FAIL LOUDLY on mismatch instead of embedding with a silently different model.
 3. Record the digest in the baseline provenance tuple, so a baseline produced
    under a republished model can never be silently diffed against an older one.
 4. Combined with F2 (embed_model in the payload), a drifted model becomes
    detectable at ingest, at query time and at eval time.

This delivers F24's actual requirement - zero silent drift - without depending on
a capability Ollama does not have. Needs approval because it changes startup
behaviour from permissive to fail-closed.


## [Phase 2.1-pre / F24] Embedding-model identity enforcement
Status: DONE
Finding ref: #24 (P1) - verdict CONFIRMED; prescribed fix NOT ACHIEVABLE,
maintainer approved the counter-proposal (pin by assertion).
Change: New core/model_identity.py enforces embedding-model identity at three
points with one shared policy; ModelIdentityError added; digest wired through
config, compose and .env.example.
Files: core/model_identity.py (new), core/exceptions.py:25-32,
core/config.py:50-55, api/main.py:16,56-60, worker.py:33,148-150,
eval/run_eval.py:head, docker-compose.yml (api + worker), .env.example,
tests/unit/test_model_identity.py (new, 8 tests)

Semantics implemented exactly as directed:
    digest mismatch            -> HARD FAIL (api startup, worker startup, eval head)
    expected unset             -> loud WARNING, never a failure
    Ollama unreachable         -> NOT a mismatch; defers to the existing
                                  readiness path, no duplicated liveness check
    no dev escape-hatch env var
    OpenAI backend exempt (immutable model names, no moving tag)

Built for 2.1 to EXTEND, not to be replaced: verify_three_way() already
implements config vs. live Ollama vs. payload digest. 2.1 only has to pass the
stored value in. Documented as NOT retroactive - the 372 existing points carry
no digest, so stored_digest=None is "unknown", not "mismatch"; three-way becomes
authoritative from the first reindex forward.

Evidence:
    pytest                     -> 60 passed (was 53; 8 new minus overlap)
    unset digest               -> WARNING "...drift is UNDETECTABLE...", api healthy
    WRONG digest (deadbeef...) -> ModelIdentityError: Embedding model identity
                                  mismatch at api startup
                                  ERROR: Application startup failed. Exiting.
    CORRECT digest             -> [api startup] identity verified ... @ 0a109f422b47...
                                  [worker startup] identity verified ... @ 0a109f422b47...

METHODOLOGY CORRECTION (recorded because the first run proved nothing):
  My initial live test set EXPECTED_EMBED_MODEL_DIGEST in the SHELL and
  concluded "healthy = pass". That was invalid: compose reads container env
  from the per-service `environment:` map, and shell variables only feed
  ${VAR} interpolation. The variable never reached the container, so the API
  was still running the unset-warning path. Fixed by adding
  EXPECTED_EMBED_MODEL_DIGEST to BOTH the api and worker environment maps, then
  re-running. Only the second run is evidence.

  Second correction: Ollama /api/tags returns a BARE HEX digest with no
  "sha256:" prefix. My earlier report wrote it prefixed - that was my own
  formatting, not the wire value. .env.example now states the format explicitly
  and includes the one-liner to read the live value.


## [Phase 1.6-pre / F25] Build reproducibility — base images and model revisions
Status: DONE
Finding ref: #25 (P2) — no HF revision pin; unpinned base images; unpinned apt
Commit: `4e43c04 build(f25): pin base images by digest and assert HF model revisions`

Two unpinned inputs made every eval baseline unreproducible:

1. **Base images by tag.** `python:3.12-slim` and `node:22-alpine` are
   republished on every security refresh. Both Dockerfiles now pin by sha256
   digest (tag retained in a comment for readability):

       python  sha256:401f6e1a67dad31a1bd78e9ad22d0ee0a3b52154e6bd30e90be696bb6a3d7461
       node    sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2

   Verified against `docker images --digests`: these are the digests actually
   resolved for the local `python:3.12-slim` / `node:22-alpine` tags.

2. **fastembed repositories by name only.** `Qdrant/bm25` and
   `BAAI/bge-reranker-base` resolved to whatever the default branch was at
   build time. A reranker weight change moves every rerank score, and therefore
   every eval number, with **no diff in this repository**. Pinned to
   `e499a1f8d6bec960aab5533a0941bf914e70faf9` and
   `2cfc18c9415c912f9d8155881c133215df768a70`.

### FAILED APPROACH (recorded so it is not retried)

`HF_HUB_OFFLINE=1` as the enforcement mechanism **does not work**. fastembed
does not resolve models through the plain `huggingface_hub` cache layout; with
offline mode set the constructor fails outright:

    ValueError: Could not load model Qdrant/bm25 from any source

An earlier note in this log claimed "the pins worked — snapshot dirs match".
That claim was **WRONG**: the directories matched because those SHAs happen to
*be* current `main`. A check that passes for the wrong reason is not a check.
Replaced with a post-hoc assertion.

### The mechanism actually shipped

`api/Dockerfile` runs three steps in one layer:

    1. snapshot_download() the exact commits into the HF cache
    2. run the fastembed constructors (they populate the cache themselves)
    3. run api/verify_model_pins.py — FAILS THE BUILD on any deviation

`verify_model_pins.py` requires the pinned snapshot to be the **sole** cached
snapshot. Checking only that it *exists* is vacuous: step 1 guarantees that on
its own. If fastembed then resolved the default branch to a newer commit, that
commit would sit alongside as a **second** snapshot and be the one actually
loaded — while a presence-only check passed cleanly. This weakness was found by
testing the verifier, not by reading it.

### Verifier tested in BOTH directions before being trusted (as directed)

    POSITIVE  correct pins
              -> "model revision verified: models--Qdrant--bm25 @ e499a1f8...
                  (sole cached snapshot)"
                 "model revision verified: models--BAAI--bge-reranker-base @
                  2cfc18c9... (sole cached snapshot)"
              -> exit 0

    NEGATIVE  wrong pin (BM25 revision set to a different valid-looking commit)
              -> "MODEL REVISION PIN VIOLATED"
                 "  models--Qdrant--bm25: pinned 1111... not cached;
                    present=['e499a1f8...']"
              -> exit 1

    NEGATIVE  simulated second snapshot (fastembed resolved something else)
              -> "MODEL REVISION PIN VIOLATED"
                 "  models--Qdrant--bm25: 2 snapshots cached
                    ['deadbeef...','e499a1f8...']; expected only the pinned
                    e499a1f8.... fastembed resolved a revision other than the pin."
              -> exit 1

Re-run against the **shipped** images (mounting the script into
`knowall-documentbot-api` and `knowall-documentbot-worker`): both exit 0, both
report the sole cached snapshot. That is artifact-level proof, stronger than a
build-log line.

### Provenance recording — and the silent bug in the first attempt

The revisions are baked into the image as `KNOWALL_BM25_REVISION` /
`KNOWALL_RERANKER_REVISION` so a running container reports what it actually
holds into the baseline provenance tuple.

The env names deliberately differ from the ARG names. Docker resolves a
self-referencing `ENV FOO=${FOO}` against a same-named `ARG FOO` to the **empty
string**. The first attempt therefore recorded `reranker_revision: "unpinned"`
in provenance while the download itself was correctly pinned — a green build
that lied. Confirmed fixed by `docker inspect` **and** `printenv` inside a
running container of both images: both variables non-empty and correct.

### Also recorded

- Embedded newlines in a `RUN python -c "..."` broke the Dockerfile parse
  (`unknown instruction:`). The verifier lives in a real script file, COPY'd in
  and `rm`'d after use.
- **Not covered:** apt-installed `tesseract-ocr` / `tesseract-ocr-fra` and
  their traineddata remain unpinned. A traineddata change would move OCR output
  with no diff here. Logged as **F26 (P3, Phase 4)** and documented inline in
  the Dockerfile; agreed fix is to vendor `eng.traineddata` / `fra.traineddata`
  from a tagged tessdata release, checksummed in a manifest, COPY'd in with
  `TESSDATA_PREFIX` set. `snapshot.debian.org` was explicitly ruled out.
  Phase 1 is **not** blocked on it.

Gates: ruff clean · mypy 31 files clean · pytest 60 passed (in-container).


## [Phase 1.6-pre] Provenance tuple + four-outcome comparator
Status: DONE
Commit: `0acb69a feat(eval): add provenance tuple and four-outcome baseline comparator`
Files: `eval/provenance.py` (new), `eval/compare.py` (new),
`tests/unit/test_eval_comparator.py` (new, 36 tests)

The failure mode a comparator exists to prevent is not a missing number — it is
a **real number read as a result when it is a different measurement**. So the
comparator's primary job is to refuse.

Four outcomes:

| Outcome | Trigger | Behaviour |
|---|---|---|
| `COMPARABLE` | nothing drifted | diff the numbers |
| `COMPARABLE_WITH_COSMETIC_DRIFT` | git sha, api/web image digest, bm25/reranker revision | named in the output; no expected retrieval effect |
| `COMPARABLE_WITH_SEMANTIC_DRIFT` | `retrieval_fetch_k`, `rerank_top_n`, `rerank_score_floor`, `retrieval_context_mode`, `neighbor_window`, `parent_char_budget`, `enable_multi_query`, `query_expansion_count`, `enable_answer_cache`, `reranker_model` | metrics ARE printed, prefixed with a warning naming every drifted knob. Not a refusal — comparing across a knob sweep is what a sweep is for |
| `INCOMPARABLE` | `corpus_manifest_sha256`, `embed_model`, `embed_model_digest`, `chunk_size`, `chunk_overlap`, `table_chunk_char_budget`, `table_max_rows_per_chunk`, `eval_mode` | **hard refusal, exit 2, no metrics printed at all** |

`eval_mode` is in the hard set (as directed): retrieval-mode numbers
(deterministic, no LLM) and full-mode numbers (rewrite + expansion in the loop)
are not the same quantity.

**`llm_model` is conditional on `eval_mode`** (as directed):

- **full mode → HARD.** The generation model drives query rewrite and
  multi-query expansion, so it changes retrieval *inputs*. A different model is
  a different system, not drift.
- **retrieval mode → COSMETIC.** The LLM never runs; its identity cannot have
  moved a single retrieval number.

`classify_fields(eval_mode)` owns that split and is the single source of truth;
`fingerprint()` hashes only the mode-appropriate hard fields. When two baselines
disagree on mode the comparator takes the stricter reading — though `eval_mode`
being hard means such a pair is already `INCOMPARABLE`.

Metrics are compared **per tier**. Tier A and tier B are never averaged; a test
pins that a tier A collapse (0.90 → 0.60) is not masked by a tier B gain
(0.40 → 0.90).

Exit codes: `0` within tolerance · `1` regression · `2` incomparable.

Test coverage that matters: every hard field individually forces refusal; every
semantic field individually forces the semantic verdict; precedence
(hard > semantic > cosmetic) is pinned; `INCOMPARABLE` is asserted to print
**no** metric text even when the delta is 0.90 → 0.10; the field classes are
asserted disjoint in both modes.

Gates: ruff clean · mypy clean · pytest **96 passed** (was 60).


## [defect found while re-greening] Env leakage into the model-identity tests
Status: DONE
Commit: `ad1470a fix(tests): pin model-identity settings against os.environ leakage`

Self-inflicted, and worth recording because it is the same class of error as the
two above. The F24 live proof added `EXPECTED_EMBED_MODEL_DIGEST` to the api and
worker `environment:` maps. `Settings(_env_file=None)` skips the dotenv file but
**still reads `os.environ`**, so from that commit onward the in-container run of
`test_unset_expectation_warns_but_does_not_fail` was exercising the *set* path
and failing with `ModelIdentityError`.

The export is the F24 enforcement mechanism and stays. The test helper now sets
`expected_embed_model_digest` and `use_openai_embedding` explicitly (overridable
per test) so each case runs the state it names.

    before -> 1 failed, 59 passed
    after  -> 60 passed

Four mechanisms this session looked like they worked and did not: the compose
shell-env F24 test, the `HF_HUB_OFFLINE` pin, the `ENV FOO=${FOO}` recording,
and this. Every one was caught by testing the check itself rather than the thing
it checks.


## [Phase 1.6] Two-mode harness, tier-B golden set, scripted corpus ingestion
Status: DONE
Commits: `7009a9c test(eval)` · `d63c917 feat(eval)` · `8ba24ea feat(eval)`

### Harness (`eval/run_eval.py`, rewritten)

Two modes, structured as the maintainer directed — two CI jobs, not one flag:

| | retrieval | full |
|---|---|---|
| path | `RetrievalService` directly | `QueryService.prepare()` |
| LLM in the loop | none at all | rewrite + multi-query expansion |
| determinism | total | not deterministic |
| tolerance | **zero** | **measured** (`--runs N`) |
| when | every PR touching `extraction/`, `services/`, `integrations/`, `core/config.py` | nightly, and before merging changes to `query.py` / `retrieval.py` |

Full mode **refuses to start** with `ENABLE_ANSWER_CACHE=true`. Runs 2..N would
be served from Redis and report a variance that is a property of the cache, not
of the system. Unit-tested in both directions.

History is seeded into real `SessionMemory` rather than passed in, so the code
path exercised is production's.

Three gates run before any query: corpus manifest verification, embedding-model
identity, and the cache check. Each one, skipped, produces numbers that look
fine and mean nothing.

Reporting is **per tier**, never averaged. Diagnostic slices (category,
language, lexical overlap) are recorded and printed but not gated; the
comparator gates tiers.

The lexical-overlap slice is computed from the golden file's `answer_snippet`,
not from retrieval output, so the slice is a stable property of the question.

Every row records the `needs_rewrite()` verdict; entries carrying
`expects_rewrite` are asserted against it and a mismatch **fails the run**.

### Golden set (`eval/golden_set.json`, 25 entries, tier B)

The previous 23 entries targeted the ad-hoc `documents/` folder — no manifest,
no checksums, not in version control. Numbers from them are not reproducible, so
they cannot back a baseline. Moved to `golden_set.legacy.json` with a `_status`
header, not deleted, so nobody re-adopts them by accident.

New schema fields: `tier`, `category`, `answer_snippet` (verbatim source text),
`history`, `expects_rewrite`.

    plain-fact 4 · table-answer 3 · long-table-tail 2 · ocr-answer 2
    multi-hop 1 · cross-doc 1 · conversational 9 · unanswerable 3
    18 en / 7 fr · 22 answerable / 3 unanswerable

**Lexical-overlap rule met and enforced:** 16/22 answerable entries (73%) share
under a third of their content words with the text that answers them, against
the 40% floor. A unit test fails if it ever drops below 40%.

**All four `needs_rewrite()` branches covered, in both languages** (as directed):

| branch | entries | note |
|---|---|---|
| 1 · no history → skip | en, fr | the EN one deliberately contains "it"; branch order must beat the regex |
| 2 · ≤6 words → short-circuit | en, fr | |
| 3 · anaphora, long → fire | en, fr, +1 | the extra is French `faut-il`, a true positive that reads like a false one |
| 4 · long, no anaphora → **must skip** | en, fr | where a widened regex over-triggers first, and it over-triggers in one language before the other |

The French branch-4 entry also pins word-boundary behaviour: `Quelle` contains
`elle` and must not match `\belle\b`. Separately unit-tested.

### Corpus ingestion (`eval/ingest_corpus.py`)

Refuses to run against the default collection — that one holds real user
documents, and mixing the corpus in would put unmanifested content in every
candidate pool. Verified: exit 2 with that message.

The etag is the manifest's own sha256, so `uuid5(source:etag:chunk_seq)` point
IDs become a pure function of the corpus definition. 13 documents → 18 chunks in
`knowall_eval`; the production collection's 376 points were not touched.

Gates: ruff clean · mypy 31 files clean · pytest **123 passed** (was 96).


## [Phase 1.6] Tier-B diagnostic baseline — and what it found
Status: DONE (diagnostic, NOT a reference baseline — see the provenance caveat)

    retrieval mode, k=5, 3 runs, knowall_eval, manifest 32610e3d...

    [tier_b]  n_answerable=22  n_abstention=3
              recall_at_fetch = 1.000
              hit_at_k        = 0.318
              mrr_at_k        = 0.318
              abstention_acc  = 1.000

    variance across 3 runs: spread 0.0 on EVERY metric.

**Determinism confirmed empirically.** Retrieval mode is byte-stable across
three runs, which is what makes a zero CI tolerance defensible rather than
optimistic. Full-mode variance still has to be measured separately.

### The number that matters is not hit@k — it is the gap

`recall_at_fetch = 1.0` with `hit_at_k = 0.318`. Retrieval finds the right chunk
for **every** answerable question. All 15 failures returned **zero** chunks: the
rerank score floor discarded them.

Measured directly rather than inferred (top-3 rerank scores, floor = 0.25):

    0.1602  b01-policy-notes.txt   <- correct   "How long must files be kept..."
    0.0028  b02-handbook.md
    0.0008  b06-operations.docx

    0.2101  b03-sales.csv          <- correct   "What revenue did West record in Q4?"
    0.0004  b07-review.pptx
    0.0003  b04-wide-row.csv

    0.0112  b09-scanned-notice.pdf <- correct   "maximum award under the heritage programme"
    0.0012  b04-wide-row.csv

    0.4475  b04-wide-row.csv       <- correct, and ABOVE the floor

The correct document ranks **first in every case**, by two to three orders of
magnitude. The ranking signal is excellent. What fails is the absolute cut.

### I checked the obvious over-reading before writing it down

"The floor is miscalibrated" would have been the wrong conclusion from tier B
alone. Ran the same probe against the **real 376-point collection** using the
retired golden set:

    3 / 21 real-corpus questions fall below the floor
    prose questions          0.66 - 0.99   comfortably above
    the three that fail      0.014, 0.014, 0.078
                             — French vocabulary table, French vocabulary
                               table, CSV column list

So the floor is not globally wrong. The pattern is **chunk shape**: the
cross-encoder scores prose in the 0.65–0.99 band and table / list / OCR content
in the 0.01–0.21 band, largely independent of whether the chunk actually
answers. Tier B is almost entirely table, spreadsheet, list and OCR content,
which is why it looks catastrophic there and mild on the real corpus. Same
defect, different exposure.

### `abstention_accuracy = 1.000` is unearned

Recorded explicitly because it is the same defect seen from the other side. The
system abstained on 15 of 22 answerable questions; scoring 3/3 on the
unanswerable ones says nothing about abstention behaviour. Read alone it is a
green checkmark that lies.

### PROVENANCE CAVEAT — why this is not the reference baseline

The recorded tuple contains:

    reranker_revision : "unpinned"      bm25_revision : "unpinned"
    git_sha           : "unknown"       api_image_digest : "unknown"

Honest, and the mechanism working as designed: the **running container** was
created from an image built before the `KNOWALL_*` env fix, and the eval code
was `docker compose cp`'d into it. The container genuinely does not hold those
values, and provenance reported exactly that instead of inventing them.

Consequence: this baseline is a **diagnostic**, recorded to prove the harness
works and to surface F27. It is not a comparison point. A reference baseline
needs (a) containers recreated from the rebuilt image and (b) tier A, which does
not exist yet.


## F27 (NEW, P2) — rerank score floor is an absolute cut on a shape-dependent score
Status: PROPOSAL-PENDING — no knob touched (R3, R5)
Evidence: `eval/baselines/tier-b-retrieval-2026-08-03.json` + the two probes above

`rerank_score_floor = 0.25` is applied as an absolute threshold to a
cross-encoder sigmoid score whose scale depends on the **shape** of the chunk
(prose vs table / list / OCR), not only on relevance. Correctly-ranked
first-place chunks are discarded, and the user sees an abstention.

Blast radius on the real corpus today: 3 of 21 golden questions — every one of
them a table or list answer. On tier B: 15 of 22.

Not fixed here. R3 freezes retrieval quality until it is measurable; it is
measurable now, but the fix is a semantic knob and belongs in a proposal with a
before/after delta, which the comparator will correctly label
`COMPARABLE_WITH_SEMANTIC_DRIFT`.

Candidate directions, in the order I would test them, none implemented:

1. **Relative floor.** Keep the top result whenever it leads the runner-up by a
   wide margin, regardless of absolute score. Fits the measurement: the winning
   gap is 2–3 orders of magnitude in every failing case.
2. **Floor by chunk shape.** The payload already carries enough to tell a table
   chunk from a prose chunk. Two thresholds instead of one.
3. **Lower the single floor.** Simplest, and the one most likely to trade a
   real gain in hit@k for a real loss in abstention accuracy — which is exactly
   what the tier-B abstention slice would show, and why it must be measured
   rather than argued.

Requires a decision before anything is changed. The harness can now produce the
before/after for any of the three.


## F27 promoted to P1 — and three corrections to my own earlier reading

Maintainer promoted F27 from P2 to P1: `recall_at_fetch = 1.0` with
`hit_at_k = 0.318` means the entire quality gap is **post-retrieval**. The
correct chunk was in hand every time and something after retrieval discarded
it. The original audit rated this risk **mitigated**; measurement inverted that.

Before the diagnostics, three things I wrote in the previous entry were wrong or
over-read. Recording them because the whole point of the instrument was to stop
me reasoning from a four-query sample.

**Correction 1 — "the correct document ranks first in every case."** It does
not. Measured over all 22 answerable entries: rank-1 is correct in **20**, not
22. Two entries rank an incorrect chunk first (`Et le stock de securite ?`,
`What stock level triggers a replenishment order for the Halifax warehouse?`).
My claim came from the four queries I happened to print.

**Correction 2 — "by two to three orders of magnitude."** The median rank1/rank2
ratio for correct rank-1 chunks is **26x**, with a minimum of **1.15x**. Several
correct answers lead the runner-up by less than 2x. The 500x–5600x figures I
quoted are the top of the distribution, not the distribution.

**Correction 3 — "the score tracks chunk shape."** Shape is a strong effect but
not the whole story. Correct rank-1 chunks cut by the floor, by shape:

    list    7/8
    table   1/1
    prose   5/11   <- 45% of correct PROSE answers are also cut

A shape-conditioned floor alone would leave half the prose failures in place.


## [F27 diagnostic 1] What the cross-encoder is actually handed
Status: DONE — one hypothesis DISPROVED, a different defect found
Commit: `a95f2ed` · data: `eval/baselines/f27-rerank-diagnostic-2026-08-03.json`

The hypothesis was that the embedding leg sees heading-enriched text while the
cross-encoder sees a bare fragment, because heading paths are prepended at
extraction time and context expansion runs after reranking.

**Disproved.** Ingestion embeds `node.text` and stores `node.text`
(`services/ingestion.py:_embed_chunks` — `embedding=emb, text=node.text` from
the same list), and `_rerank_pool` scores `c.text`. The two legs receive
identical text. There is no divergence to fix.

**What the measurement did find** is a systematic absence, not a divergence:

    rank-1 chunks:                        22
    ... carrying section_title metadata:   9
    ... whose TEXT leads with it:          9   (9/9 — enrichment is never stripped)
    ... with NO section metadata at all:  13

The 13 are exactly the **non-heading-aware extractors** — csv, xlsx, pptx and
both OCR PDFs. Only `docx_format.py` and `txt.py` build a heading stack and
prepend a path. For the rest, the leading line of what the cross-encoder scores
is whatever the format happened to emit:

    b03-sales.csv           'region,quarter,units_sold,revenue_cad'
    b05-inventory.xlsx      'Sheet: Thresholds'
    b04-wide-row.csv        'contract_id,summary'
    b09-scanned-notice.pdf  'ARCHIVED NOTICE'
    b13-avis-archive-fr.pdf 'AVIS ARCHIVE'
    b07-review.pptx         'Quarterly Review'

No filename, no document title, no table caption. A cross-encoder trained on
prose query/passage pairs is being asked to judge `West,Q4,205,2460` against
"What revenue did the West region record in Q4?" with nothing else to go on.

And the enrichment that would help arrives too late: `_expand_context()` runs at
`services/retrieval.py:188`, **after** the floor has already been applied at
line 182. Section-parent text can never influence the decision that discarded
the chunk.


## [F27 diagnostic 2] What the scores actually separate
Status: DONE
Commit: `a95f2ed` · tool: `eval/diagnose_rerank.py` (reports only, tunes nothing)

**The absolute score does not separate correct from incorrect.** The ranges
overlap almost completely:

    rank-1 CORRECT    n=20   min 0.0003   median 0.0821   max 0.9999
    rank-1 INCORRECT  n=2    min 0.0005   median 0.0020   max 0.0035

**The rank1/rank2 gap separates them better, though not cleanly:**

    rank-1 CORRECT    median 26.3x   min  1.15x
    rank-1 INCORRECT  median  5.6x   max  8.06x

Keep-criterion comparison over rank-1 only, nothing changed:

| criterion | keeps correct | keeps incorrect |
|---|---|---|
| absolute floor ≥ 0.25 | **7/20** | 0/2 |
| ratio gap ≥ 10x | 10/20 | 0/2 |
| ratio gap ≥ 5x | 14/20 | 1/2 |
| absolute gap ≥ 0.01 | **14/20** | 0/2 |

An absolute floor throws the gap signal away entirely. Two criteria double the
correct-answer retention at no measured cost in incorrect answers.

**Do not read that table as a result.** n=2 for the incorrect group is far too
small to claim "0 incorrect kept" means anything, and the rows exclude the
unanswerable set entirely — the population that actually decides whether
abstention still works. Both gap criteria must be measured end-to-end with
`false_abstention_rate` and `correct_abstention_rate` before any of them is
believed. The table's only job is to show the signal exists.


## PROPOSAL P-2 — finding #27 (P1). Candidates, not a decision.
Status: PROPOSAL-PENDING

`bge-reranker-base` is trained on prose query/passage pairs and
`sigmoid(logit)` is **not a calibrated probability**. "The floor is mistuned" is
therefore one hypothesis among several, not the conclusion. Four candidates,
none chosen, each with what would falsify it:

**C1 — Enrich the reranker input.** Prepend document title / sheet / table
caption for the formats that carry no heading path, so the cross-encoder judges
a passage rather than a fragment.
*Attacks:* the 13 rank-1 chunks with no section metadata.
*Falsified if:* enriched scores for table/list chunks stay in the 0.01–0.2 band.
*Cost:* changes stored text ⇒ **reindex** ⇒ new corpus provenance, and it is a
chunking-adjacent change, so it needs its own approval under R5.

> **AMENDED after the F29/F30 split.** C1 is not separable from finding #30.
> Enriching what the cross-encoder scores means enriching *before* the floor,
> and today the pipeline is `fetch → rerank → floor → top-k → expand`, so any
> enrichment that reaches the scorer **is** a reordering. C1's real cost is
> therefore the reindex **plus** reranking substantially longer text for every
> candidate on every query. Listing C1 and #30 as separate items made C1 look
> cheaper than it is.
>
> Partly discharged already: F29 (`64b9a35`) gave csv/xlsx/pptx a
> `section_title`, so the metadata C1 needs now exists for those three formats.
> PDF still has none. Nothing consumes it at rerank time — that step is C1 and
> remains pending.

**C2 — Gap-based or relative keep-criterion.** Keep rank 1 when it leads rank 2
by a margin, independent of absolute value; keep lower ranks only above a floor.
*Attacks:* the 13/20 correct answers the absolute floor discards.
*Falsified if:* `correct_abstention_rate` collapses — a query with no good
answer can still produce a large ratio gap between two equally irrelevant
chunks. The 1.15x correct minimum also means a gap threshold high enough to be
safe may cut real answers.
*Cost:* code only, no reindex. Cheapest to measure.

**C3 — Separate the abstention decision from relevance ordering.** Abstain on a
much lower absolute bar; order what survives by rerank score. Today one
threshold does both jobs, and the job it is bad at (calibrated absolute
confidence) is the one that produces the user-facing failure.
*Attacks:* the conflation itself rather than either symptom.
*Falsified if:* the low bar admits the distractor documents on unanswerable
queries.
*Cost:* code only.

**C4 — Per-query score normalisation.** Normalise across the candidate pool
(z-score or softmax) and threshold the normalised value, so the cut adapts to a
query's score scale instead of assuming one global scale.
*Attacks:* the shape-dependence directly — it is a scale problem, and this
removes the scale.
*Falsified if:* it destroys abstention, since normalising always produces a
"best" candidate however bad the pool.
*Cost:* code only.

C2, C3 and C4 are cheap and measurable now. C1 is the expensive one and the only
one that would change the index.

### Gating (as directed)

**Any tuning of the floor stays gated on tier A.** Tier B is deliberately
table-, list- and OCR-heavy — that composition is *why* the defect surfaced
there — so a value fitted against tier B would be fitted to the corpus's
composition, not to the system. That is overfitting with extra steps.

The **diagnostics above are not gated** and are complete.

### Do not over-read `recall_at_fetch = 1.0`

13 synthetic documents producing 18 chunks, with `retrieval_fetch_k = 20`,
means the fetch stage returns **the entire corpus** for every query. Recall of
1.0 is arithmetic, not evidence of retrieval quality, and it will fall on tier
A. What survives the caveat is the *shape* of the finding — the gap between
fetch and final is post-retrieval loss — not the specific value 1.000.


## [Phase 1.6] CI eval gate — and what it refuses to pretend
Status: DONE
Commit: `dee16fb` · file: `.github/workflows/eval.yml`

Two jobs, deliberately not one job with a mode flag (as directed):

| | `retrieval` | `full` |
|---|---|---|
| trigger | PR touching `backend/extraction/**`, `backend/services/**`, `backend/integrations/**`, `backend/core/config.py`, `backend/eval/**` | nightly cron + `workflow_dispatch` |
| passes | 2 | 3 |
| tolerance | **zero** | **measured**, reported by the job |
| cache | default | `ENABLE_ANSWER_CACHE=false` (harness refuses otherwise) |

The retrieval job **fails if its two passes disagree at all**. Retrieval mode
has no LLM in it, so any spread is nondeterminism nobody has found yet, and it
would make every future comparison unreliable.

Both jobs ingest into `knowall_eval`, never the production collection —
`ingest_corpus.py` refuses the default collection outright.

### The gate says what it cannot do

The regression-comparison step scans `eval/baselines/` for a file whose
provenance contains no `"unknown"` and no `"unpinned"`. When there is none it
emits a **warning that the regression gate is INACTIVE** and exits 0, rather
than passing silently. A step that reports success while comparing nothing is
precisely the green checkmark that lies.

Gated **today**, with no reference baseline: corpus manifest integrity,
embedding-model identity, golden-set schema, `needs_rewrite()` branch
agreement, and retrieval determinism.
Not gated today: metric regression. Requires tier A.


## [Phase 1.6] Provenance-complete baseline + a gate that could have vanished
Status: DONE
Commit: `dee16fb` · file: `eval/baselines/tier-b-retrieval-2026-08-04.json`

Re-recorded after rebuilding the image (not `docker compose cp` — the code in
the image must match the sha it records) and recreating the containers. Every
provenance field now resolves:

    git_sha            56154fecc8e99bdefaf180495683b35ea4f85ae3
    api_image_digest   sha256:0dd9f3325c1c40df7945d62fa039830028c3db4bd4b766a05d773df0494b49bf
    reranker_revision  2cfc18c9415c912f9d8155881c133215df768a70
    bm25_revision      e499a1f8d6bec960aab5533a0941bf914e70faf9
    embed_model_digest 0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f
    corpus_manifest    32610e3d856c6caf5f2d3120c69321fa9192586d5a22f73c3ef38a2dc7f75754

This run was made **fail-closed**: `EXPECTED_EMBED_MODEL_DIGEST` was passed
explicitly, so F24 enforcement was active rather than warning.

Numbers unchanged from the diagnostic run, and the split pair now states
plainly what the single number hid:

    recall_at_fetch          1.000
    hit_at_k                 0.318
    mrr_at_k                 0.318
    false_abstention_rate    0.682     <- 68% of answerable questions get "I don't know"
    correct_abstention_rate  1.000
    spread across 3 runs     0.0 on every metric

Determinism has now been confirmed on **two separate container builds**, six
passes total. That is what makes the zero CI tolerance a measurement rather
than an assumption.

### A gate that could have disappeared silently

Running `compare.py` against the two real baselines rather than only synthetic
fixtures exposed a hole in it. The old file predates the abstention split, so
both new metrics were simply **absent** — and the comparator skipped them
without a word. A rename or a dropped field would have passed as "no
regression" forever.

It now warns when a metric the OLD baseline gated on is missing from the NEW
one. The reverse (new metric, old baseline predates it) stays silent, because
nothing was lost.

End-to-end verification, old vs new:

    verdict: COMPARABLE_WITH_COSMETIC_DRIFT
      reranker_revision: unpinned -> 2cfc18c9...
      bm25_revision:     unpinned -> e499a1f8...
      git_sha:           unknown  -> 56154fec...
      api_image_digest:  unknown  -> sha256:0dd9f332...
    [tier_b]
      ^ recall_at_fetch  1.000 -> 1.000  (+0.000)
      ^ hit_at_k         0.318 -> 0.318  (+0.000)
      ^ mrr_at_k         0.318 -> 0.318  (+0.000)
    OK — no metric regressed beyond tolerance.       exit 0

The comparator correctly classified a build-identity change as cosmetic, named
every drifted field, and diffed the numbers.


## [Phase 1.6] Full-mode variance — measured 0.0, and NOT usable as a tolerance
Status: DONE (measurement) · **BLOCKED** (tolerance) on finding #27
Baseline: `eval/baselines/tier-b-full-2026-08-04.json`

Three passes, `ENABLE_ANSWER_CACHE=false`, F24 enforcement fail-closed
(`EXPECTED_EMBED_MODEL_DIGEST` passed explicitly, so a drifted model would have
aborted the run rather than warned).

    [tier_b]  recall_at_fetch          1.000
              hit_at_k                 0.409     (retrieval mode: 0.318)
              mrr_at_k                 0.409
              false_abstention_rate    0.545     (retrieval mode: 0.682)
              correct_abstention_rate  1.000

    variance across 3 runs:  spread 0.0 on EVERY metric.

Rewrite fired on all 5 entries whose branch predicted it, and actually changed
the text in all 5 (`n_would_fire=5, n_fired=5, branch_mismatches=[]`). Full mode
is genuinely exercising rewrite and expansion — unlike retrieval mode, where
`fired=0` by construction.

### The 0.0 is an artifact. Do not encode it as the tolerance.

Zero spread with an LLM in the loop was implausible enough to check rather than
report. Measured directly, calling the two LLM paths that are actually in the
retrieval loop 10 times each on identical input:

    query rewrite    "How long does it take before that reaches the duty supervisor?"
                     -> 3 distinct outputs in 10 calls
                     "And the disposal rule?"
                     -> 4 distinct outputs in 10 calls
    expansion        "What revenue did the West region record in Q4?"
                     -> 2 distinct outputs in 10 calls
                     "How long must files be kept before they may be destroyed?"
                     -> 5 distinct outputs in 10 calls

`llm_temperature = 0.1`, no seed. **The LLM is not deterministic.** The rewrites
differ substantially — one call produced "What is the policy on disposing of
hazardous waste?" for a records-retention follow-up, which is a different query
by any reading.

Separate observation, not acted on: for the retention question the expansion
step returns **statements rather than queries** in 9 of 10 calls -- e.g. "For
business purposes, companies often have policies in place regarding the
retention of documents and records." That is a prompt-adherence problem with a
1b model, not finding #27, and it is logged here rather than fixed because
changing the expansion prompt is a generation-prompt change (R5) and because
nothing can measure the effect while #27 pins 60% of the entries.

So the pipeline is stochastic and the metric did not move. The reason is
finding #27:

    answerable entries returning 0 chunks   12 / 22   pinned at hit@k = 0
    unanswerable entries returning 0 chunks  3 /  3   pinned at 1.0
    ------------------------------------------------------------------
    entries whose score CANNOT vary         15 / 25 = 60%
    entries that could express variance     10 / 25 = 40%

and every one of those 10 live entries returned **exactly one** chunk. The score
floor collapses the result set to 0 or 1 items, so a rewrite would have to flip
*which single chunk* survives in order to move any metric. That is a very high
bar, and it is why substantially different queries produce identical numbers.

Corroborating detail: `mrr_at_k == hit_at_k` exactly, in both modes
(0.318/0.318 and 0.409/0.409). With never more than one result there is no rank
to reciprocate — **mrr carries no information at all today**, and will not until
#27 is resolved.

### Consequence

**The full-mode CI tolerance cannot be set yet.** A tolerance of 0.0 derived
from this run would be a gate that starts failing the day #27 is fixed and
entries become able to move. Recorded as measured-but-unusable, with the
mechanism, rather than shipped as a number.

Re-measure after #27 is resolved AND on tier A. Until then the nightly full-mode
job records and reports the spread without gating on it, which is what the
workflow already does.

### One provenance caveat, stated rather than hidden

This baseline records `git_sha 8f114488` while the image was built at
`56154fec`. I passed `$(git rev-parse HEAD)` at launch, and HEAD had moved two
commits ahead of the image — both documentation-only, so the numbers are
unaffected. The mechanism nonetheless permits a mismatch.

`api_image_digest` is the authoritative identity of the code that ran;
`git_sha` is the repository pointer at launch and may run ahead of the image.
`baselines/README.md` now says so. Anyone diffing two baselines should trust the
image digest.


## CORRECTION — the variance result is a SENSITIVITY finding, not a stability one
Applies to: the full-mode entry above · directed by the maintainer

The previous entry reported "spread 0.0 across a provably stochastic pipeline"
and drew the right operational conclusion (do not set the tolerance) from the
wrong framing. Stated correctly:

> **0.0 spread across a pipeline that is demonstrably non-deterministic means
> the harness cannot currently detect change. It is a statement about the
> instrument, not about the system.**

The corroborating tell is `mrr_at_k == hit_at_k` *exactly*, in both modes
(0.318/0.318 and 0.409/0.409). Two metrics reporting one bit of information,
because results never exceed one item. A measuring instrument whose two
channels are perfectly correlated is reporting its own floor, not the signal.

Consequences, all of which follow from sensitivity rather than stability:

- The nightly full-mode job stays **non-gating**. It records spread; it does
  not act on it.
- Zero spread must never be cited as evidence that a change was safe. It is
  currently consistent with *any* change to the LLM path.
- Detecting change requires the metric to be able to move, which requires
  finding #27 to lift. Sensitivity is blocked on #27, not on tier A.
- The retrieval-mode zero is a different claim and still stands: that mode has
  no LLM in it, so there is nothing for the metric to be insensitive *to*.


## Finding #27's first diagnostic produced TWO findings — now split
Directed by the maintainer: track them separately, since they are separately
testable and separately fixable.

| # | Sev | Finding | Status |
|---|-----|---------|--------|
| **29** | P2 | csv, xlsx and pptx chunks carry **no section metadata at all** | **FIXED** — `64b9a35` |
| **30** | P2 | `_expand_context()` runs **after** the floor, so enrichment can never influence the discard decision | **PINNED, not fixed** — `414de43`; entangled with P-2 C1 |


## F29 (P2) — extractor metadata gap
Status: FIXED · Commit: `64b9a35`

13 of 22 rank-1 chunks on tier B carried no `section_title`, and they were
exactly the extractors that build no heading stack — only `docx_format.py` and
`txt.py` did. Two real consequences: `_expand_with_sections` fell through to a
plain ±1 window so row-groups of one table were never related to each other,
and the cross-encoder received a bare row-group whose leading line was a CSV
header with nothing saying which table it came from.

    csv   ->  "Table: <stem>"        one section per file
    xlsx  ->  "Sheet: <name>"        matches the prefix the text already carries
    pptx  ->  "Slide N: <title>"     falls back to "Slide N", never absent

**PDF deliberately excluded.** Its chunks are pages; a per-page section title
would make every section a singleton — strictly worse than the ±1 window it
uses today. PDFs still have no document-level title in their reranker input.
That is P-2 candidate C1 and is *not* fixed here.

Metadata only: the embedded text is unchanged, so the corpus manifest hash and
every vector are identical and a before/after stays COMPARABLE. Re-ingest
produced **18 chunks from 13 documents — the same count as before**, which is
the check that no chunking changed.

Five tests run the real extractors over fixtures built in the test, including a
regression guard that no chunk from these three formats may lack the field.


## F30 (P2) — enrichment arrives after the decision it should inform
Status: PINNED, NOT FIXED · Commit: `414de43`

    fetch -> rerank -> FLOOR (retrieval.py:182) -> top-k -> expand (:188)

A chunk discarded for scoring 0.16 against a floor of 0.25 is discarded on the
merits of its **bare** text, and the section context that might have lifted it
is fetched only for its luckier neighbours.

Four characterization tests pin it: a discarded chunk's section is never even
requested; survivors do get context; the reranker provably sees bare text; and
the same ordering holds in window mode.

**Why pinned rather than fixed — and this changes proposal P-2.** Moving
expansion before the floor means the cross-encoder scores *expanded* text. That
is candidate **C1 in everything but name**. So:

> **C1 and F30 cannot be decided independently.** C1's true cost is not only
> the reindex — it is reranking substantially longer text for every candidate,
> on every query. Listing them as separate items made C1 look cheaper than it
> is.

Until that decision lands, the tests make the ordering explicit and fail loudly
if anyone reorders it by accident.


## F28 (P1) — the rewrite fallback cannot see semantic drift
Status: FIXED (guard + instrumentation) · Commit: `b6a6f00`

`query.py` caught exceptions, empty output and gross length overruns — every
failure mode except the one that actually happens. Observed in the full-mode
run: a records-retention follow-up rewritten as *"What is the policy on
disposing of hazardous waste?"* — fluent, correctly sized, past every guard,
about a different subject. A test pins that it satisfies both pre-existing
checks.

The guard measures **meaning, not shape**: cosine between the original and the
rewritten query in the same embedding space retrieval scores in. An
unmeasurable similarity is never a rejection — it degrades to the old
behaviour rather than discarding every rewrite.

**Instrumentation matters as much as the guard.** A rejected rewrite leaves
`standalone == original`, indistinguishable in hit@k from a question that was
already standalone. `RewriteResult` now carries `fired`, `reason`
(`no-history | not-needed | llm-error | empty | too-long | drift | ok`), the
similarity and the rejected text; the harness records all of it per entry and
reports `n_rejected_as_drift`, the reason histogram and similarity min/median.

### Measured distribution — guard disabled, 5 entries × 6 calls

    n=30   min 0.387   median 0.692   max 1.000
    0.45 / 0.50 / 0.55   reject   6/30 (20%)
    0.60 / 0.65          reject  13/30 (43%)
    0.70                 reject  18/30 (60%)

The 6 rejected at 0.55 are all one entry: *"Et le stock de securite ?"* →
*"What does the reorder point list?"* — wrong subject (the entry asks for
`safety_stock=15`, the rewrite asks for `reorder_point=25`) **and** wrong
language.

### Honest limits, recorded rather than glossed

- `0.55` was chosen **a priori**; the measurement is *consistent with* it, not
  derived from it. Deriving a threshold from the tier-B distribution would be
  the overfitting this log keeps warning about.
- It catches **gross** drift only. *"And the disposal rule?"* → *"What kind of
  records is covered under the retention policy?"* scores 0.596 and passes,
  though it is also drifted. Catching that costs 43% of rewrites, which is a
  retrieval-quality change needing a measured before/after.
- Sample is 30 rewrites, one model, tier B only.

**No LLM seed was set**, as directed: a seed would make the eval reproducible
while hiding the nondeterminism real users get — the opposite of what this
harness is for.


## [F29] Before/after measured — ZERO change, and that was predictable
Status: measured, and the result is about the instrument as much as the change

Re-ingested the corpus with the new section metadata and re-ran retrieval mode,
two passes, against the committed baseline:

    verdict: COMPARABLE_WITH_COSMETIC_DRIFT

    [tier_b]
      ^ recall_at_fetch           1.000 ->  1.000  (+0.000)
      ^ hit_at_k                  0.318 ->  0.318  (+0.000)
      ^ mrr_at_k                  0.318 ->  0.318  (+0.000)
      ^ correct_abstention_rate   1.000 ->  1.000  (+0.000)
      v false_abstention_rate     0.682 ->  0.682  (+0.000)

Re-ingest produced **18 chunks from 13 documents**, identical to before, which
confirms no chunking moved. Every metric identical to three decimals.

### This is not evidence that F29 helped, and not evidence that it is safe

It is the **sensitivity finding applied to my own change**, and it was
predictable from the mechanism:

1. Finding #27 pins **15 of 25** entries at a score that cannot move.
2. Every one of the 10 live entries returns **exactly one** chunk.
3. F29's only retrieval-path effect is on **context expansion** — and by
   finding #30 expansion runs *after* the floor.

So a chunk the floor discards never reaches expansion, and a chunk that
survives gets expanded either way (previously via the ±1 window, now via its
section). Expansion changes the chunk's *text*, not whether it is the right
chunk, so `hit@k` cannot move. **F29 could not have registered on this
instrument no matter what it did.**

What IS proven about F29: five unit tests run the real extractors and assert
the field is emitted, including a guard that no chunk from these three formats
may lack it. That satisfies R2 for the change itself. The *retrieval* effect is
unmeasurable today and is recorded as unmeasured rather than as neutral.

Three findings are therefore entangled, and the order is forced:

> **#27 must lift before #29 or #30 can be evaluated at all.** Until the floor
> stops collapsing results to 0-or-1 items, the harness cannot distinguish a
> retrieval improvement from a no-op.

### The comparator caught my own sloppiness, which is the point of it

    cosmetic drift (no expected retrieval effect):
      git_sha:          56154fec... -> b6a6f00...
      api_image_digest: sha256:0dd9f332... -> unknown

`api_image_digest` went to `unknown` because this run used code copied into a
running container rather than a rebuilt image, and I did not pass the image id.
The recorded `git_sha` (`b6a6f00`) is also **wrong for the code that ran** — the
container additionally held F29 (`64b9a35`) via `docker compose cp`. Exactly the
git_sha-vs-image hazard documented earlier, committed by me, one session after
documenting it.

The after-run is therefore **not committed as a baseline**. It is a diagnostic
comparison, recorded here.

**Hardening, so the next person is told rather than expected to remember:**
`run_eval.py` now prints a loud `WARNING: DIAGNOSTIC ONLY — unresolved
provenance: <fields>` at record time whenever any provenance field is `unknown`
or `unpinned`, naming them, and pointing at `baselines/README.md`. Previously
that judgement lived only in a README nobody reads while running an eval.


# Section 1B — Phase 1 exit criteria RESTRUCTURED (maintainer decision)

Tier A is not landing. Rather than leave Phase 1 permanently open against a
dependency outside this work, **Phase 1 exits on tier B**, and everything that
genuinely requires real documents moves to a new **Phase 1A**.

| | exits on | state |
|---|---|---|
| 1.1 lockfiles | — | **DONE** |
| 1.2 ruff / mypy / pytest green | — | **DONE** |
| 1.3 httpx port | — | **DONE** |
| 1.4 reproducible corpus + baseline | the tier-B baseline as reference | **DONE** |
| 1.5 golden set | 25 entries + the unanswerable additions (32 total) | **DONE** |
| 1.6 CI gate | retrieval-mode gate ACTIVE | **DONE** |

**Phase 1A — deferred until tier A exists:**

- ≥60 golden entries drawn from real documents.
- The **metric-regression half of 1.6**. The workflow scans `eval/baselines/`
  for a provenance-complete file and, finding none suitable, emits a warning
  that the regression gate is **INACTIVE** rather than passing silently.
  Gated *today*: corpus integrity, embedding-model identity, golden-set schema,
  `needs_rewrite()` branch agreement, retrieval determinism.
- Any **relevance** threshold. C2's gap margin and C4's normalised cut are both
  corpus-shape-sensitive in a way C3's abstention floor is not.

`docs/HANDOFF.md` records, as directed, that the headline baseline is
synthetic, tier-B-shaped, deliberately table/list/OCR-heavy, and that **no
threshold in this system has been validated against real-world document
composition**.


## PROPOSAL P-2 — DECIDED: candidate C3
Status: ACCEPTED and implemented · Commit: `d3aab92`

The maintainer chose C3 on a property that was **not in my candidate list**,
and the reasoning corrects an omission in the proposal:

> C3 is the only candidate that restores the instrument. C2 keeps rank 1 when
> it dominates — which still returns **one item**. `mrr_at_k == hit_at_k`
> stays exact, 60% of entries stay pinned, and the harness remains unable to
> distinguish a retrieval improvement from a no-op.

I had scored the candidates on whether they fix the *defect*. I had not scored
them on whether they fix the *measurement*, even after writing the sensitivity
finding myself. C2 would have improved hit@k while leaving the harness blind.

### Implemented

    ABSTENTION  abstention_score_floor = 0.01, applied ONCE to the best
                candidate. Below it, even the top hit is one the cross-encoder
                confidently rejects.
    ORDERING    the reranker's job. rerank_top_n bounds the count. No
                per-chunk relevance judgement by default.

`rerank_score_floor` is **not deleted** — it defaults to `0.0`, and a test
pins that restoring `0.25` reproduces the old behaviour exactly. Both numbers
sit in the provenance tuple, so any baseline recorded either side of this
change is flagged as **semantic drift** rather than silently diffed.

### Why the abstention bar is not gated on tier A

Once the two jobs are separated, the bar answers *"did retrieval return
anything coherent?"*, not *"is this relevant?"*. A cross-encoder sigmoid below
0.01 is a logit near −4.6: the model is confidently rejecting its own best
candidate. That is tied to the **model's** confidence semantics, not to a
corpus's composition — principled rather than measured, and documented as such.

Falsification is unchanged: **if distractors are admitted on unanswerable
queries, C3 is wrong.**

### One note on the brief

The instruction said to set the bar "well below your 0.387 minimum". 0.387 was
the minimum **rewrite similarity** (finding #28), a different measurement in a
different space. The reranker's observed rank-1 output spans **0.0003 to
0.9999**. The bar was set from that range and from the logit reasoning above,
which I believe is what was intended; recorded here in case it was not.


## Golden set: unanswerable entries 3 → 10
Status: DONE (done FIRST, before reading any C3 result, as directed)

`correct_abstention_rate = 1.000` over three entries cannot validate the one
thing C3 is most likely to break. Seven added, two kinds, both languages:

**Near miss — the topic IS covered, the specific asked for is not**

- *"Who can authorise an exception to the seven-year retention period?"* — b01
  states the period **and** the authorisation rule, and nothing about
  exceptions. Shares almost all its vocabulary with the answering chunk.
- *"What happens to an incident that is still unresolved after the duty
  supervisor has been notified?"* — b02 escalates at 72 hours and stops.
- *"Quel montant est accorde aux demandes soumises apres le 31 mars ?"* — b13
  gives both the deadline and the ceiling, and nothing about late applications.

**Absent specific — plausible values that do not exist**

- *"How long is the maintenance window for the payroll system?"* — the b06
  table lists `billing` and `reporting` only.
- *"What revenue did the West region record in Q1 of the following year?"* —
  b03 covers one year. Nearly identical wording to an answerable entry.
- *"What penalty applies when uptime falls below 95 percent?"* — b08 defines
  credits below 99.5 percent.
- *"Combien de jours de preavis faut-il pour resilier le contrat CT-9002 ?"* —
  b04 carries CT-9001 only. Returning the CT-9001 notice period here would be a
  confidently wrong answer, not a near miss.

    total 32   answerable 22   unanswerable 10   (7 en / 3 fr)


## [P-2 C3] Result — falsification condition FIRED, and the split is diagnostic
Status: measured, provenance-complete except `web_image_digest` (frontend not
rebuilt; retrieval mode never touches it)

    retrieval mode, k=5, 3 runs, 32 golden entries (22 answerable / 10 unanswerable)

                              before C3      after C3
    recall_at_fetch             1.000          1.000
    hit_at_k                    0.318          0.682
    mrr_at_k                    0.318          0.682
    false_abstention_rate       0.682          0.318
    correct_abstention_rate     1.000          0.200   <-- FALSIFICATION FIRED
    spread across 3 runs         0.0            0.0

### 1. Abstention first, because it is the falsification condition

`correct_abstention_rate` collapsed **1.000 → 0.200**. Eight of ten unanswerable
queries now return chunks. Split by the two kinds authored for exactly this
purpose, the causes are **different**, and only one of them is a threshold
problem:

**Absent-specific — the bar is too low. Fixable, and gated on tier A.**

    0.0664  How many parking permits were issued last September?
    0.0383  What revenue did the West region record in Q1 of the following year?
    0.0380  Combien de jours de preavis faut-il pour resilier le contrat CT-9002 ?
    0.0152  What is the annual budget for the advanced training modules?

All four sit between 0.015 and 0.066 — above the 0.01 bar, but only just. A bar
around 0.07–0.10 catches all four. **Not doing that:** a value chosen to
separate these specific scores is a corpus-fitted relevance threshold, which is
exactly what Phase 1A defers until tier A exists.

**Near-miss — NO absolute bar can fix these.**

    0.9968  Quel montant est accorde aux demandes soumises apres le 31 mars ?
    0.9568  What penalty applies when uptime falls below 95 percent?
    0.9557  What happens to an incident that is still unresolved after the
            duty supervisor has been notified?
    0.6986  Who can authorise an exception to the seven-year retention period?

These score **0.70 to 0.997** — higher than most *correct* answers in the same
run. The cross-encoder is confidently right: the chunk it returned **is** topically
relevant. It simply does not contain the answer.

> A cross-encoder scores **topical relevance**, not **answer presence**. No
> threshold on that score can separate "this passage is about your question"
> from "this passage answers your question", because the model is not measuring
> the second thing. Raising the bar high enough to reject a 0.9968 near miss
> would reject nearly every correct answer too.

Logged as **finding #31 (P1)**. It is not a C3 regression — the old floor
"passed" these only because it was rejecting almost everything, including 15 of
22 correct answers. C3 exposed it; it did not cause it.

**Correctly abstained (2/10):** *"Quel taux de change s'applique aux
subventions versees a l'etranger ?"* (no exchange-rate content anywhere) and
*"How long is the maintenance window for the payroll system?"* — the only two
where even the best candidate fell below 0.01.

### 2. The instrument: alive, and the reason it still reads equal has changed

    answerable returned:    5 chunks x 15 entries,  0 chunks x 7
    unanswerable returned:  5 chunks x 8,           0 chunks x 2
    reciprocal rank of every hit: 1.0  (15 of 15)

`mrr_at_k == hit_at_k` still, at 0.682 — but for a completely different reason,
and the difference matters:

    BEFORE  forced by construction. Results never exceeded ONE item, so there
            was no rank to reciprocate. The metric could not diverge.
    AFTER   an observation. Results are five items, mrr CAN diverge, and it
            does not because the reranker places the correct chunk at rank 1
            in every single case where it retrieves it at all — 15 of 15.

That is the instrument coming alive. It can now register a ranking regression,
which it was structurally incapable of before. `mrr_at_k` is the number to carry
into Phase 3 as the retrieval-quality baseline.

### 3. Do NOT read the hit@k jump as a 2.1x improvement

0.318 → 0.682 is **substantially mechanical**. The corpus is 18 chunks; `k=5`
returns 28% of it on every non-abstaining query. Zero entries returned five
chunks and missed the answer, which sounds impressive and mostly reflects how
small the haystack is.

What is *not* mechanical, and is the real result: the correct chunk was there at
rank 1 in every case, and the old floor was throwing it away.

### 4. The remaining false abstentions are mostly by construction

Seven answerable entries still return nothing. **Six are conversational** —
*"And the disposal rule?"*, *"Et le stock de securite ?"* — which retrieval mode
sends to the retriever **verbatim**, because it does not rewrite. They are
authored to require history-based rewriting, so failing here is the mode
behaving correctly, not a defect. Full mode is where they should be read.

The seventh, *"At what stock level should a replenishment order be raised?"*
(xlsx `reorder_point,25`), is a genuine table-answer failure with the correct
chunk scoring below 0.01.

`false_abstention_rate = 0.318` in **retrieval mode therefore over-counts**, and
should be read alongside the conversational slice (`hit@k = 0.333`) rather than
alone.


## [F31 caveat] The generator does NOT catch the near-misses — 0 of 4
Status: measured · F31 stays **P1**, and converges with finding #5 as predicted

The maintainer's caveat was right to demand the measurement: the system has two
abstention layers, and determining answer presence is a job the generator can do
and a cross-encoder structurally cannot. Measured in full mode
(`ENABLE_ANSWER_CACHE=false`, `llama3.2:1b`), every unanswerable entry run
through `prepare()` + `answer_prepared()`. Reported individually as directed.

### The four near-misses, verbatim

**1. "Who can authorise an exception to the seven-year retention period?"**

> *"According to [1], the records officer has written authority to dispose of
> records. Therefore, the records officer is the one who can authorise an
> exception to the seven-year retention period."*

**FABRICATION.** b01 says disposal requires the records officer's written
authorisation. It says nothing about exceptions to the retention period. The
model made an unsupported inferential leap — signposted by its own
"Therefore" — and attached a citation to it.

**2. "What happens to an incident that is still unresolved after the duty
supervisor has been notified?"**

> `[1] [1][3]`

**DEGENERATE.** Citation markers, no prose. Not a decline and not an answer.

**3. "Quel montant est accorde aux demandes soumises apres le 31 mars ?"**

> *"Selon les informations fournies [5], le montant des demandes soumises après
> le 31 mars est de 75000 dollars."*

**FABRICATION, and the worst of the four.** b13 states the deadline *is* 31
March and the ceiling is 75 000. The model inverted a deadline into an
entitlement: it asserts that applications submitted **after** the deadline
receive the money. Fluent, cited, and the opposite of what the source says.

**4. "What penalty applies when uptime falls below 95 percent?"**

> `[1] [2][3]`

**DEGENERATE**, as #2.

    generator declined on the near-misses:  0 of 4

### And the absent-specific half

Declined on 2 of 6 — and both are the two where **retrieval itself abstained**,
so the generator never saw any context. On every entry where chunks were
returned, it produced something.

One of those, *"How many parking permits were issued last September?"*, is worth
recording because it is the near-miss failure in miniature:

> *"According to the provided documents, in September 2023, there are no parking
> permit reissues mentioned. Therefore, I could not find this information..."*

It reaches the right conclusion through a **false premise**: b12 states permits
*are* reissued each September. The decline is correct; the reasoning contradicts
the cited source.

### Conclusion

    generator declined on 2 of 10 unanswerable entries
    ...and both were entries where retrieval returned NOTHING

> **With `llama3.2:1b`, the second abstention layer does not function.** System
> prompt rule 3 is followed essentially never when context is present. The
> layering argument is sound in principle; this model does not implement it.

F31 therefore **stays P1** and is not merely a layering observation. It converges
with **finding #5 (citations unverified)** exactly as anticipated — same root
cause, now with four measured instances: the model asserts what the context does
not support and cites a passage that does not support it.

Scoped honestly: this is measured on `llama3.2:1b` only. A larger generator may
comply with rule 3. But 1b is what the system ships with, and **upgrading the
model is explicitly forbidden as a substitute for fixing grounding** (Appendix
B), so the finding stands against the shipped configuration.

Two follow-on observations, recorded not acted on:

- **Degenerate citation-only output** (2 of 4 near-misses returned `[1] [2][3]`
  and nothing else) is a distinct generation defect from fabrication. It is not
  an abstention and would reach a user as an empty answer.
- The correct fix direction is **verification against the cited passage**, which
  is finding #5's territory, not a threshold anywhere.


## Phase 3 planning note — the reranker has no ordering headroom on tier B
Status: recorded, as directed

Reciprocal rank was **1.0 in 15 of 15** hits. The reranker places the correct
chunk first in every case where it retrieves it at all. There is no ordering to
improve on this corpus, which means:

> **P-2 candidates C2 and C4, and the C1 + finding #30 joint experiment, are all
> TIER-A-ONLY.** Measuring any of them against tier B would compare against a
> ceiling already reached — a null result would be indistinguishable from a
> broken implementation.

Phase 3 must not schedule them before tier A exists. C1/#30 additionally carry
the reindex plus longer-reranking cost, which must be stated together.

## F32 (P2) — degenerate citation-only generation
Status: OPEN, scheduled for 2.4 with finding #5

Split out of F31 at the maintainer's direction, because it is a **different
defect with a different fix**. Two of the four near-miss probes returned:

    [1] [1][3]

Citation markers, no prose. That is neither an answer nor an abstention. It
passes every existing check — non-empty, correctly sized, contains citations —
and reaches the user as an empty answer bubble.

**Agreed fix (2.4):** detect it as a *malformed generation* — non-citation
content below a trivial length — treat it as a **failed** generation, and fall
back to `NO_ANSWER_MESSAGE` rather than streaming an empty bubble. It belongs
next to finding #5's citation verification because both are checks on the
generated text against what the context supports, and both need the same hook.

Note the shape of this: it is the same class as finding #28. A guard that
checks for emptiness and length but not for *content* passes fluent-looking
output that carries no information. #28 was the query-rewrite instance; this is
the generation instance.


## Metric limitation — `correct_abstention_rate` cannot detect abstention-by-misreading
Status: RECORDED, deliberately not fixed

The absent-specific entry *"How many parking permits were issued last
September?"* produced:

> *"According to the provided documents, in September 2023, there are no parking
> permit reissues mentioned. Therefore, I could not find this information in the
> provided documents."*

The **conclusion is correct**. The **premise contradicts the source** — b12
states permits *are* reissued each September. The model declined for a reason
that is false.

> `correct_abstention_rate` counts outcomes, not reasoning. It cannot
> distinguish a genuine abstention from an abstention reached by misreading the
> context. A system that misreads its way to the right answer scores identically
> to one that reads correctly.

Not fixing the metric now — measuring reasoning is a much larger instrument than
measuring outcomes, and building it here would be scope creep on a number that
is already the second most informative in the suite.

What it **does** change is weighting. The original audit's risk register treated
grounding as adequately mitigated by system-prompt rule 3. Three measurements
now say otherwise:

    F31   generator asserts unsupported claims and cites them   0/4 caught
    F32   generator emits citations with no content             2/4 near-misses
    here  generator reasons from a premise the context denies   1 observed

> **Groundedness checking is a heavier item than the original audit assumed**,
> and finding #5 (citations unverified) should be read as the parent of all
> three rather than as a separate P2.

## [Pre-reindex probe] F27 and F31 BOTH reproduce on the production collection
Status: DONE · diagnostic, NOT a baseline · raw output:
`eval/baselines/prereindex-probe-2026-08-05.txt`

Taken because the information disappears the moment the reindex runs. The
documents behind `knowall_collection` have no manifest, so nothing here is
reproducible — but the collection has a **different composition** from tier B
(376 points, 13 sources, mostly prose) and that is exactly what makes it worth
measuring.

### Coverage: 21 of 21

The retired golden set resolves **completely**. A full measurement, not a
subset.

### recall_at_fetch is a real number for the first time

    n                     : 21
    recall_at_fetch       : 0.952      (20/21)
    hit_at_k              : 0.952
    mrr_at_k              : 0.897
    false_abstention_rate : 0.000
    mean candidates/query : 20 of 376 points = 5%

On tier B, `fetch_k=20` against 18 chunks returned the entire corpus and 1.000
was arithmetic. Here it selects 5% and one query's relevant chunk never enters
the pool at all.

**`mrr_at_k` (0.897) diverges from `hit_at_k` (0.952) for the first time.** On
tier B they were identical in every run — first because results never exceeded
one item, then because the reranker had no ordering headroom. Here it has
headroom and does not always use it. That confirms the Phase 3 gating decision
from the other direction: C2, C4 and C1+#30 need a corpus where ordering can
move, and tier B is not one.

### F27's table signature REPRODUCES — it is a system property

    prose  n=2   min 0.9970  median 0.9979  max 0.9987   below old 0.25 floor: 0/2
    table  n=3   min 0.0138  median 0.0777  max 0.4050   below old 0.25 floor: 2/3
    list   n=16  min 0.0136  median 0.9083  max 0.9998   below old 0.25 floor: 1/16

Two of three table answers sit below the old floor **on a corpus that is
overwhelmingly prose**, and both are correct:

    0.0138  "Comment dit-on 'Hello' en français ?"          French Vocabulaire.xlsx
    0.0777  "What columns does the advertising dataset contain?"  advertising.csv

Same shape, different corpus, same outcome. **Finding #27 is not a tier-B
artifact**, and Phase 1A must test the shape effect against real documents
rather than treat it as a synthetic quirk.

Three caveats, recorded rather than smoothed:

- `n=3` for tables is thin.
- The shape classifier labels 16 of 21 chunks "list" (heuristic: ≥3 lines,
  <8 words/line), which catches bulleted prose out of docx. That bucket is
  heterogeneous and its range (0.0136–0.9998) partly reflects the classifier,
  not a property of the data.
- Three rank-1 chunks are simply WRONG, one of them at **0.9514** — a
  confidently-scored incorrect top hit inside the *answerable* set. That is
  F31's shape appearing where it was not being looked for.

### F31's near-miss behaviour REPRODUCES — also a system property

Four probes authored against these documents: squarely on a covered topic,
asking for a specific the corpus does not contain.

    0.9244  returned 5   "maximum number of nodes in a Databricks interactive cluster?"
                         best chunk: cluster UI/CLI/REST text — nothing about limits
    0.9211  returned 5   "Which Hadoop component replaced MapReduce in later releases?"
                         best chunk: schema inference for JSON/XML — not even adjacent
    0.5918  returned 5   "pass mark for the ABC DELF junior A2 exam?"
                         best chunk: a French TV-viewing exercise
    0.0008  ABSTAINED    "correlation coefficient between TV and newspaper spend?"

**Three of four scored 0.59–0.92**, and the top two score higher than most
*correct* answers in the same run. The 0.9211 case is the clearest
demonstration in either corpus: a chunk about JSON/XML schema inference,
scored at 0.92 against a question about MapReduce's successor.

> A cross-encoder scores topical relevance, not answer presence, on real
> documents exactly as on synthetic ones. No absolute bar separates them,
> because the model is not measuring the thing the bar would need.

### What this settles

Both P1 findings are **system properties**, confirmed on two corpora of
different composition. Neither is an artifact of the synthetic corpus, and
Phase 1A inherits both as things to test against real documents rather than
things to re-derive.

## [Phase 2.1] Reindex EXECUTED — all four confirmations pass
Status: DONE · commits `4b619e0` (identity + marker), `6949095` (verification)

    376 chunks reindexed from 13/13 documents
    verified 376 points in knowall_collection
    DIGEST_ENFORCEMENT_FROM=2026-08-05T08:53:05.779915+00:00

Chunk count is **identical** to before (376), which is the check that the
migration rewrote the corpus rather than changing it.

Preconditions met before executing: snapshot taken and **restore-verified**
(376 out, 376 back into a throwaway collection, throwaway deleted); dry run
clean; pre-reindex probe recorded; runbook written. Images were **rebuilt**
first so the migration ran committed code rather than files copied into a live
container.

### 1. Identity on every point — PASS

    points without a digest : 0
    distinct digests        : {0a109f422b47...: 376}
    distinct embed_model    : {nomic-embed-text:latest: 376}

Exactly ONE digest across the collection. More than one would mean it mixes
vectors from different models, which is the condition finding #2 existed to
make visible.

### 2. Missing digest is fatal under enforcement — PASS

Exercised live, not only in unit tests. `DIGEST_ENFORCEMENT_FROM` is now set in
**both** the api and worker environment maps in `docker-compose.yml` (not the
shell — compose does not pass that through), and the stack came back healthy
with it active.

### 3. Finding #29 metadata — PASS, and it exposed the scale of what is left

First time this has been observable at all: the 376 points predated F29.

    csv     72/72   carry section_title   <- previously ZERO
    xlsx      9/9   carry section_title   <- previously ZERO
    docx    73/73   carry section_title
    txt       8/8   carry section_title
    pdf      0/214  carry section_title
    pptx    not present in this collection

> **214 of 376 points — 57% of the collection — are PDF and still carry no
> section metadata.**

That was a deliberate exclusion (per-page sections would be singletons, worse
than the ±1 window PDFs use today), but until now its scale was invisible. On
this corpus the F29 fix covers 43% of points and the majority remain bare.

That materially changes the **C1** calculus in proposal P-2: C1 depends on
having something to prepend, and for the largest share of this collection there
is still nothing. C1 on real data therefore needs a PDF answer — document title
or page heading — that F29 did not provide. Recorded against P-2.

### 4. F19 — the boundary is NOT being crossed

Measured immediately post-reindex, on the maintainer's point that the reindex
re-embeds everything, so any crossing would already have silently truncated
during the migration.

    method: bge-reranker WordPiece (PROXY — see caveat)
    tokens  min=5   median=403   p95=649   max=1056
    chars   min=5   median=1420  max=2991
    chunks OVER 2048 tokens : 0
    chunks within 20% of it : 0

**No truncation occurred.** The largest chunk is ~1056 tokens, about half the
limit. So finding #19 is a **guard against future chunking changes, not an
active data loss** on this corpus — which is a materially weaker claim than the
one filed, and the right one.

The headroom is not large. `chunk_size` is 550 chars and
`table_chunk_char_budget` is 1600, yet the largest observed chunk is 2991 chars
— section prefixes and table row-groups stack. **Roughly a 2x increase in any
chunk budget would cross the boundary**, which is exactly the change the guard
must catch.

**Caveat, stated because the number would otherwise be over-trusted:**
nomic-embed-text's own tokenizer is not in the image. This uses the cached
bge-reranker WordPiece tokenizer — same BERT family, not the same vocabulary.
Good enough to answer "is 2048 crossed" when the answer is 1056; it would NOT
be good enough at 1900, and in that case the honest method is empirical: embed
a full chunk and a truncated prefix and compare, which is how #19 was proven
originally.


## PROPOSAL P-3 — finding #5 (groundedness). Candidates, not a decision.
Status: PROPOSAL-PENDING · scope: phase 2.4

### What finding #5 has become

Filed as "citations unverified", P2. It is now the **parent of three measured
defects**, and the original severity was wrong:

| child | what was measured |
|---|---|
| **F31** (P1) | generator asserts unsupported claims and cites them — **0 of 4** near-misses caught |
| **F32** (P2) | generator emits citation markers with no prose — 2 of 4 near-misses |
| *(unnamed)* | generator reaches a correct abstention through a premise the context **contradicts** |

The constraint that shapes every candidate: **groundedness checking on a 1B
model, without upgrading the model.** Appendix B forbids the upgrade as a
substitute for fixing grounding, and F31 measured that the second abstention
layer does not function at this size.

### The benchmark case — and why the obvious fix fails it

Every candidate must be scored against this, measured on 2026-08-05:

    question   "Quel montant est accorde aux demandes soumises apres le 31 mars ?"
    context    "Les demandes doivent etre soumises avant le 31 mars."  (+ ceiling 75000)
    answer     "le montant des demandes soumises apres le 31 mars est de 75000 dollars"

The model **inverted a deadline into an entitlement**. Now note what this
defeats:

- **Range / numeric validation passes.** 75000 is genuinely in the context.
- **Citation-index validation passes.** Passage [5] exists and is the one about
  the grant.
- **Verbatim-quote validation passes.** The model can quote the deadline
  sentence truthfully and still draw the opposite conclusion from it.
- **Length and non-emptiness pass**, as they did for F28 and F32.

> Every check that validates the *shape* of the answer or the *presence* of its
> tokens passes this case. Only a check that compares the **claim** against the
> **passage's meaning** catches it. That is the design problem.

---

### D1 — Extractive span check

Require each claim to carry a verbatim span from its cited passage; verify the
span occurs in that passage byte-for-byte.

*Attacks:* F32 (no span → malformed), fabricated citations, invented numbers.
*Falsified if:* it does not catch the benchmark case — **and it does not**. The
model can quote the deadline sentence exactly and still invert it.
*Cost:* code only. Prompt change to require spans ⇒ R5 (generation prompt).
*Reversible:* yes, a settings flag.
*Honest verdict:* necessary, nowhere near sufficient. Catches F32 and crude
fabrication; misses the class that matters most.

### D2 — NLI entailment check

A small entailment model scores (passage, claim) → entails / neutral /
contradicts. Reject or abstain below a threshold.

*Attacks:* the benchmark case directly. "Applications after 31 March receive
75000" is **not entailed** by "applications must be submitted before 31 March",
and an NLI model is trained on exactly that distinction.
*Falsified if:* a model small enough to run alongside a 1B generator cannot
make the call reliably on French, or on passages this long. Both are real risks
and both are measurable before committing.
*Cost:* **a new runtime model** ⇒ R5 stop-and-propose in its own right. Memory
alongside the existing embedder + reranker + generator on a 3GiB api container
is a live constraint, not a footnote.
*Reversible:* yes — off by default, one flag.
*Honest verdict:* the only candidate that attacks the benchmark case head-on,
and the most expensive.

### D3 — Verification pass by the same 1B model

Per claim, a second call: *"Is this claim stated in this passage? yes/no."*

*Attacks:* the benchmark case, in principle. Verification is a strictly easier
task than generation, and the model is not being asked to compose.
*Falsified if:* the 1B model is no better at verifying than generating — which
F31 gives real reason to suspect, since it already fails to apply rule 3. **This
is cheap to test before building anything**: replay the four near-misses and the
inversion as verification prompts and count.
*Cost:* code only, no new dependency. One extra LLM call per claim — meaningful
latency on CPU.
*Reversible:* trivially.
*Honest verdict:* test it before designing around it. If it works it is by far
the best cost/benefit; if it does not, it fails fast and cheap.

### D4 — Answer-presence gate before generation

Decide *answerability* separately from generation: for the top passages, ask
whether they contain the information the question needs, and abstain if not.

*Attacks:* **F31 at its root.** F31 is not really a generation defect — it is
that nothing in the system ever decides answerability. The cross-encoder cannot
(it scores topical relevance), and the generator will not.
*Falsified if:* it inherits D3's weakness — same model, same size. Or if it
raises `false_abstention_rate` more than it raises `correct_abstention_rate`,
which the split metric now measures directly.
*Cost:* one LLM call per query, before generation. Cheaper than D3 (per query,
not per claim).
*Reversible:* yes.
*Honest verdict:* attacks the right layer. Shares D3's dependence on 1B
judgement, so **D3's cheap test settles both**.

### D5 — Malformed-generation guard  *(F32 only — separable)*

Non-citation content below a trivial length ⇒ failed generation ⇒
`NO_ANSWER_MESSAGE`.

*Attacks:* F32 exactly. Nothing else.
*Falsified if:* it fires on legitimate terse answers. Measurable against the
golden set.
*Cost:* trivial. No prompt change, no new dependency, no extra call.
*Reversible:* yes.
*Honest verdict:* **not a groundedness fix and should not wait for one.** It is
a correctness bug with a five-line fix. Recommend landing it independently of
this proposal.

---

### Recommended sequence, not a decision

1. **Run D3's cheap test first.** Replay the four F31 near-misses and the
   benchmark inversion as *verification* prompts to the same 1B model, and
   count. It costs one script and settles whether D3 and D4 are viable at all
   before either is designed.
2. **Land D5 now**, independently. It is a separable correctness bug.
3. **D1 as the floor** — necessary regardless, and it makes D2/D3 cheaper by
   giving them a claim/span pair to check rather than free text.
4. **D2 only if D3's test fails**, because it is the only remaining candidate
   that attacks the benchmark case, and it carries a new-runtime-model
   decision under R5.

### Reversibility — a standing requirement

Whatever lands must be switchable off, the way C3 left `rerank_score_floor`
restorable at `0.0` with a test pinning the old behaviour.

> A groundedness check that cannot be switched off is a groundedness check
> nobody can measure the cost of.

Concretely: a settings flag per mechanism, defaulting **on**, with a test that
disabling it reproduces the pre-2.4 behaviour exactly — and both states in the
provenance tuple, so a baseline recorded either side is flagged as semantic
drift rather than silently diffed.

### How it gets measured

The instrument already exists and C3 made it sensitive:

    correct_abstention_rate   must RISE  (F31: 8 of 10 unanswerable leak today)
    false_abstention_rate     must NOT rise materially — the trade this
                              proposal is most likely to lose
    hit_at_k / mrr_at_k       must not regress

Plus a new counted outcome per entry, following the F28 pattern:
`n_rejected_as_ungrounded`, with the rejected text kept for forensics — so a
guard that is silently rejecting everything is visible as a count rather than
inferred from a metric moving.

**Caveat carried from the metric-limitation note:** `correct_abstention_rate`
counts outcomes, not reasoning. It cannot tell a genuine abstention from an
abstention-by-misreading, so it can register success for the wrong reason. The
per-entry forensic record is what makes that inspectable.


## Gating corrected — ordering headroom is NOT tier-A-gated
Directed by the maintainer, correcting an over-gate I recorded as directed
without questioning.

I wrote that C2, C4 and C1+#30 were tier-A-only because reciprocal rank was
1.0 in 15/15 on tier B. The maintainer's correction: that conflated two
different requirements.

| genuinely tier-A-gated | NOT tier-A-gated |
|---|---|
| absolute threshold VALUES (the absent-specific abstention bar, C4's normalised cut) | **ordering headroom** |
| headline baseline credibility | |
| real FR / OCR / table coverage | |

Ordering experiments need candidate pools where chunks **compete for rank 1** —
that is corpus **scale and topical redundancy**, not human authorship. I gated
on tier A because the probe happened to demonstrate divergence there, which was
the wrong feature to generalise from.

### Tier C — the repository's own documentation

`docs/`, the audit report, this log, the runbooks. Real human prose, deep
headings, genuine near-duplicate content across sessions, clean licensing,
already on disk. Manifested and checksummed exactly like tier B, reported
**separately from both A and B**.

It does **not** replace tier A: English-only, technical register, no PDF, no
OCR, no tables.

**Gating pre-test, before any questions are authored:** measure whether
`mrr_at_k` diverges from `hit_at_k` on tier C. If it does not, tier C does not
unblock the ordering experiments either, and that must be known before
investing in questions.

Tier-C questions must target specifics **only a reader of these documents could
know** — finding numbers, commit SHAs, measured values — so that a full-mode
answer cannot come from the model's generic RAG knowledge instead of from
context.

### 3.1 refiled: UNBLOCKED, not indefinite

Index tuning needs **many** vectors, not realistic ones. A deliberately
synthetic scale corpus, generated to a target count and never committed, is
sufficient: at 100k+ vectors `m` / `ef_construct` / `ef` become measurable,
where at 372 they were below `full_scan_threshold` and unmeasurable by
construction. Separate workstream, no longer deferred.

### Shape classifier — retire it for tier B, do not rebuild it

The heuristic (≥3 lines, <8 words/line) conflates bulleted prose with tables,
which is why the "list" bucket spanned 0.0136–0.9998 and could not be quoted.
`generate_tier_b.py` **knows what shape it emitted** — ground-truth shape labels
belong in the manifest at generation time. The heuristic stays only where
ground truth is unavailable (tier A, tier C, the production collection), and
every reported figure must say **which source it came from**.

## [P-3 / D3] Viability test — FAILED, and the control says why
Status: DONE · D3 and D4 are both dead as designed · D5 landed (`7e26d56`)

### The test design was wrong first, and the maintainer caught it

My first design replayed only the four near-misses and the inversion — every
case a rejection. **A model that answers "no" to everything scores 5/5.** That
is the same trap as `correct_abstention_rate = 1.000` while abstaining on 68%
of answerable questions, which I had caught myself and then reproduced.

Corrected as directed: both directions, claim presented as a standalone
proposition rather than self-review, EN and FR reported separately, confusion
matrix rather than an accuracy figure.

### Result: 0 acceptances out of 16

    [all] n=16              accepted   rejected
      should accept              0         11    <- good answers killed
      should reject              0          5

    [en] n=12   0 accepted / 8 positives
    [fr] n=4    0 accepted / 3 positives

It rejected **"Disposal requires written authorisation from the records
officer"** against a passage containing that sentence **verbatim**.

Read naively this is "D3 is a refusal machine" — exactly the outcome the
maintainer predicted the negatives-only design would have hidden.

### The control: it is not judging at all

Before declaring D3 dead I checked whether this was a prompt artifact rather
than an inability, because **D4 shares the framing** and the distinction
changes what D4 is worth.

    CONTROL 1  claim IS the passage, word for word
               "The sky is blue." / "The sky is blue."      -> NO
               real passage, identical claim                -> NO
               verbatim sentence from the passage           -> NO

    CONTROL 2  label mapping FLIPPED (YES now means "contradicts")
               supported claim   (expect NO)                -> NO
               contradicted claim (expect YES)              -> NO

    CONTROL 3  no YES/NO framing, open question
               "How long are records retained?"
               -> "Records are retained for seven years from the date of creation."

> **"NO" is a fixed token, not a decision.** Control 2 settles it: with the
> labels inverted the model should have said YES at least once, and did not.
> Control 3 settles the other half: the model reads the passage perfectly and
> answers correctly when not forced into a binary verdict.

### What this actually means

The failure is **specific to the constrained binary-verdict framing**, not to
comprehension. Consequences:

- **D3 is dead as designed.** Not because the model cannot verify, but because
  it cannot be steered into emitting a verdict token.
- **D4 is dead for the same reason**, without needing its own test. It asks for
  the same kind of binary judgement ("does this passage contain the answer?").
  That settles the D3/D4 asymmetry the maintainer raised — it is moot.
- **D1's value goes UP.** Control 3 shows the model performs well in exactly
  the mode D1 needs: open-ended extraction from a passage.

### New candidate D6, derived from the control rather than assumed

Elicit the supporting sentence **open-ended** — the mode that demonstrably
works — then verify it mechanically, which needs no model judgement at all:

    1. the generator emits, per claim, a QUOTE from the cited passage
       (open-ended extraction — Control 3's mode)
    2. the quote is checked to occur in that passage, byte-for-byte
       (pure string matching, no model in the loop)
    3. no quote, or a quote that does not occur -> the claim is unsupported

This is D1's mechanism with D3's intent, avoiding the failure both D3 and D4
run into. It is **not** a complete answer to the benchmark inversion — the
model can still quote the deadline truthfully and draw the wrong conclusion —
so D2 remains the only candidate that attacks that case head-on.

**Not implementing D6.** P-3's discipline was to propose and let the maintainer
decide, and D6 arrived after approval. Recorded for decision alongside D2.

## [P-3 / D1+D6] Measured — it is a GENERATION REGRESSION, and it ships OFF
Status: implemented, tested, **disabled by default** · commit `b523f9d`

### Both directions, 15 positives / 5 negatives

    EMISSION RATE   positives  3/15 emitted a quote
                    negatives  2/5
    MATCH RATE      positives  0/3      negatives  0/2
    OUTCOME         positives kept 0/15      negatives kept 0/5
    REASONS         positives {no-quotes: 11, quote-not-found: 3, no-citations: 1}

Splitting emission from matching is what made this readable, exactly as
directed: **emission is the failure, not matching.** Eleven of fifteen never
produced a quote at all. An aggregate "0/15" would have looked like a strict
checker rather than a generator that stopped working.

### The raw output showed something worse than "did not quote"

    Q  "How long are records retained?"
       passage: "Records are retained for seven years from the date of creation."
    A  "I could not find this information in the provided documents. [1]
        SUPPORT:
        [1] [1]"

The model **abstained on questions it answers correctly without rule 5** —
rule 3 firing on an answerable question, the opposite failure from F31.

### Control: rule 5 CAUSED it

Same 15 questions, same passages, same model. Only the prompt rule differs.

    base prompt (4 rules)   answered 13/15   abstained  2/15
    with rule 5             answered  2/15   abstained 13/15

Thirteen questions flipped from answered to abstained. Base-prompt answers for
those were correct and cited:

    "According to [1], records are retained for seven years from the date of
     creation, and disposal requires written authorisation..."
    "According to [1], an incident must be reported within 24 hours of discovery."

> **The SUPPORT requirement is a generation regression on a 1B model, not a
> grounding mechanism.** Asking it to produce a structured second section
> destroyed its ability to answer at all.

### Shipped OFF, not deleted

`require_support_quotes` now defaults to **false**, with a test asserting the
default. The verification code is correct and passes 17 unit tests; it would
work against a generator that can satisfy the output contract. Leaving it in
place, off, costs nothing and makes it viable on a larger model without a code
change. The maintainer's standing reversibility requirement is what made this a
one-line default flip rather than a revert.

### My unit tests passed and proved nothing about this

All 17 grounding tests were green when the mechanism was measured at 0/15.
They feed **well-formed SUPPORT blocks to the parser** — they verify the
checker, never the generator's ability to produce input for it.

That is the same class of gap as finding #28: a guard validated against the
shape it expects rather than the input it will actually receive. I wrote the
F28 note about exactly this and then built it again one commit later. The
lesson that generalises: **a component test of a checker is not evidence the
checked-for thing occurs.**

### Where P-3 now stands

    D1+D6   implemented, correct, DISABLED — generation regression on 1B
    D2      OPEN — the only remaining candidate
    D3      dead: fixed "NO" token under any binary-verdict framing
    D4      dead: shares D3's framing, settled without its own test
    D5      LANDED (`7e26d56`) — malformed-generation guard, on by default

> **Finding #5 has no viable fix on llama3.2:1b using prompt-level or
> self-check mechanisms.** Three independent measurements now say so: the
> generator will not apply rule 3 (F31), cannot be steered into a verdict token
> (D3 control), and cannot satisfy a structured output contract without
> collapsing (D6 control). What remains is D2 — an external entailment model —
> or a larger generator, which Appendix B forbids as a substitute for fixing
> grounding.

That is a real constraint on the system as configured, and it belongs in the
handoff rather than in a backlog.

### D2's settling measurement — FILED, NOT CLOSED

Phase 3 or post-handoff, as directed. The measurement that would settle it:

- a small NLI model on the **French** benchmark inversion,
- at **this passage length**,
- fitting alongside embedder + reranker + generator in a **3GiB** container.

Three unmeasured risks plus an R5 new-model decision. **If tier A lands, real
bilingual documents are exactly what would test the first two.**

## [P-3 follow-up] Is the four-rule prompt already near the ceiling? YES — F33
Status: MEASURED and FILED. Prompt NOT changed — R5.

Rule 5 collapsing answers 13/15 -> 2/15 was a very large effect for one added
rule, so the maintainer asked whether the *existing* prompt is already costing
answers. Same 15 positives, same passages, same model; the only variable is
which rules are present.

    STRIPPED (rules 1-2 only)        answered 15/15   abstained  0/15
    SHIPPED  (rules 1-4)             answered 12/15   abstained  3/15
    WITH RULE 5 (rules 1-5)          answered  2/15   abstained 13/15

**The abstention and concision rules cost three answers** on questions the
corpus demonstrably answers:

    "How often are parking permits reissued?"        b12 states it verbatim
    "What is happening in the lobby?"                b12 states it verbatim
    "How long are records kept and who signs off
     on destroying them?"                            two claims, one passage

Filed as **finding #33 (P2)**. Not fixed: the generation prompt is R5
territory, and the approval given covered only D1's rule 5.

### Three caveats that bound the claim

1. **Cannot attribute to rule 3 vs rule 4.** The stripped prompt dropped BOTH
   the abstention rule and the concision rule. Isolating them needs two more
   runs, which is cheap and worth doing before anyone edits the prompt.
2. **Single sample on a nondeterministic model.** The base prompt scored 13/15
   in the rule-5 control an hour earlier and 12/15 here. The model produces 3-5
   distinct outputs per input at `temperature=0.1`, so the 3-answer gap carries
   at least ±1 of noise. The *direction* is consistent; the magnitude is not
   pinned.
3. **n=15**, hand-authored, English-dominant.

### What it does settle

The rule-5 collapse is **specific to the structured-output contract**, not to
prompt length or rule count. Going 2 rules -> 4 rules costs 3 answers; going
4 rules -> 5 rules costs 10 more. That is not a linear degradation, and it
supports the handoff's framing: the model tolerates instructions about *what to
answer* and fails on instructions about *how to shape output*.

It also means the system carries a real, measured trade today: rule 3 exists to
make the model abstain when context is missing, and F31 measured that it does
not do that (0/4). So rule 3 is currently paying a cost of ~3 answers in 15
while delivering none of its intended benefit. **That framing is the finding**,
and it is a maintainer decision, not a cleanup.

## [R5] Ollama runtime upgraded 0.9.3 -> 0.32.5 — embedding vectors survived
Status: DONE · pinned BY DIGEST · runbook `docs/RUNBOOK-ollama-upgrade.md`

Approved as a second R5 item after the generation-model upgrade turned out to
be blocked behind it: `qwen3.5:2b` and `qwen3.5:4b` resolve in the registry
(200; weights 2.74 GB and 3.39 GB; config digests recorded) but `ollama pull`
returns **HTTP 412 "requires a newer version of Ollama"** on 0.9.3. Reported
rather than substituted — an adjacent model that happens to pull on 0.9.3 would
answer a different question than the campaign exists to settle.

    old  ollama/ollama@sha256:45008241d61056449dd4f20cebf64bfa5a2168b0c078ecf34aa2779760502c2f  (0.9.3)
    new  ollama/ollama@sha256:4dea9fb511947e24a84237bb636b0203abcb2ff0d3fbc7b4ff865deb91362131  (0.32.5)

Pinned by digest, not tag, per finding #25.

### Pre-flight, in the order directed, all before the runtime moved

1. Qdrant snapshot with **verified restore** — 376 points out, 376 back into a
   throwaway collection, throwaway deleted.
2. `nomic-embed-text` digest recorded to a committed file.
3. A fixed probe text's 768-dim vector captured and committed
   (`eval/baselines/embedding-fingerprint.json`).
4. Rollback written into the runbook **first**, with the old runtime digest and
   the snapshot name.

`--verify` was also **self-tested before the upgrade** (deviation `0.000e+00`,
byte-exact), so a bug in the check could not be discovered at the moment of
needing it. That is handoff §1c applied to my own tooling.

### The result, and why the tolerance mattered

    digest      0a109f422b47…  ->  0a109f422b47…     UNCHANGED
    dim         768            ->  768               unchanged
    byte-exact  False
    cosine      0.999999870819
    deviation   1.292e-07        (tolerance 1e-05)

**The digest did not move, so the runbook says proceed.** But the vectors are
**not bit-identical** — and without the explicit tolerance the maintainer
required, `byte-exact: False` would have read as alarming. With it, the number
places itself: `1.292e-07` sits squarely in the floating-point/batching
population (~1e-7), two orders below the 1e-5 threshold and nowhere near the
re-quantization population (~1e-3+).

### What that non-zero deviation actually tells us — worth recording

Identical weights, identical digest, and the embedding function still produces
marginally different floats under a different runtime. So:

> **Embedding output is bit-stable WITHIN a runtime version, not ACROSS one.**
> The retrieval-mode determinism measured earlier (0.0 spread over six passes)
> holds for a fixed container, which is what CI compares. It would not survive
> a runtime bump, and a future baseline diff across one should expect
> ~1e-7-scale vector noise rather than treating it as drift.

That is below any threshold in the system and changes nothing today. It is
recorded because the next person to see `byte-exact: False` deserves to know it
was measured and dismissed on evidence rather than overlooked.

## F35 (P1) — abstention detected by exact string, so a self-worded decline leaks
Status: OPEN, filed not fixed

Flagged by the maintainer while reading F31's qwen3.5:4b result. Confirmed in
the code, and it is worse than one call site.

`NO_ANSWER_MESSAGE` is compared **verbatim** at three places:

    query.py:443   "citations": prepared.citations if answer != NO_ANSWER_MESSAGE else []
    query.py:371   abstained=(answer.strip() == NO_ANSWER_MESSAGE)
    query.py:390   the grounding guard skips when answer == NO_ANSWER_MESSAGE
    query.py:420   the malformed guard skips likewise

The measured case, from the battery's F31 suite on qwen3.5:4b:

> *"The provided context does not specify what happens to an incident after it
> escalates to the duty supervisor; it only states that unresolved incidents
> escalate after 72 hours."*

That is a **correct decline**. It fails every comparison above. Consequences:

1. **Citations stay attached** — the user sees a refusal presented with five
   sources, implying the answer came from them.
2. **Telemetry counts it as an answer**, so `abstained` under-reports exactly
   the behaviour the system is trying to encourage.
3. **It gets cached as an answer**, so the decline is replayed to later callers
   with the same citations.

### Why this stayed invisible until now

On `llama3.2:1b` the model **never** declined (F31: 0 of 4), so the branch was
unreachable in practice. The exact-match check is **load-bearing and
model-dependent**: it worked only because the model it was written against
could not follow rule 3 at all. A generator that declines *better* breaks it.

That is the same shape as findings #27 and #33 — a mechanism that looked
correct because the thing it guards against never occurred.

### The fix is structural, not a longer string list
Not implemented, because it changes user-visible behaviour and deserves a
decision rather than a quiet edit. The wrong fix is fuzzy-matching decline
phrasings, which reintroduces semantic judgement. The right shape:

> **A decline is an answer that attributes nothing.** If the answer body
> contains no citation markers, the citations array must be empty and the turn
> counted as an abstention — regardless of wording.

`services/grounding.py` already computes exactly this (`reason ==
"no-citations"`), so the signal exists and is model-independent. It is
currently only consulted when `require_support_quotes` is on.

## F36 (P2) — two caching layers with different hit conditions, neither aware of the other
Status: OPEN, documented not instrumented

Found by a benchmark that produced a physically impossible shape:

    ladder run 1, IDENTICAL prompt每 call
      concurrency=1   218.5s
      concurrency=2    19.0s      <- latency FELL as concurrency rose

Latency cannot fall as contention rises. The cause is Ollama's **KV prefill
cache**: every call used the same prompt, so calls 2..N reused the prefill.
Re-run with a per-call nonce, the shape is monotone and sane
(48.3 / 91.4 / 140.9 / 182.1s at concurrency 1-4).

**This is a property of production, not just of the benchmark.** Two caches now
sit in the path with *different hit conditions*:

| layer | keyed on | effect |
|---|---|---|
| answer cache (`enable_answer_cache`) | exact match on the normalized question + knobs + corpus version | returns the stored answer, no LLM call |
| Ollama prefix cache | the token prefix of the assembled prompt | skips prefill, still generates |

A query that **misses** the answer cache can still **hit** the prefix cache and
return several times faster than a novel one — because the assembled prompt
shares its context blocks with a previous query even when the question differs.
Neither layer is instrumented for the other's effect, so a latency measurement
cannot currently attribute a fast response to either.

Consequences to carry:

- **Never benchmark with a fixed prompt.** Any latency number taken that way is
  a cache-hit number. The stability probe now varies a nonce per call and says
  so in the docstring.
- Real-world latency depends on **query diversity**, which no metric records.
  A corpus of similar questions will look far faster than a diverse one.
- Disabling the answer cache for full-mode eval (already done, and required)
  does **not** disable the prefix cache. Full-mode variance measured with
  repeated questions is still partly measuring a cache.


## F37 (P1) — admission control admits ~3x what the timeout tolerates
Status: OPEN · config-only fix · independent of the generator decision

    measured, cache-defeated, full-context prompts (~7,700 tokens)
      concurrency 1    worst  48.3s
      concurrency 2    worst  91.4s
      concurrency 3    worst 140.9s
      concurrency 4    worst 182.1s
      => ~+45s per additional concurrent request, linear
      => crosses llm_read_timeout=300s at concurrency ~6-7

`max_concurrent_queries = 20` (`config.py:239`, the semaphore at
`api/routers/query.py:31`).

> The gate admits roughly **three times** what the timeout tolerates. Requests
> past the crossing are admitted **only to time out** — which is strictly worse
> than the `503 + Retry-After: 5` the semaphore already returns when full. A
> client that is told to retry can; a client that waits five minutes for a
> timeout cannot.

**This is a config defect on any generator.** `llama3.2:1b` had enough latency
headroom to mask it — at a few seconds per query, 20 concurrent never
approached 300s. The mismatch was always there; a slower generator exposed it.
Same shape as findings #27, #33 and #35: a mechanism that looked correct
because the condition it mishandles never arose.

The fix is a number, not code, and should land **regardless of which generator
ships**. The value should come from a measured crossing rather than a fitted
line, so the ladder is being extended to 8 before anything is changed.

## [Stability] Sustained full-context + the extended ladder — F37 fixed from measurement
Status: DONE · `max_concurrent_queries` 20 -> 4

### Sustained FULL-CONTEXT load, the gap the maintainer named

30 min, 2 concurrent, ~7,743-token prompts, **unique per call** so no prefix
cache:

    rounds=22 (44 queries)  errors=0  silent-empties=0  restarts=0  OOMKilled=False
    peak 4.90 GiB   headroom 1.10   CROSSES 6 GiB: False
    latency median 62.1s  max 88.8s   drift 61.2s -> 62.4s over 30 min
    over llm_read_timeout=300s: 0/44

**Peak under sustained full context (4.90) is LOWER than sustained-short
(5.54).** The two did not compose because they are driven by different
variables:

> **Concurrency drives memory; context length barely does.** The short phase
> peaked higher because it ran 4 concurrent (3 queries + an embed); this ran 2.
> KV growth from an 8k context is small against the model's resident footprint.

The composition risk was overstated — by the maintainer in raising it and by me
in accepting the framing.

### Extended ladder, and a repeat of the cold-load artefact

    concurrency=4  worst 332.7s  peak 5.90 GiB   <- CONTAMINATED, see below
    concurrency=5  worst 208.4s  peak 5.54 GiB
    concurrency=6  worst 244.1s  peak 5.46 GiB
    concurrency=7  worst 293.5s  peak 5.56 GiB
    concurrency=8  worst 332.8s  peak 5.57 GiB

Level 4 ran **first**, from a baseline of 0.82 GiB — the model was not
resident, so its 332.7s includes a cold load. Levels 5-8 are warm. The tell is
the same one that exposed the prefix cache: latency **fell** from 4 to 5 as
concurrency rose. Two cold-start contaminations in one investigation, both
caught by the impossible-shape check rather than by discipline.

Warm series, combining both ladder runs:

    concurrency  1     2     3     4     5     6     7     8
    worst (s)   48.3  91.4 140.9 182.1 208.4 244.1 293.5 332.8

Monotone, roughly +40s per additional request. **Crosses llm_read_timeout=300s
at concurrency 8**, with 7 at 293.5s — under, but with no margin at all.

### F37 fixed: 20 -> 4

Not 7. At 7 the worst admitted request takes **293.5s against a 300s budget** —
nothing left for a larger prompt, a slower disk, or a cold model load, and the
cold-load contamination above shows exactly how much a cold load costs. 4 gives
182.1s, about 60% of budget.

A test pins it below the crossing rather than pinning the literal number, so
re-measuring on a different generator does not silently break it.

### The real memory high-water mark: 5.90 GiB of 6.0

Observed at **cold load + concurrency 4** — 98% of the limit, 0.10 GiB spare.
Steady-state under high concurrency is ~5.6 GiB.

> The worst realistic case is not steady load. It is a **cold model load while
> already serving concurrent requests** — a restart under traffic. That is the
> scenario closest to exhausting the container, and it is 0.10 GiB away.

Nothing OOM'd in any phase, and no silent empties appeared under any pressure.
But **8 GiB is the defensible limit for this generator**, not 6.

## [Phase 2.2-pre] Post-C3 assembled-prompt token distribution
Status: DONE · `scripts/prompt_distribution.py`

Measured over **real retrieval** — `QueryService.build_prompt` on chunks the
retriever actually returned — not synthetic text. The D6 lesson applies: a
constructed prompt measures what its author believed the pipeline assembles.

### Valid run: `knowall_eval`, the corpus the golden set targets

    knobs: rerank_top_n=5  parent_char_budget=4000  context_mode=section

    ASSEMBLED PROMPT (system + context + question), n=23
      min=329  p25=346  MEDIAN=5140  p75=5265  p95=5367  max=5375
      over 8192: 0      within 20% of it: 0
      median = 63% of the context budget

**Nothing crosses the 8192 context budget**, and the maximum (5375) sits 34%
below it.

### The shape is BIMODAL, and the mechanism explains it

    p25 = 346          |  the abstention path: C3 returned ONE chunk, or none
    5140-5375 plateau  |  the answering path: C3 returned FIVE

Two populations, not a distribution with a tail. C3 either admits
`rerank_top_n=5` chunks or the abstention floor cuts to nothing — there is no
middle.

**The plateau spans 4%** (5140 to 5375) across the entire upper mode.
`parent_char_budget=4000 x rerank_top_n=5` therefore produces an almost
**fixed-size** prompt on every answering query.

> Consequence for the latency curve: prompt size is essentially **constant on
> the answering path**, so ~48s warm is close to the per-query cost of *every
> real answer* — not an average over a spread. Predictable, and **not reducible
> by trimming outliers**, because there are none. The only lever is the budget
> itself.

### The answer to the over-provisioning question: NEITHER

The maintainer framed two outcomes — median far below the ceiling (bound the
tail) or median near it (the budget is oversized, reducing it is a latency
lever). The measurement lands between them, at **63%**:

- **Not a tail phenomenon.** The distribution is tightly clustered: p25=346
  then a jump to a 5140-5375 plateau. There is no long tail to bound — prompts
  are either tiny (a single small chunk) or essentially full-size.
- **Not systematically oversized either**, in the sense of overflowing. The
  budget is never exceeded and never approached.

But 5140 tokens is the **input to the latency curve**: ~48s warm single-shot at
~7,700 tokens, and prefill dominates. So `parent_char_budget` is a latency lever
whether or not it is a truncation risk — cutting it would cut prefill roughly
proportionally.

> **That trade is retrieval quality against latency, and only eval can settle
> it.** Not tuned here. R3 and the tier-A gate both apply: a value fitted to
> tier B's composition is fitted to the corpus, not the system.

### A measurement error caught in my own script

The first version printed per-chunk token counts under the heading *"the
embedding budget applies here"* and reported **16 chunks over 2048**. That is
wrong. Those are chunks **after context expansion**, which is what enters the
prompt; the embedding budget applies to the chunk **as stored**, before
expansion, and expanded text is never re-embedded. `verify_reindex.py` already
measures the right thing (max ~1056 tokens stored).

Had it been reported as written, it would have looked like an active F19 breach
— 16 chunks silently truncated at embedding time — when no such thing occurs.
Corrected in place, and the heading now names what it measures.

### A second run that is NOT evidence

Also ran against `knowall_collection`, which produced median=4592 (56%) — but
**24 of 32 golden questions returned zero chunks** there, because the golden set
targets tier B and that collection holds the real documents. n=8 prompts from
mismatched questions is not a distribution. Recorded so the number is not
mistaken for a second data point.

## [Phase 2.3] Containment cost — measured on BOTH generators, no cost detected

                        containment OFF   containment ON
    qwen3.5:4b              15/15             15/15
    llama3.2:1b (ships)     13/15             15/15

**No availability cost on either.** The maintainer's prediction held: F33
measured that this model family tolerates instructions about *what to answer*
and collapses on instructions about *output shape*, and a spotlighting clause
sits on the tolerated side. Rule 5 cost 13/15 -> 2/15; the containment clause
costs nothing.

**The +2 on the incumbent is NOT an improvement.** F33 measured the same base
prompt at 12/15 and 13/15 on separate runs, so 13 -> 15 sits inside the
already-measured nondeterminism band for that model. Reporting it as a gain
would be reading noise as signal — the honest claim is "no measurable cost",
not "it helps".

Measured on both because 2.3's effectiveness is generator-dependent like
everything else in P-3, and **`llama3.2:1b` is still what ships**. A defence
that held only on the candidate would have been worthless to the running
system.

## [Phase 4.3] Payload metadata hygiene — 18 fields, one real defect
Status: DONE (the defect) · decisions recorded (the rest)

Audited against the live collection, not the code's intentions. **18 fields,
not 12** — 2.1 added `embed_model` / `embed_model_digest` and F29 widened
`section_title` coverage since the finding was filed.

### The defect: `etag` is FILTERED but was never INDEXED

    delete_stale()  must=[source]  must_not=[etag]      qdrant_store.py:370

`etag` is the staged swap's cut-over condition — it runs on **every ingest** —
and it was not in `REQUIRED_PAYLOAD_INDEXES`, so that delete full-scanned the
collection every time. Now indexed.

Found by asking *which fields appear in a `FieldCondition`* rather than by
profiling, because a full scan on 376 points is invisible until it is not.
That is the same shape as 2.6: the cost is silent and grows with the corpus.

Pinned as an **invariant, not an instance**: a static test parses every
`FieldCondition(key=…)` and every entry of `REQUIRED_PAYLOAD_INDEXES` out of
the source and asserts containment, so a *new* filter on an unindexed field
fails CI. Deliberately static — it reads the file rather than importing the
module, so it runs without `fastembed` and cannot be defeated by a mock.

### Field-by-field decision

| field | points | verdict |
|---|---|---|
| `source` | 376 | INDEXED — selection, deletion |
| `chunk_seq` | 376 | INDEXED — window expansion |
| `section_title` | 162 | INDEXED — parent retrieval |
| `etag` | 376 | **NOW INDEXED** — the defect above |
| `text` | 376 | keep — the payload itself |
| `embed_model`, `embed_model_digest` | 376 | keep — phase 2.1 identity, read by the reindex verifier |
| `page_number` | 214 | **keep** — citation precision, and D1+D6 makes it load-bearing |
| `table_id`, `headers`, `row_range`, `sheet_name` | 76–85 | **keep** — table provenance; same citation-precision argument |
| `file_format` | 376 | keep — used by `verify_reindex.py` reporting |
| `key`, `chunk_index`, `total_chunks` | 376 | **drop candidates** — `key` duplicates `source`+index; the other two predate `chunk_seq` |
| `content_type`, `image_count` | 376 / 210 | **drop candidates** — write-only, never read |

**The drops are NOT applied.** Removing a payload field only takes effect on
reindex, and payload shape is corpus state: dropping five fields is a data
migration, not a code change. 4.1's alias path now makes that safe to do, but
it should ride along with a reindex that is happening anyway rather than
forcing one. Recorded as decided-but-deferred rather than done.

### The coverage gap under any section-based filtering

`section_title` is present on **162 of 376** points. F29 added it to csv, xlsx
and pptx, but **214 points are PDF and still bare** — per-page sections would
be singletons, worse than the ±1 window PDFs use today.

> Any future decision to filter or route on `section_title` inherits a 43%
> coverage floor on this corpus. A filter on it silently excludes every PDF
> chunk, which is the majority.

## F26 CLOSED — tesseract language data vendored and verified
Status: DONE

The base-image digest pinned the tesseract **binary**; it never pinned the
**traineddata**. `apt-get install tesseract-ocr-fra` resolved against Debian's
archive at build time, so a traineddata refresh would have changed OCR output
with no diff anywhere in this repository — and OCR output is corpus content, so
every stored vector and every eval number would have moved silently.

    tesseract-ocr/tessdata @ 4.1.0
      eng.traineddata  23.5 MB  daa0c97d651c19fba3b25e81317cd697e9908c8208090c94c3905381c23fc047
      fra.traineddata  14.2 MB  eac01c1d72540d6090facb7b2f42dd0a2ee8fc57c5be1b20548ae668e2761913

**Standard `tessdata`, not `tessdata_fast`.** The point of vendoring is to PIN
current behaviour; `_fast` would have changed OCR output while claiming to fix
reproducibility.

**The per-language apt packages are no longer installed.** With no system copy
present there is nothing for `TESSDATA_PREFIX` to be shadowed by. The
maintainer's point applies directly: the presence of the right file is not
evidence it is the one being read — the same coincidence that made the
HuggingFace revision pin look like it worked when it did not. Removing the
ambiguity beats testing around it.

### Verified against SILENT GARBAGE, not against non-empty output

    1. MANIFEST    both files match their committed sha256
    2. RESOLUTION  TESSDATA_PREFIX=/opt/tessdata, and
                   tesseract --list-langs reports: "/opt/tessdata/" (2)
    3. CONTENT     b09  61 chars  'ARCHIVED NOTICE ... 75000 dollars.'   3/3 strings
                   b13 117 chars  'AVIS ARCHIVE ... avant le 31 mars.'   4/4 strings

Byte-identical to the pre-change baseline in both languages. A word count would
have passed on garbage; `'plafond'` and `'31 mars'` would not. If the vendored
French model had failed to load while English held, that asymmetry is the only
place the shadowing failure would have shown.

### Two self-inflicted build failures, both the same shape

1. The inline check imported `yaml`, but the layer runs **before**
   `pip install`. It failed the build for the wrong reason.
2. Rewritten as a multi-line `python -c`, shell escaping mangled it — the same
   failure that broke this Dockerfile during finding #25.

Moved into `api/verify_tessdata.py`, the pattern `api/verify_model_pins.py`
already established. The lesson had been learned and written down, and I
reintroduced it anyway by not applying it.

---

## [Phase R0] Make CI pass

CI had failed all four times it had ever run. Both defects were invocation-level;
no code was at fault. Sequenced so each commit left the tree green.

**3e86de6 — the six real mypy errors, no ignores.**
Five shared one cause: redis-py types every command as `Awaitable[Any] | Any`
because one class serves both the sync and async API, and these stores build the
sync client. `integrations/redis_sync.py` narrows once (`as_text`/`as_int`/
`as_list`) with the reason stated, instead of six suppressions that record
nothing and keep suppressing after the types change. The sixth was a latent bug,
not a typing artifact: `next()` on `query_embed`'s **Iterable** (not Iterator) —
correct only if the implementation happens to return a generator. Now
`next(iter(...))`.
Landed BEFORE the invocation fix deliberately: the two CI defects were stacked,
ruff failed first and skipped mypy, so fixing the invocation while these stood
would have moved the failure one step down.

**dd0e860 — both static steps run from the repository root.**
`ruff check --config ../pyproject.toml .` from `backend/` changed how
`src = ["backend"]` resolves, reclassifying first-party imports as third-party:
35 phantom I001 errors. `mypy --config-file ../pyproject.toml` from `backend/`
resolved `files = ["backend/core", …]` against CWD → `backend/backend/core` →
exit 2, every run. Verified by executing the workflow's exact commands from the
workflow's exact directories before pushing.

**b07450b — trivy-action pinned by commit SHA.**
The security job had NEVER initialised: `@0.28.0` names a version that has never
existed (tags carry a `v` prefix), so the runner failed at "Set up job". Two
layers deep behind a job that could never pass, and cited in the audit as a
working CI job. Same pattern as the alias script's unreachable branch, in build
configuration. Filed as P1-8.

**bdfaa88 — split the scan from the gate.**
`security-scan` always runs, never gates, publishes the full CVE list as an
artifact. `security-gate` fails only on HIGH/CRITICAL in application packages.
A HIGH in a hash-pinned Python dependency is fixable in a commit; a HIGH in a
transitive Debian package needs a base-image digest bump, which moves tesseract,
OCR output, corpus content and every eval baseline. One boolean over both would
either block on something no commit can fix or invite softening the gate on its
first execution — which is how a gate becomes decorative.
`scripts/summarise_trivy.py` is a file, not an inline heredoc, because the first
attempt WAS a heredoc and it broke the workflow's YAML parse. Third time an
embedded multi-line command has bitten this repository.

### Result

| job | before | after |
|---|---|---|
| Frontend build + types | success | success |
| Backend lint + types + unit tests | **failure (Ruff)** | **success** |
| E2E (compose + Playwright) | skipped, never run | **success** |
| Image scan (report) | never initialised | **success**, publishes |
| Dependency gate (application) | — | **failure — 22 real findings** |

E2E and the image scan executed for the first time in this repository's history.

### R0 exit: NOT fully met, for a real reason

The gate is red because it found 22 HIGH findings in pinned Python dependencies
(P1-9), all with upstream fixes. Two are not free bumps: `starlette` is pinned
by `fastapi<0.47.0`, and `pillow` sits in the OCR path where output is corpus
content. Both are R5 proposals, and `scripts/verify_ocr.py` makes the pillow
question measurable rather than speculative.

### A sixth self-check failure

While chasing the CVE list I printed `exit=0` from a Trivy run that had reported
`FATAL` — because the command was piped through `tail`, so `$?` reflected tail.
That is the third occurrence of the `| tail` exit-code defect in this
engagement, and the second I have committed myself while auditing for it. Two
concurrent scans also deadlocked on Trivy's cache lock, and the local image scan
timed out on a 10 GB image; the application-layer list was obtained by scanning
the pinned lockfile directly, which is both faster and exactly the gate's scope.

---

## [Phase R1] Shipping-configuration correctness

**R1.1 — the admission ceiling (1af91eb).** F37 RETRACTED, not corrected: it
sized the ceiling against `llm_read_timeout` alone and never asked what else
could bind. Memory binds two levels earlier. Measured on llama3.2:1b — fixed
resident 1.62 GiB, concurrency 1 at 3.87, concurrency 2 at 4.88 (+1.004
marginal), concurrency 3 projected 5.88. Limits re-derived: api 3→5g,
ollama 8→4g, worker 4→2g, declared total 15.5→11.5 GiB against an 11.68 GiB
host. Ceiling 4→1. `core/admission_limits.py` enforces it against the real
cgroup limit, with three inputs (generator, limit, per-request delta) — a
generator lookup alone would have passed the shipping config.

A measurement artifact worth keeping: the first profile was taken *under* the
3 GiB limit and appeared to converge at 2.99 GiB. Raised to 5 GiB the same
workload climbed to 3.87. The plateau was the ceiling, not the workload.

**R1.2–1.5 (6638061).** Four guards that read declarations instead of facts.

  1.2  placeholder refusal extended to all credentials and BOTH entry points.
       The worker ran no checks at all and started on the full placeholder set;
       it is the entry point that writes to the index. Web tier gained its own
       check for the three variables that exist only there.
  1.3  MinIO's functional shipped credentials replaced with placeholders,
       finishing 2.7.
  1.4  the trust/port guard read a variable nothing set (one mention, in a
       compose comment). MEASURED that a container cannot observe host port
       publishing — the socket view is identical for 127.0.0.1 and 0.0.0.0
       mappings — so the declaration is required and its absence FAILS CLOSED.
  1.5  `/ready` added to both allowlists (it was on neither, so no browser
       could reach it), and its remediation text made TRUE rather than
       softened: api/main.py now calls ensure_ready.

**R1.6 — alias bootstrap: PROPOSED, not implemented.** Written into HANDOFF §12
question 2, covering shape, cost to an already-ingested deployment (no
re-embedding; a copy, not a recompute), whether queries can continue (no — the
bootstrap moves the collection being served, unlike the swap which fails safe),
idempotency and the dangerous interrupted state, and downtime. The unreachable
branch at alias_reindex.py:235-238 is DELETED and replaced with an explicit
pre-swap refusal; `--drop-candidate` added for the orphan left by a failed swap.

### Findings filed this phase

P1-10 abstention-path ladder (right number, wrong quantity) · P1-11
recreate-tail 502s (maximally credible on arrival, on the commit that had just
bumped starlette) · P1-12 measuring a resource under the limit being sized ·
P2-8 a test encoding a guard's broken semantics · P2-9 a test asserting a config
value. Method practices 3c and 3d added to HANDOFF §3.

### Self-check failures this phase

Four of my own tests were wrong before the code was: one forbade documenting the
dead variable in a comment; one mis-parsed `const READ_ONLY: RegExp[] = [`; and
two pre-existing tests encoded the pre-R1.4 contract. Plus a live guard test
that reported "started" because `docker compose exec` runs the IMAGE's /app, not
the working tree — the same trap the eval README already warns about.

---

## [Phase R3] Structural cleanup — mostly declined

The brief's default answer was no, and the default held for three of four items.

### DECLINED: consolidating the verification scripts

No concrete hazard could be named. They were forced to reject in Phase D, each
with legible error text, and consolidation would trade a working guard for a
tidier directory. `verify_model_pins`, `verify_tessdata`, `verify_ocr`,
`verify_reindex`, `corpus/verify`, `embedding_fingerprint`, `startup_checks` and
the gitignore guard stay exactly as they are.

### DECLINED: extracting output handling from services/query.py

R2 ALREADY DID IT. `services/output_guard.py` holds the checks; what remains in
query.py is `_guard_output`, a 16-line adapter that calls it, logs the counters
and records them in the trace. Moving the adapter would separate the wiring from
the thing it wires, and the wiring is the orchestrator's job — the file's actual
purpose.

Measured before deciding, rather than assumed:

    82 prepare          75 stream_prepared    46 build_prompt
    44 rewrite          39 answer_prepared    29 _check_grounding
    24 expand_queries   23 _reject_if_malformed  21 _finish
    16 _guard_output    ... 12 others under 20 lines

The two largest are the two request paths, which is what a coordinator is.

`_reject_if_malformed` (D5) stays too, and deliberately: it decides whether a
generation COUNTS as an answer, while output_guard cleans an answer that already
counts. output_guard's own docstring says it "does not decide policy" — folding
a policy decision into it would make that false.

### DECLINED: extracting caching and telemetry

Caching is four methods totalling 37 lines; telemetry is one method of 21. No
defect motivates moving either, and the brief was explicit that absent a defect
the answer is no.

### DONE: the config-flag audit

    DEAD FLAGS: ZERO.

The audit first reported eight, and all eight were artifacts of its own search
path: the four `*_model` fields are consumed by `computed_field` properties
inside config.py, which the search excluded, and `enable_ocr` / `ocr_languages`
/ `ocr_dpi` live in extraction/, which the search omitted. A dead-code audit with
an incomplete search path MANUFACTURES dead code. Verified each by hand.

The tool also first reported ALL 70 flags as dead, because its grep used `|`
alternation without `-E` and BRE read it as a literal pipe. That shape was
impossible enough to catch itself.

Two genuine findings, both PROPOSED not implemented, since changing the
provenance tuple is a behaviour change:

  1. OCR SETTINGS ARE ABSENT FROM PROVENANCE.
     `enable_ocr`, `ocr_languages` and `ocr_dpi` change the text extracted from
     scanned PDFs, therefore the stored vectors, therefore what any eval
     measures. `chunk_size` and `chunk_overlap` affect stored text in EXACTLY
     the same way and are HARD fields. `corpus_manifest_sha256` does not cover
     it — it hashes SOURCE files, not extracted text. Two baselines taken across
     an OCR-setting change would compare as COMPARABLE while measuring
     different corpora. Same shape as the n_answerable gap.

  2. FULL-MODE GENERATION FLAGS ARE ABSENT.
     `llm_num_ctx`, `llm_temperature`, `llm_num_predict`, `llm_enable_thinking`,
     `require_support_quotes`, `min_answer_chars`, `rewrite_min_similarity` and
     the four `strip_*` flags all change the ANSWER, which full mode measures.
     In retrieval mode the LLM never runs, so they are correctly irrelevant
     there — this is the conditional-classification case `llm_model` already
     has.

"Unpinned by tests" turned out to be a weak signal: `strip_output_scaffolding`
appears in it, yet is exercised by a reversibility test that DERIVES the flag
set from Settings rather than naming flags literally — which is the better
design, and the one adopted after the literal-value anti-pattern (P2-9).

### DEFERRED, EXPLICITLY: the five payload-field drops

`key`, `chunk_index`, `total_chunks`, `content_type`, `image_count`. Verified
write-only: no reader, and NO FieldCondition on any of them, so they are not
load-bearing for filtering.

    cost    a full re-ingest of 377 points across 14 documents via in-place
            scripts/reindex.py, which rewrites the LIVE collection and degrades
            retrieval for the whole run
    benefit ~100 KB of payload and a tidier schema. No correctness benefit, no
            performance benefit — nothing is indexed on them

Deferring onto the alias bootstrap (HANDOFF section 12, question 2) rather than
leaving it floating: the original reasoning — "it should ride along with a
reindex that is happening anyway" — is still correct, and the bootstrap is a
migration that will happen anyway. It is NOT deferred onto the alias SWAP, which
does not work; it is deferred onto the bootstrap that would make the swap
possible.

