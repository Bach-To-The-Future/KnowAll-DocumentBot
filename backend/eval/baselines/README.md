# Baselines

Each file here is one recorded eval run: a provenance tuple plus the numbers it
produced. `eval/compare.py` diffs two of them and refuses when the tuples say
they are not measuring the same thing.

```
python eval/compare.py baselines/old.json baselines/new.json
```

Exit `0` within tolerance · `1` regression · `2` incomparable.

## Recording one

Three values cannot be discovered from inside the container and must be passed
at the call site. The image build context is `backend/`, so there is no `.git`
to read; a container cannot see its own image id without the docker socket; and
the embedding-model digest is the F24 enforcement input.

```sh
docker compose exec \
  -e QDRANT_COLLECTION=knowall_eval \
  -e KNOWALL_GIT_SHA=$(git rev-parse HEAD) \
  -e KNOWALL_API_IMAGE_ID=$(docker inspect -f '{{.Id}}' knowall-documentbot-api) \
  -e KNOWALL_WEB_IMAGE_ID=$(docker inspect -f '{{.Id}}' knowall-documentbot-web) \
  -e EXPECTED_EMBED_MODEL_DIGEST=<live digest> \
  api python eval/run_eval.py --mode retrieval --runs 3 --out /tmp/b.json
```

`KNOWALL_WEB_IMAGE_ID` was missing from this list, and its absence is what made
the first attempt at a fresh reference baseline self-label DIAGNOSTIC ONLY. The
web tier plays no part in an eval run; it is in the tuple so that "which build
produced this number" has one answer rather than two.

Write to `/tmp` and `docker compose cp` the file out. `eval/baselines/` inside
the image is root-owned and the API runs as `appuser`, so `--out` pointed there
dies on a `PermissionError` — after the run has completed, which wastes the run.

Full mode additionally requires:

- `-e ENABLE_ANSWER_CACHE=false` — the harness refuses to start without it,
  because runs 2 and 3 would otherwise measure the cache.
- `-e EXPECTED_LLM_MODEL_DIGEST=<live digest>` — not refused without it, but the
  run warns and `llm_model_digest` records `"unpinned"`, which makes the file a
  diagnostic. `llama3.2:1b` is a moving tag; the tag alone pins nothing.

## What makes a file a *reference* baseline

Every field of the provenance tuple resolved. In particular:

- `git_sha`, `api_image_digest`, `web_image_digest` — not `"unknown"`
- `reranker_revision`, `bm25_revision` — not `"unpinned"`
- `llm_model_digest` — the live generator digest in full mode; `"not-applicable"`
  in retrieval mode, where the generator never runs. `"unpinned"` there means
  the generator *did* run unidentified, which is a diagnostic, not a reference
- `corpus_manifest_sha256` — matches `eval/corpus/MANIFEST.yaml`
- `embed_model_digest` — the live Ollama digest, verified at run head
- the code in the image matches `git_sha` (rebuild, don't `docker compose cp`)

`"unknown"` and `"unpinned"` are not placeholders the harness fills in
optimistically; they are what the running container actually reported. A file
carrying them is a **diagnostic** — useful for finding defects, useless as a
comparison point. Say which one a file is when you commit it.

**`api_image_digest` is the authoritative identity of the code that ran.**
`git_sha` is the repository pointer at launch and can run *ahead* of the image
— `$(git rev-parse HEAD)` describes the working tree, not the build. Rebuild
before recording, and when two baselines disagree, trust the image digest.

## Naming

    tier-<tier>-<mode>-<YYYY-MM-DD>.json

Mode is `retrieval` or `full`; they are never comparable to each other
(`eval_mode` is a hard field).

## Current files

| file | kind | why |
|---|---|---|
| `tier-b-full-2026-08-04.json` | **provenance-complete, tier-B only** | full mode, 3 passes, cache disabled, F24 fail-closed. Measured spread 0.0 — **not usable as a tolerance**: finding #27 pins 60% of entries at a score that cannot move, so the metric is insensitive to the LLM variation that demonstrably exists. Records `git_sha` two docs-only commits ahead of the image. |
| `tier-b-retrieval-2026-08-04.json` | **provenance-complete, tier-B only** | every provenance field resolves; image rebuilt so its code matches the recorded sha. Usable as a same-tier comparison point for retrieval-mode changes. Not a *headline* baseline — see below. |
| `tier-b-retrieval-2026-08-03.json` | diagnostic (superseded) | recorded before the model-revision env fix, with eval code copied in. Provenance honestly reports `unknown`/`unpinned`. Kept because it surfaced finding #27. |
| `f27-rerank-diagnostic-2026-08-03.json` | diagnostic | not an eval run — per-candidate rerank scores, shapes and rank1/rank2 gaps behind finding #27. Produced by `eval/diagnose_rerank.py`. |

There is **no headline baseline yet**, and there cannot be one until tier A is
populated: tier B alone is deliberately table-, list- and OCR-heavy, so its
numbers describe that composition rather than the system. In particular
`recall_at_fetch = 1.0` there is arithmetic — 18 chunks against
`retrieval_fetch_k = 20` means the fetch stage returns the whole corpus every
time — and it will fall on tier A.

No knob may be tuned against tier-B numbers. Fitting a threshold to a corpus
that is 60% tables and OCR fits the corpus, not the system.
