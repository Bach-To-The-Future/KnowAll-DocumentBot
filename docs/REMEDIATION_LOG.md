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
