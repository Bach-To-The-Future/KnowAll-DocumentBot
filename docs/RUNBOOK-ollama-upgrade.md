# Runbook — Ollama runtime upgrade

**R5 item, approved separately from the generation-model upgrade.** It became
necessary because `qwen3.5:2b` and `qwen3.5:4b` resolve in the registry but
cannot be pulled on `0.9.3`:

```
Error: pull model manifest: 412:
The model you are attempting to pull requires a newer version of Ollama.
```

## Why this is not a version bump

The same container serves **`nomic-embed-text`**, whose digest is the F24
identity pin now enforced fail-closed at api startup, worker startup and the
eval head. If the upgrade republishes or re-quantizes that model:

- startup **correctly** hard-fails on the digest mismatch, and
- every committed baseline's `embed_model_digest` becomes INCOMPARABLE.

That is the mechanism working as designed, but it makes this a reindex-scale
event rather than an image tag change.

---

## ROLLBACK — written before anything moved

Everything needed to return to the pre-upgrade state:

| artifact | value |
|---|---|
| runtime image (pinned, by digest) | `ollama/ollama@sha256:45008241d61056449dd4f20cebf64bfa5a2168b0c078ecf34aa2779760502c2f` (= `0.9.3`) |
| Qdrant snapshot, restore-VERIFIED | `knowall_collection-186674847162446-2026-08-05-12-14-54.snapshot` (376 points out, 376 restored, 9.7 MB) |
| embedding digest | `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f` |
| embedding fingerprint | `eval/baselines/embedding-fingerprint.json` — probe text + its 768-dim vector |

To roll back:

```sh
# 1. restore the runtime pin in docker-compose.yml, then
docker compose up -d --force-recreate ollama

# 2. only if the collection was reindexed under a changed model:
#    restore inside the qdrant container from
#    file:///qdrant/snapshots/knowall_collection/<snapshot name above>
```

---

## Order of operations — do not reorder

### Before touching the runtime

1. `docker compose exec api python scripts/snapshot.py --collection knowall_collection --verify`
2. `docker compose exec -e FINGERPRINT_PATH=/tmp/f.json api python scripts/embedding_fingerprint.py --capture`
   then copy it to `eval/baselines/embedding-fingerprint.json` and **commit it**.
3. This document, with the rollback filled in.

All three are done. Their values are in the table above.

### Pin the new runtime BY DIGEST, not by tag

Consistent with finding #25. A tag is republished; a digest is not. Record the
tag in a comment for readability, exactly as `api/Dockerfile` does.

### Immediately after the upgrade — BEFORE pulling any generator

> **This window no longer opens by itself, and you have to force it.** Two
> changes closed it, neither of them intended to:
>
> 1. The ollama `entrypoint` in `docker-compose.yml` **auto-pulls both models**
>    on start (`… || ollama pull nomic-embed-text ; … || ollama pull
>    llama3.2:1b`). So `docker compose up -d --force-recreate ollama` — the
>    rollback command in this very runbook — arrives with the generator already
>    present.
> 2. Since `9f821b3` (finding F4/F5) the healthcheck **requires both models
>    resident** before reporting healthy. A container deliberately held without a
>    generator now reads as unhealthy, which is correct for normal operation and
>    inconvenient here.
>
> To hold the window, start ollama with the auto-pull bypassed and only the
> embedder present:
>
> ```sh
> docker compose run --rm --entrypoint "" -d --name ollama-probe ollama >     bash -c "ollama serve & until ollama list >/dev/null 2>&1; do sleep 1; done; >              ollama list | grep -q '^nomic-embed-text ' || ollama pull nomic-embed-text; wait"
> # fingerprint against this container, then remove it and bring the stack up normally.
> ```
>
> **Do not weaken the healthcheck to make this step convenient.** Its whole
> purpose is that `up -d --wait` must not report ready while the generator is
> absent — that was F4, and it made the generator-identity guard a no-op in
> exactly that window.

```sh
docker compose exec api python scripts/embedding_fingerprint.py --verify
```

**Unchanged** → proceed to the generator.

**Moved** → STOP. Report before proceeding. Then let the same command's
discriminating test decide what kind of change it was:

| result | meaning | action |
|---|---|---|
| cosine ≈ 1.0 against the stored probe | republish carrying the same weights; metadata moved | update `EXPECTED_EMBED_MODEL_DIGEST`; collection intact; baselines stay comparable |
| cosine < 1.0 | **re-quantization** — every stored vector was produced by a function that no longer exists | collection invalidated; reindex + fresh baselines; **maintainer decision** |
| dimension changed | collection unusable | reindex, unconditionally |

**Do not assume which case you are in.** The digest moving tells you the
artifact changed; it says nothing about whether the vectors did.

### Then, and only then

Pull the generator, verifying its tag and digest empirically against the
registry rather than from memory. Run `scripts/generator_battery.py`
**unmodified** — it reproduces the exact suites that established the 1B
constraint, so the numbers are directly comparable.

---

## What this cannot change

Finding #27 and the cross-encoder half of finding #31 — that a cross-encoder
scores **topical relevance**, not **answer presence** — live in
`bge-reranker-base`, which runs in the **api** container and is untouched by
this. They stay open whatever the battery reports.
