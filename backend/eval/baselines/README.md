# Baselines

Each file here is one recorded eval run: a provenance tuple plus the numbers it
produced. `eval/compare.py` diffs two of them and refuses when the tuples say
they are not measuring the same thing.

```
python eval/compare.py baselines/old.json baselines/new.json
```

Exit `0` within tolerance · `1` regression · `2` incomparable.

## What makes a file a *reference* baseline

Every field of the provenance tuple resolved. In particular:

- `git_sha`, `api_image_digest` — not `"unknown"`
- `reranker_revision`, `bm25_revision` — not `"unpinned"`
- `corpus_manifest_sha256` — matches `eval/corpus/MANIFEST.yaml`
- `embed_model_digest` — the live Ollama digest, verified at run head

`"unknown"` and `"unpinned"` are not placeholders the harness fills in
optimistically; they are what the running container actually reported. A file
carrying them is a **diagnostic**, useful for finding defects and useless as a
comparison point. Say which one a file is when you commit it.

## Naming

    tier-<tier>-<mode>-<YYYY-MM-DD>.json

Mode is `retrieval` or `full`; they are never comparable to each other.

## Current files

| file | kind | why |
|---|---|---|
| `tier-b-retrieval-2026-08-03.json` | **diagnostic** | recorded from a container built before the model-revision env fix, with eval code copied in. Provenance honestly reports `unknown`/`unpinned`. Recorded to prove the harness works and to surface finding #27; not a comparison point. |

There is no reference baseline yet. One needs tier A, which is not populated.
