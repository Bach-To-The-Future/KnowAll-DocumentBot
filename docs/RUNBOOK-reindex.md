# Runbook — phase 2.1 reindex

Rewrites **every point** in a collection so each one records which embedding
model produced its vector. One pass, three jobs:

1. `embed_model` + `embed_model_digest` on every payload (finding #2 / 2.1).
2. `digest_enforcement_from`, which turns "no digest" from *unknown* into
   *escaped the reindex*.
3. Finding #29's extractor metadata (`section_title` on csv/xlsx/pptx), which
   every existing point predates.

Doing these as three separate reindexes would mean three full re-embeddings and
three windows in which the collection is half-migrated.

---

## Before

**1. Back up the VOLUME, and prove it restores.**

> **RETRACTED: the Qdrant-snapshot procedure below.** Qdrant writes snapshots to
> `/qdrant/snapshots`. `docker-compose.yml:43` mounts only
> `qdrant_data:/qdrant/storage`, so snapshots live in the container's writable
> layer and are **destroyed by `docker compose down`** — or any recreate.
> Verified 2026-08-10: a snapshot taken and `--verify`-confirmed was gone
> minutes later.
>
> `--verify` cannot detect this, because it restores within the *same container
> lifetime*. The check and the defect share the assumption that the container
> persists. Every snapshot in this engagement — pre-reindex, pre-Ollama-upgrade,
> pre-clean-room — was written to that unmounted path, so **every destructive
> operation approved on the condition of a verified snapshot was approved
> against a backup that could not survive a container recreate.**

```sh
# Volume-level, survives `docker compose down`:
docker run --rm -v qdrant_data:/src -v "$PWD/backup":/dst alpine \
    tar czf /dst/qdrant_data.tgz -C /src .

# Prove it: extract into a throwaway volume, boot a throwaway Qdrant on it,
# and check the point count. Listing the tar is NOT a restore test.
docker volume create restore_probe && \
docker run --rm -v restore_probe:/dst -v "$PWD/backup":/b alpine \
    tar xzf /b/qdrant_data.tgz -C /dst && \
docker run -d --name restore-probe -e QDRANT__SERVICE__API_KEY=probe-key \
    -v restore_probe:/qdrant/storage qdrant/qdrant:v1.14.1
# then, from a sidecar (the qdrant image ships no curl):
docker run --rm --network container:restore-probe curlimages/curl -s \
    -H "api-key: probe-key" \
    http://127.0.0.1:6333/collections/knowall_collection
docker rm -f restore-probe && docker volume rm restore_probe
```

The superseded snapshot command, kept only so the retraction is legible:

```sh
# DO NOT RELY ON THIS — the artifact does not survive a container recreate.
docker compose exec api python scripts/snapshot.py \
    --collection knowall_collection --verify
```

Point IDs are `uuid5(source:etag:chunk_seq)` and therefore **stable**, which is
what makes the reindex idempotent — and also means it overwrites in place and
there is no second copy of the old vectors. `--verify` recovers the snapshot
into a throwaway collection, compares point counts, and deletes the throwaway;
the source is never touched by the check. A snapshot nobody has restored is a
backup nobody has tested.

**2. Record a pre-reindex baseline in the same session.**

The comparator will **refuse** to diff across the boundary — `embed_model_digest`
is a HARD field — and that refusal is correct. Record it anyway: it is the only
description of the old state that survives.

**3. Dry run.**

```sh
docker compose exec api python scripts/reindex.py --dry-run
```

---

## Run

```sh
docker compose exec api python scripts/reindex.py --confirm
```

It refuses without `--confirm`, and **fails closed on embedding-model identity
before touching anything** — a reindex under a drifted model would bake the
drift into every vector, permanently and invisibly.

One failing document does not abort the run; failures are collected and
reported at the end.

---

## After

The script scrolls the **entire collection** and fails if a single point lacks a
digest or carries an unexpected one. Only on a clean scroll does it print:

```
DIGEST_ENFORCEMENT_FROM=<iso timestamp>
```

Set that in the **api and worker** environment maps in `docker-compose.yml` —
not the shell, which compose does not pass through to containers.

From then on `verify_three_way()` treats a point with no digest as **fatal**
rather than unknown. That is the point: without the marker, "unknown" is
permanent and an unverifiable collection is indistinguishable from a verified
one forever.

Then record a **fresh** baseline. Do not attempt to compare it to a pre-reindex
one.

---

## If it fails partway

**Re-run it.** That is safe and is the intended recovery:

- Point IDs are `uuid5(source:etag:chunk_seq)`, so a document already processed
  is rewritten in place rather than duplicated.
- The staged etag swap removes any point whose etag moved.
- `DIGEST_ENFORCEMENT_FROM` is printed **only** after a full scroll confirms
  every point carries a digest, so a partial run cannot leave enforcement
  switched on against a half-migrated collection.

Do **not** set `DIGEST_ENFORCEMENT_FROM` from a run that reported problems.
Enforcement would turn every missed point into a hard failure at query time.

Restore from the snapshot only if re-running fails repeatedly:

```sh
# inside the qdrant container's filesystem
file:///qdrant/snapshots/<collection>/<snapshot name>
```

---

## Scope

`scripts/reindex.py` operates on `QDRANT_COLLECTION`. To reindex the eval
collection instead, set it for that invocation:

```sh
docker compose exec -e QDRANT_COLLECTION=knowall_eval api \
    python scripts/reindex.py --confirm
```

`eval/ingest_corpus.py` is the eval corpus's own path and refuses to run against
the default collection outright.
