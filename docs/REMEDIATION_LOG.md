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
