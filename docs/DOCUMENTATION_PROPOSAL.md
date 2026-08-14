# Documentation proposal

2026-08-14. **Nothing deleted in this pass.** D1–D6 apply: the default is keep,
and removal requires a positive case.

**Result up front: nothing is proposed for deletion or archiving. Not one file.**
Every document examined is either load-bearing, evidence for a live retraction or
open question, or costs nothing to keep. The **"genuinely superseded" category is
empty**, and this document says so rather than manufacturing an entry to justify
the audit.

**What the audit did find is six contradictions, four of them in the entry
point, and three of them created by work landed in the last two days.** That is
the real hazard the brief names — a claim contradicted elsewhere, not a redundant
one. They are corrections, not removals.

---

## The provenance constraint, resolved first

The last pass ended with *"MANIFEST.yaml has no free edits — check whether others
exist."* Searched every `sha256`/`hashlib`/`checksum` site in `backend/`:

| file | pinned by | free to edit? |
|---|---|---|
| `backend/eval/corpus/MANIFEST.yaml` | `manifest_sha256` — HARD provenance **and** the etag every point ID derives from | **NO.** A comment edit forces a re-ingest and invalidates both baselines. |
| `backend/eval/corpus/tier-b/*` — **including `b02-handbook.md`** | per-document `sha256` in that manifest | **NO.** The only markdown in the repository that is byte-pinned. |
| `backend/vendor/tessdata/MANIFEST.yaml` + `*.traineddata` | `api/verify_tessdata.py` | **NO** (build gate). |
| **everything under `docs/`** | nothing | **yes** |
| `backend/eval/baselines/README.md` | nothing — `corpus/verify.py` lists `README.md` in `NON_DOCUMENT_NAMES`, and it lives outside the corpus tree anyway | **yes** |

**So every recommendation below is free to apply.** The one markdown file that is
pinned, `b02-handbook.md`, is a corpus *fixture*, not documentation, and appears
in no recommendation.

---

## 1 · Inventory

"Last substantive update" is the last commit touching the file; commit count
indicates whether it is maintained or written-once.

| file | lines | last | commits | what becomes unanswerable if it is gone |
|---|---|---|---|---|
| `docs/HANDOFF.md` | 1095 | 08-14 | 15 | Everything a new engineer needs, and **the retractions**. Six claims are retracted here and nowhere else; deleting it turns each into an unsupported assertion. |
| `docs/REMEDIATION_LOG.md` | 3205 | 08-13 | 35 | *When* each finding was seen and what was tried. The only chronological record; the audits give conclusions, not sequence. Cited by `HANDOFF`, `MANIFEST.yaml`, and this pass. |
| `docs/RAG_FIELD_GUIDE.md` | 1141 | 08-14 | 3 | The transferable method — the 12 measurement rules. Written for a reader who never sees this repository; nothing else is addressed to them. |
| `docs/FINAL_AUDIT.md` | 883 | 08-13 | 10 | The severity-ranked findings (P0–P3) **and the anti-pattern catalogue P2-8…P2-18**, referenced by ID from the field guide, the handoff and `admission_limits.py`. |
| `docs/PRUNING_PROPOSAL.md` | 478 | 08-14 | 5 | Why 41 candidates were *not* removed. Its whole purpose is to stop the next person re-auditing them; it is also cited from `api/Dockerfile`. |
| `docs/FINAL_VERIFICATION.md` | 320 | 08-14 | 4 | Whether the assembled system worked **after** the changes, and F1–F5. Answers "does the audit's verdict still hold?" — a question the audit cannot answer about itself. |
| `docs/RAG_EVOLUTION.md` | 274 | 07-30 | 1 | The technique landscape *not* adopted here — HyDE, ColBERT, GraphRAG, agentic RAG, multimodal — with notes on when each earns its complexity. Nothing else surveys the road not taken. |
| `docs/rag_fact_sheet.yaml` | 248 | 08-14 | 3 | Every shipped value in one machine-readable place, re-derived at R4. The only structured (non-prose) statement of configuration. |
| `docs/RUNBOOK-reindex.md` | 154 | 08-11 | 2 | The **verified-restore** backup procedure and why re-running a reindex is the recovery path. Carries the P0-2 rewrite. |
| `docs/RUNBOOK-ollama-upgrade.md` | 100 | 08-05 | 1 | The rollback digest, and the discriminating test for *what kind* of embedding-model change occurred. Unreconstructable — the pre-upgrade digest is recorded nowhere else. |
| `backend/eval/baselines/README.md` | 94 | 08-14 | 5 | What makes a baseline a *reference* rather than a diagnostic. **Cited from running code** (`run_eval.py:591`). |
| `docs/LOCKFILES.md` | 59 | 07-30 | 1 | That lockfiles must be regenerated **in Docker**, not on a laptop. |
| `infra/README.md` | 23 | 07-30 | 1 | Why `docker-compose.yml` sits at the repository root — a decision someone would otherwise re-open. |
| `backend/eval/corpus/tier-b/b02-handbook.md` | 9 | 07-30 | 1 | *Not documentation.* A byte-pinned corpus fixture. Listed only to record that it was examined and excluded. |

Total ≈ 8,100 lines across 13 documents.

---

## 2 · Classification by audience

### Entry point — must be current; duplication here is a hazard

`HANDOFF.md` · `RUNBOOK-reindex.md` · `RUNBOOK-ollama-upgrade.md` ·
`LOCKFILES.md` · `infra/README.md` · `baselines/README.md`

**All six defects below are in this class.** That is not a coincidence: it is the
only class where staleness is a defect at all.

### Evidence — historical by nature; staleness is *not* a defect

`FINAL_AUDIT.md` · `FINAL_VERIFICATION.md` · `REMEDIATION_LOG.md` ·
`PRUNING_PROPOSAL.md`

These record what was true when measured. `FINAL_VERIFICATION.md:36` says *"the
images are 10 GB each"* — now false, and **correctly left alone**: it is a dated
report of a real measurement, and rewriting it would destroy the evidence for the
R-1 saving. The same sentence in `HANDOFF.md` is a defect, because the handoff is
read as current. **Identical text, opposite verdicts, decided by audience.**

### Standalone — written for someone who never sees this repository

`RAG_FIELD_GUIDE.md` · `RAG_EVOLUTION.md`

They do not overlap as much as the line counts suggest. The field guide is
**method** — how to know whether a measurement means anything, drawn from this
engagement's failures. RAG_EVOLUTION is **technique landscape** — what exists in
RAG generally, most of which this system does not use. One tells you how to
measure; the other tells you what you might build.

### Genuinely superseded — **empty**

No file's content is fully absorbed elsewhere. Every candidate examined had at
least one fact that exists nowhere else; those are named in §5.

---

## 3 · Recommended corrections

All are edits, none are deletions.

### E-1 · `HANDOFF.md` §4 states an image size that is now wrong by 2.7× · **HIGH**

> `| docker compose build | **2576.7 s (~43 min)** | with a **warm** Docker layer
> cache; a cold cache is slower. **Both backend images are 10 GB.** |`

Measured today, after `8f65a0e`: **3.68 GB**. This is the setup table in the
entry point — the first number a new engineer uses to decide whether they have
disk for this.

**Fix:** state 3.68 GB, and cross-reference `PRUNING_PROPOSAL.md` R-1 for the
before/after.

**Do not restate the build time.** ~43 min was measured with a warm layer cache;
the two rebuilds since (35m46s, ~35m) both had the model layer *cold*, which is
the opposite condition. **Post-prune warm-cache build time is unmeasured**, and
writing a number that was not measured under the stated conditions is the error
this engagement has been correcting throughout. Either re-measure or mark it
pending.

### E-2 · `HANDOFF.md` §4's `--wait` timing measured the F4 defect · **HIGH**

> `| docker compose up -d --wait | 35.1 s | 7/7 services healthy |`

Written `064c38a` (08-13). F4/F5 was fixed `9f821b3` (08-14). That figure was
therefore produced by the **old** healthcheck — the one that reported healthy
while `llama3.2:1b` was still downloading. It is not a stale measurement of a
stable thing; **it is a measurement of the bug.**

The sequence itself still works, and I checked rather than assumed: the ollama
`entrypoint` (present since 2025-07-08, unrelated to F4/F5) auto-pulls both
models, so `--wait` now blocks until they are resident and the two documented
`ollama pull` lines are fast no-ops. **There is no deadlock** — I expected one
and was wrong.

But on a **fresh** host `--wait` now legitimately takes as long as a ~1.6 GB pull,
not 35.1 s. That is the fix working as designed.

**Fix:** replace the figure with a re-measurement on a fresh volume, or annotate
it as "models already resident; a first run pays the model pull inside `--wait`".

### E-3 · The shared-volume hazard is now stated twice, and I wrote the second one · **MEDIUM**

`HANDOFF.md` §4, note 2 — present before this pass:

> *"Every volume and container in `docker-compose.yml` carries a **global**
> `name:`, so a second checkout on the same host **silently reuses the first
> one's volumes and models**. A fresh clone is not a clean room."*

`HANDOFF.md` §11, P1 — added by me in `8d54820`, without noticing the above.

The two are not identical (§11 adds the `docker volume prune` destruction path,
the 271-dangling-volume count, and a mitigation table), but they share a root
fact, and **this is exactly the entry-point duplication the brief warns about**:
two statements that can drift apart.

**Fix:** merge rather than duplicate — keep §11 as the full entry, reduce §4
note 2 to one line pointing at it. Prefer merging and cross-referencing over
deleting, and note that §4's framing ("a fresh clone is not a clean room") is the
better *sentence*; it should survive into §11.

**Recorded plainly:** I filed a P1 for something the handoff already documented.
Not checking what exists before adding is the same class of error this engagement
has repeatedly found.

### E-4 · `RUNBOOK-ollama-upgrade.md` describes a window that no longer exists · **MEDIUM**

> `### Immediately after the upgrade — BEFORE pulling any generator`

The procedure depends on observing the embedding model *before* the generator
arrives. But the ollama `entrypoint` auto-pulls **both** models on start, and
since `9f821b3` the healthcheck **requires both** before reporting healthy. After
`docker compose up -d --force-recreate ollama` — the runbook's own rollback
command — the generator is already there.

The auto-pull predates this engagement; the healthcheck change did not. Together
they make the runbook's intended ordering unobtainable by the documented steps.

**Fix:** document how to hold the window — recreate with the entrypoint
overridden, or run the fingerprint check against a container started without the
auto-pull. **Not** a code change: the healthcheck is correct for the normal case
(that is F4/F5), and weakening it to make a runbook step convenient would
reintroduce the defect.

### S-1 · `RAG_EVOLUTION.md` §9 makes two claims contradicted by the shipped system · **MEDIUM**

**Claim 1 — a model swap that is not in force.**

> *"Swapping to a multilingual reranker moved hit@5 from 0.857 → 0.952 and
> abstention accuracy from 0.5 → 1.0."*

The shipped reranker is `BAAI/bge-reranker-base` — confirmed in
`core/config.py:245`, in `rag_fact_sheet.yaml:59`, and in the provenance tuple of
`tier-b-retrieval-2026-08-14.json`. That is the **same model the same paragraph
blames** ("`bge-reranker-base`, EN/ZH-trained… scored relevant *French* chunks
near zero"). No multilingual reranker is deployed.

Further: `0.857` appears **nowhere else in the repository**, and `0.952` appears
in `REMEDIATION_LOG.md:1899` as `recall_at_fetch: 0.952 (20/21)` on the 376-point
ad-hoc collection — a different measurement entirely. The before/after pair is
**unsourced here**. I cannot establish it was ever true of this system; the file
has one commit, dated before the engagement.

**Claim 2 — a mechanism that was replaced.**

> *"sigmoid-mapped scores gated by a floor threshold… The floor converts the
> reranker from a sorter into a relevance judge."*

Superseded, and `HANDOFF.md:653` says so:

> *"**The rerank threshold discarded correct answers.** One number decided both
> 'is anything relevant' and 'which is most relevant'… Now split into a very low
> abstention bar plus ranking."*

Shipped today: `rerank_score_floor: 0.0` (off), `abstention_score_floor: 0.01`.
The single-floor mechanism §9 describes is not the mechanism running.

**Fix:** annotate §9 — keep the *reasoning* about cascade shape and empirical
calibration, which is sound and is the section's teaching value; mark the swap
claim as unsupported and point the floor discussion at the field guide's measured
account. **Do not delete the section**, and do not silently restate the numbers:
they have not been re-measured.

### E-5 · `FINAL_VERIFICATION.md` and `FINAL_AUDIT.md` — **do not merge** · recommendation

Examined as instructed. **Merging would lose the distinction and break
references.**

- **Different questions.** `FINAL_AUDIT` asks *what is wrong with this system*
  (883 lines, of which 578 are the severity-ranked findings). `FINAL_VERIFICATION`
  asks *does the audit's verdict still hold after twelve changes* — its closing
  section is literally titled "Has anything changed since the audit's verdict?"
  A document cannot ask that about itself.
- **Different findings, deliberately renumbered.** The audit uses P0-1…P3-n; the
  verification uses F1–F5 precisely so a reader can tell *found* from *confirmed
  later*. Merging collapses that into one voice and the provenance of each finding
  is lost.
- **Referenced by ID from four places.** `P2-18`, `P0-3`, `P1-9` and others are
  cited from `HANDOFF.md`, `RAG_FIELD_GUIDE.md`, `api/requirements.in` and
  `core/admission_limits.py`. A merge renumbers or breaks those.

**Recommendation: keep both, add a one-line pointer at the top of each** naming
the other and the question it answers. That is the cheapest fix for the only real
problem here — that a reader landing on one may not know the other exists.

---

## 4 · Confirmed load-bearing (checked, not re-derived)

The pruning pass asserted these; the brief asked for confirmation rather than a
fresh derivation.

**`docs/LOCKFILES.md` — confirmed, and confirmed *by use*.** The instruction to
compile in Docker exists in three files: `requirements.txt` (as the autogenerated
header — the command, not the reason), `REMEDIATION_LOG.md` (historical), and
LOCKFILES.md. Only LOCKFILES.md gives the rationale:

> *"generate them **in Docker** so the result matches the build image rather than
> whatever is on your laptop."*

Stronger than a grep: **R-3 followed this file two days ago** to regenerate the
hashed lock after removing `minio`. A document used in anger last week is not a
deletion candidate.

**`infra/README.md` — confirmed.** The rationale appears in exactly one other
place, which is the pruning proposal describing *this file*:

> *"`docker-compose.yml` stays at the repository root deliberately: `docker
> compose up` works with zero flags, and build contexts (`./backend`,
> `./frontend`) stay short."*

23 lines, referenced from `HANDOFF.md`. Keep.

**`backend/eval/baselines/README.md` — strongest case of the three.** It is cited
from **running code**: `run_eval.py:591` prints

> `"  This file is not a reference baseline. See eval/baselines/README.md."`

A user is directed to it by the software at the moment they need it. Deleting it
would leave a live error message pointing at nothing.

---

## 5 · Examined and kept

| file | considered because | kept because |
|---|---|---|
| `RAG_EVOLUTION.md` | oldest doc, 1 commit, describes a Streamlit prototype | **It does not document only the prototype.** §6 covers the naive baseline; §§7–11 are shifts still in force; Parts III–IV survey techniques *not* adopted (HyDE, ColBERT, contextual retrieval, GraphRAG, agentic RAG, multimodal, caching) with notes on when each earns its complexity. That survey exists nowhere else. Two claims need correcting (S-1); the file does not. |
| `REMEDIATION_LOG.md` | 3205 lines, largest file, superseded by two audits | **Evidence, and the only chronology.** The audits record conclusions; this records order and what was tried and abandoned. It is the supporting evidence for the §0 retractions — and a retraction whose evidence is gone is an unsupported assertion. |
| `FINAL_AUDIT.md` / `FINAL_VERIFICATION.md` | apparent overlap | See E-5. Different questions, different finding namespaces, IDs cited from code. |
| `PRUNING_PROPOSAL.md` | a completed proposal; work is done | Its "examined and kept" section is the record that stops a re-audit, and its execution table records **two wrong estimates** and one withdrawn item. Deleting a completed proposal deletes the reasoning for the 41 things *not* removed. Cited from `api/Dockerfile`. |
| `rag_fact_sheet.yaml` | duplicates values in `HANDOFF.md` §5 | The only **structured** statement of configuration, re-derived at R4. Spot-checked against the code today: `reranker_model`, `rerank_score_floor: 0.0`, `abstention_score_floor: 0.01` all match `core/config.py`. It carries none of the RAG_EVOLUTION contradiction. Duplication of a *correct* value is not the hazard; contradiction is. |
| `RUNBOOK-reindex.md` | might have drifted like the snapshot procedure | **Checked and current.** It carries the P0-2 rewrite properly, and keeps the superseded command with `# DO NOT RELY ON THIS` so the retraction stays legible. Both referenced scripts exist with the documented flags (`snapshot.py --collection --verify`, `reindex.py --dry-run --confirm`). |
| `RUNBOOK-ollama-upgrade.md` | 1 commit, oldest runbook | Holds the rollback digest and the discriminating cosine test, recorded nowhere else. `embedding_fingerprint.py --verify` exists as documented. One ordering defect (E-4), no reason to remove. |
| `HANDOFF.md` §0 Retractions | the "10 GB" figure inside it is now wrong | **Do not touch the retraction's evidence.** The 10 GB and ~43 min figures there are the *measurement supporting* the "10 minutes" retraction. Correct §4, which is read as current; leave §0, which is read as history. Annotating §0 with a pointer to the new figure is acceptable; overwriting it is not. |
| `b02-handbook.md` | markdown in the tree | A byte-pinned corpus fixture, not documentation. Editing it breaks `manifest_sha256`. Excluded from every recommendation. |

---

## 6 · Sequence, if approved

Corrections only; each is documentation-only and reversible by `git revert`.

1. **E-1** — the image size in `HANDOFF.md` §4. One number, wrong in the entry
   point, measured.
2. **E-3** — merge the duplicated volume note. Removes a drift surface I created.
3. **E-5** — the two cross-reference pointers. Two lines.
4. **S-1** — annotate `RAG_EVOLUTION.md` §9.
5. **E-4** — document how to hold the ollama runbook's window.
6. **E-2** — requires a *measurement* on a fresh volume before it can be written,
   so it is last and should not be guessed.

Items 1–5 can be done immediately. **Item 6 is blocked on a measurement**, and
writing it without one would be the defect it is meant to fix.

**Not proposed:** any deletion, any archive, any merge of two documents into one.
