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
  -e EXPECTED_EMBED_MODEL_DIGEST=<live digest> \
  api python eval/run_eval.py --mode retrieval --runs 3 --out /tmp/b.json
```

Full mode additionally requires `-e ENABLE_ANSWER_CACHE=false`; the harness
refuses to start without it.

## What makes a file a *reference* baseline

Every field of the provenance tuple resolved. In particular:

- `git_sha`, `api_image_digest` — not `"unknown"`
- `reranker_revision`, `bm25_revision` — not `"unpinned"`
- `corpus_manifest_sha256` — matches `eval/corpus/MANIFEST.yaml`
- `embed_model_digest` — the live Ollama digest, verified at run head
- the code in the image matches `git_sha` (rebuild, don't `docker compose cp`)

`"unknown"` and `"unpinned"` are not placeholders the harness fills in
optimistically; they are what the running container actually reported. A file
carrying them is a **diagnostic** — useful for finding defects, useless as a
comparison point. Say which one a file is when you commit it.

## Naming

    tier-<tier>-<mode>-<YYYY-MM-DD>.json

Mode is `retrieval` or `full`; they are never comparable to each other
(`eval_mode` is a hard field).

## Current files

| file | kind | why |
|---|---|---|
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
