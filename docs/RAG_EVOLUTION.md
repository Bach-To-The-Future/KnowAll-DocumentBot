# The Evolution of RAG: From Naive to Enterprise

*A field guide to fundamental and advanced Retrieval-Augmented Generation — general theory and the technique landscape, anchored throughout in the real evolution of one system (the KnowAll DocumentBot: FastAPI, Qdrant, Redis/ARQ, Ollama, Next.js).*

---

# Part I — Fundamentals

## 1. What RAG Is — and When to Use It

A language model stores knowledge in two places: its **parameters** (frozen at training time, expensive to change, impossible to cite) and its **context window** (ephemeral, cheap to change, fully inspectable). Retrieval-Augmented Generation is the discipline of populating the second with the right evidence at the right moment: documents are chunked, embedded, and indexed offline; at query time, the most relevant chunks are retrieved and injected into the prompt so the model answers from the corpus rather than from its weights.

RAG competes with two alternatives, and choosing correctly matters more than any downstream tuning:

| Dimension | RAG | Fine-tuning | Long-context stuffing |
|---|---|---|---|
| Knowledge freshness | Update by re-indexing (minutes) | Update by re-training (days) | Update by re-pasting (instant, but per-request) |
| Provenance / citations | Native — you know which chunk answered | None — knowledge is diffuse in weights | Possible but unranked |
| Cost profile | Small prompt, per-query retrieval compute | High one-time, cheap inference | Token cost scales with corpus × queries |
| Access control | Enforceable at retrieval time | Impossible post-training | Manual |
| Best for | Factual grounding over changing/private corpora | Style, format, domain *behavior* | Small corpora (< a few hundred KB), one-off analysis |

The rules of thumb: **fine-tune for behavior, retrieve for knowledge**; and if the entire corpus fits comfortably in the context window *and* is queried rarely, skip RAG entirely. RAG earns its complexity when the corpus is larger than the window, changes over time, requires citations, or requires per-user access control.

## 2. Anatomy of a RAG System: Two Planes

Every production RAG system is two loosely-coupled pipelines sharing an index:

```
WRITE PATH (ingestion)                    READ PATH (query)
──────────────────────                    ─────────────────
acquire (upload/sync/crawl)               understand (rewrite, expand, route)
extract (parse, OCR)                      retrieve (dense / sparse / hybrid)
chunk (segment + enrich)                  rerank (cross-encoder, floor)
embed (dense and/or sparse)               assemble (context expansion, budget)
index (upsert, metadata)                  generate (grounded prompt, stream)
                                          record (telemetry, cache, memory)
```

The single most consequential architectural fact: **these planes have different latency and reliability contracts.** The write path is a batch job — minutes are fine, but it must be durable, idempotent, and atomic. The read path is interactive — every millisecond counts, but individual failures are retryable. Naive systems fuse them (ingestion inside a request handler) and inherit the worst of both. Part II, Shift 1 covers the separation in depth.

## 3. Embeddings and Vector Search, from First Principles

### Bi-encoders

A dense embedding model is a **bi-encoder**: it maps a text to a single fixed-width vector such that semantically similar texts land close together under some metric (cosine similarity, dot product, or Euclidean distance — for normalized vectors the first two are equivalent). The defining property is that query and document are encoded *independently*: documents can be embedded once, offline, and a query compares against millions of precomputed vectors in milliseconds. The defining cost is the same independence — the model never sees query and document together, so fine-grained interactions (negation, exact identifiers, rare terms) are compressed away.

Three practical facts routinely bite practitioners:

- **Asymmetric models need task prefixes.** Many retrieval-tuned models (nomic-embed, E5, BGE families) are trained with distinct prefixes for corpus text vs queries (`search_document:` / `search_query:`, `passage:` / `query:`). Omitting them places queries and documents in subtly different regions of the space. *Case study: the baseline audit of this project found the prefixes missing entirely — a measurable recall loss fixed in two lines.*
- **Embeddings have input windows too.** Text beyond the model's token limit is usually truncated *silently*. A chunk longer than the window is only partially searchable — while its full text still sits in the payload, so the index disagrees with itself.
- **Dimensions are a cost knob.** Matryoshka-trained models (e.g. OpenAI `text-embedding-3`) allow truncating vectors to lower dimensions with graceful quality decay — often the cheapest 2–4× storage/latency win available.

### Approximate nearest-neighbor search

Exact k-NN over millions of vectors is too slow; vector databases use approximate indexes, overwhelmingly **HNSW** (Hierarchical Navigable Small World): a multi-layer proximity graph searched greedily from coarse to fine, giving sub-linear search with a tunable recall/speed trade (`ef`, `M` parameters). Two production notes:

- **Quantization** compresses vectors for RAM residency — scalar int8 (~4×, negligible quality loss, used in this project), product quantization (~10–60×, needs rescoring), binary (~32×, for very large scale). The standard pattern: quantized vectors in RAM for the graph walk, full-precision on disk for final rescoring.
- **Metadata filtering interacts with ANN.** Filtering after the graph walk can return fewer than k results; engines like Qdrant filter *during* traversal, but only efficiently if the filtered fields carry **payload indexes**. Unindexed filters on hot paths degrade to scans.

## 4. Chunking Theory

Why chunk at all? Two independent forces impose it: **embedding dilution** (a single vector summarizing many topics matches none of them well — retrieval precision favors small, single-topic chunks) and the **generation budget** (the LLM context is finite and must hold instructions + evidence + answer). Chunking is where those forces are negotiated.

A taxonomy, roughly in ascending sophistication:

| Strategy | Mechanism | Failure mode it fixes / introduces |
|---|---|---|
| Fixed-size | N tokens + overlap | Trivial; ignores all structure, splits mid-thought |
| Recursive | Split on paragraphs → sentences → chars | Respects local boundaries; still structure-blind |
| **Structural** | Split on headings/cells/slides; carry hierarchy | Preserves the author's own segmentation |
| Semantic | Split where embedding similarity between adjacent sentences drops | Topic-coherent chunks; expensive, jittery thresholds |
| Late chunking | Embed the long document with a long-context embedder, then pool token vectors per chunk | Each chunk's vector "knows" its document context; requires long-context embedding models |

The rule that governs all of them: **every chunk must be interpretable in isolation**, because isolation is exactly how the embedding model, the reranker, and often the LLM will see it. A table row without its header, a paragraph without its heading, a code snippet without its signature — all are noise to the retriever regardless of how relevant they are in situ. Techniques that restore self-containedness (heading-path prefixing, header repetition, LLM-generated chunk context — see §14) are among the highest-ROI interventions in all of RAG.

## 5. Grounded Generation

Retrieval quality is wasted if the prompt squanders it. The fundamentals:

- **Separate instructions from evidence.** Grounding rules ("answer only from context, cite passage numbers, abstain if absent") belong in the system message; numbered, provenance-tagged context blocks and the question belong in the user turn. Long contexts erode instruction-following; keeping rules in the position the model attends to most is free reliability.
- **Budget the window explicitly.** Every runtime has a default context length, and most **truncate silently** when exceeded — some from the *front*, deleting your instructions first. Compute the budget (instructions + k × chunk size × expansion factor + answer headroom) and configure it. *Case study: the baseline system's model appeared to "ignore" its grounding rules; it had never seen them — the default window was smaller than the assembled prompt.*
- **Design for abstention.** A grounded system must be able to say "the corpus doesn't contain this." That requires (a) a retrieval-side relevance floor so irrelevant chunks never reach the prompt, and (b) an instructed, *exact* abstention string the UI can detect and render distinctly. Hallucination in RAG is usually not a generation defect — it is retrieval failing to say "no."
- **Lost in the middle.** LLMs attend most reliably to the beginning and end of long contexts (Liu et al., 2023). The mitigation is not clever ordering of twenty mediocre chunks — it is injecting *few, rerank-ordered, high-precision* chunks so there is no middle to get lost in.

---

# Part II — The Journey: Naive to Enterprise

## 6. The Naive Baseline and Its Failure Classes

The starting point was the archetypal prototype: a Streamlit UI, ingestion inside request handlers, fixed-size sentence splitting, one dense model, cosine top-4, a small local LLM. Its defects generalize to failure classes found in most first RAG builds:

- **Event-loop starvation** — blocking extract/embed/upsert inside `async` endpoints froze *all* traffic during ingestion. `async` is a contract, not a decoration.
- **Silent index corruption** — failed embeddings were skipped, then results `zip`ped against chunks: one timeout shifted every subsequent text↔vector pairing by one. No error, no crash, an index that lies. This is the worst bug class in RAG because the system keeps answering confidently.
- **Non-idempotent writes** — `uuid4()` point IDs meant every re-upload duplicated the document's vectors, silently consuming top-k slots with copies.
- **Structure destruction** — DOCX headings flattened into blobs; CSVs sentence-split into header-less comma fragments; wide tables truncated at the embedder's window with the overflow invisible to search.
- **Errors as data** — exceptions returned as HTTP 200 strings in the answer field, indistinguishable from real answers.
- **Model misuse** — missing task prefixes (§3), unbounded context (§5).

The lesson that ordered the entire roadmap: **before any retrieval sophistication, stop corrupting the index and stop lying about failure.**

## 7. Shift 1 — Data Ingestion & State: Durable, Idempotent, Atomic

**Problem.** In-request ingestion; job status in a process dict (restart = amnesia); duplicates on re-ingest; document updates via delete-then-insert, leaving a crash window in which the document existed *nowhere*.

**Solution.**
- `202 Accepted` + `job_id`; the work moves to an **ARQ worker on a Redis queue** — bounded concurrency (the embedder is CPU-bound; unbounded parallelism collapses throughput for everyone), retry with backoff, durable status with TTL.
- **Deterministic point IDs**: `uuid5(namespace, f"{source}:{etag}:{chunk_seq}")` — the same version of the same chunk always maps to the same ID.
- **Staged atomic swap**: upsert the new version first (same etag → same IDs → pure overwrite), *then* delete points whose etag differs.

**Why.** Queues decouple request latency from work latency — the HTTP transaction should end when intent is recorded, not when a 30-minute OCR job finishes. Durable queues deliver *at least once*, which means retries **will** re-run jobs; content-derived IDs are what make a re-run a harmless overwrite instead of an index multiplication. And where vector stores offer no multi-operation transactions, **ordering substitutes for atomicity**: at every crash point the index holds either the complete old version or the complete new one — never neither.

## 8. Shift 2 — Structure-Aware Chunking

**Problem.** Fixed-size splitting treated documents as character streams (§4's failure modes, all of them at once).

**Solution.** Heading-path chunking for prose (split on heading boundaries, maintain the hierarchy as a stack, *prepend the full path* — `Doc > Section > Subsection` — to every chunk's embedded text); token-budgeted row grouping for tables with the header repeated per chunk; and order-preserving metadata on every chunk (`chunk_seq`, `section_title`) — deliberately planted as raw material for read-time context assembly (Shift 4).

**Why.** Structure is the author's own semantic segmentation; discarding it forces the retriever to relearn boundaries it was handed for free. Prefixing the heading path is a deterministic, zero-cost instance of the general principle formalized later as *contextual retrieval* (§14): move context **into** the chunk, because context outside the chunk does not exist for the embedding model.

## 9. Shift 3 — Hybrid Retrieval and the Reranking Cascade

**Problem.** Dense-only cosine top-4. Dense vectors excel at paraphrase and fail systematically at **lexical precision** — exact acronyms, identifiers, rare terms, cross-language vocabulary. And with no relevance floor, the four best-of-a-bad-lot chunks were injected regardless, so out-of-corpus questions were answered from noise.

**Solution.** The canonical three-stage cascade:

1. **Hybrid recall** — each point carries two named vectors: dense (semantic) and BM25 sparse (lexical, IDF server-side); both legs queried in parallel with metadata filters applied *inside each leg*.
2. **Reciprocal Rank Fusion** — merge the two ranked lists by rank position: `score = Σ 1/(60 + rankᵢ)`. Rank-based fusion exists because cosine and BM25 scores are incommensurable; RRF needs no per-corpus calibration.
3. **Cross-encoder reranking** — the fused top ~20 re-scored by a model that reads query and chunk *together*; sigmoid-mapped scores gated by a floor threshold, where an empty post-floor result triggers instructed abstention.

**Why the cascade shape.** Bi-encoders are O(1) per query against a precomputed index but lossy; cross-encoders are accurate but O(n) forward passes. Use each where it is cheap: bi-encoder recall over millions, cross-encoder precision over twenty. The floor converts the reranker from a sorter into a *relevance judge* — the mechanism that makes honest abstention possible.

**Why calibration is empirical.** The project's evaluation harness made the abstract concrete: hybrid recall@20 was 0.952 — retrieval was fine — but the default reranker (`bge-reranker-base`, EN/ZH-trained) scored relevant *French* chunks near zero and scored CSV rows containing the literal word "Australia" at 0.99 for "What is the capital of Australia?". No floor value fixes a miscalibrated model. Swapping to a multilingual reranker moved hit@5 from 0.857 → 0.952 and abstention accuracy from 0.5 → 1.0. Invisible without a golden set; a one-line fix with one.

## 10. Shift 4 — Context Assembly and Query Understanding

**Problem.** The chunk-size contradiction (§4): small chunks retrieve precisely but starve the generator; large chunks feed the generator but embed poorly. Plus conversational queries: "how do I configure *it*?" embeds to nothing — the referent lives in history the retriever never sees.

**Solution.**
- **Small-to-big (parent-document) retrieval**: match on small chunks; after reranking, rebuild each winner's surroundings at read time — walking outward through its section via `chunk_seq` under a character budget, stopping at sequence gaps, with a per-source claimed-set so overlapping winners never duplicate text. Related patterns in the wider ecosystem: *sentence-window retrieval* (embed sentences, return ± a window) and *auto-merging retrieval* (a chunk hierarchy where enough retrieved children collapse into their parent).
- **Multi-query expansion**: an LLM writes 2–3 alternative phrasings; all variants fetch candidates, pooled and deduplicated *by point ID*, then reranked **against the original question only** — expansion boosts recall but must never redefine relevance. Run the expansion LLM call *concurrently* with the primary retrieval and it costs ~zero wall-clock.
- **Anaphora-gated rewriting**: rewrite follow-ups into standalone questions using session history — but gate the LLM call behind a cheap heuristic (pronouns, demonstratives, elliptical shortness), because most questions don't need it and every skipped rewrite is one less round-trip before the first token.

**Why.** The unifying principle: **the retrieval representation and the generation payload are different artifacts with different optima.** Embed small and clean; assemble large and coherent at read time from structure metadata. The vector space stays uncluttered (expansions and assembled contexts never touch the index), and "lost in the middle" is addressed by construction — few, ordered, high-precision passages instead of twenty stuffed mediocrities.

## 11. Production Hardening (Condensed)

The remaining evolution was software engineering, not information retrieval — and it caught real defects the IR work never would have:

- **Decoupled full stack.** Streamlit's rerun-the-script model gave way to a Next.js/FastAPI monorepo with layered internals (thin routers → services → interface-backed integrations, wired by one composition root, validated config via pydantic-settings). The layering is what made unit tests injectable and E2E boundaries mockable.
- **The streaming proxy pattern.** Answers stream as NDJSON events (`citations`, then `token`s, then `done`; mid-stream failures become `error` *events* because the HTTP status is already committed). The browser reaches the backend only through a Next.js Route Handler proxy — chosen over rewrites for one decisive reason: rewrites cannot inject request headers. The proxy adds the API key server-side (it never reaches the browser), enforces an endpoint allowlist, streams zero-copy in both directions, and propagates client aborts upstream so an abandoned stream doesn't leave the LLM generating to a dead socket.
- **Deterministic E2E at the boundary.** Playwright against the composed stack, intercepting at the proxy with canned NDJSON/job sequences — real streaming assembly and polling state machines, zero LLM-latency dependence. First run caught a production bug no green build had: `crypto.randomUUID()` requires a secure context — fine on `localhost`, fatal for any LAN user.

---

# Part III — The Advanced Frontier

Techniques beyond this project's current state, with honest notes on when each earns its complexity.

## 12. Query Transformation: HyDE, Step-Back, Decomposition

- **HyDE** (Hypothetical Document Embeddings): ask an LLM to *write a hypothetical answer*, embed that, and search with it — exploiting the fact that document↔document similarity is often more reliable than query↔document. Works best when queries are terse and documents verbose. Caveat: the hypothesis is only as good as the generator — with a small local model, hallucinated hypotheses actively mislead retrieval (the reason this project deliberately deferred it).
- **Step-back prompting**: derive a more abstract question first ("What are Databricks cluster types?" behind "Can I share an interactive cluster?"), retrieve for both.
- **Decomposition**: split multi-hop questions into sub-questions, retrieve per sub-question, synthesize. This is the gateway to agentic RAG (§16).
- **Routing**: classify the query first — chitchat vs corpus question vs aggregation ("how many documents mention X?" is a *database* query, not a retrieval query) — and send each to the right machinery.

## 13. Beyond BM25: Learned Sparse and Late Interaction

BM25 is a 30-year-old statistical formula and still embarrassingly hard to beat, but it cannot bridge vocabulary gaps ("automobile" ≠ "car"). Two learned families close it:

- **Learned sparse (SPLADE family)**: a transformer expands each text into weighted vocabulary terms — sparse-index efficiency with learned synonymy. Drop-in wherever BM25 vectors go.
- **Late interaction (ColBERT)**: store a vector *per token*; score by MaxSim between query tokens and document tokens. Much of a cross-encoder's precision at a fraction of query cost — paid for in index size (an order of magnitude larger; mitigated by pooling/quantization in ColBERTv2/PLAID).

Selection heuristic: hybrid BM25+dense with a cross-encoder covers most corpora; reach for SPLADE when vocabulary mismatch dominates *and* you can't afford reranking latency; reach for ColBERT at scale where reranking is the bottleneck.

## 14. Contextual Retrieval

The generalization of Shift 2's heading-path prefixing: for each chunk, have an LLM write a 1–2 sentence *situating context* ("This chunk is from the Q3 filing, discussing revenue in the cloud segment…") and prepend it before embedding and BM25 indexing. Anthropic's published measurements: ~49% reduction in retrieval failures combined with hybrid search, ~67% with reranking added. The trade is an LLM call per chunk at ingest time — made economical by prompt caching (the full document cached, each chunk a small suffix). The deterministic structural prefix is the free tier of this idea; LLM-situated context is the premium tier. Same principle: **context outside the chunk does not exist — move it inside.**

## 15. GraphRAG and Structured Knowledge

Vector RAG answers *local* questions — those answerable from a handful of passages. It structurally cannot answer *global* ones ("What are the main themes across this corpus?" "How are these two entities connected?") because no chunk contains the answer. GraphRAG (Microsoft's formulation) builds an entity/relationship graph via LLM extraction at ingest, clusters it into communities, and pre-summarizes each community; global questions are answered map-reduce over community summaries, and entity questions traverse the graph. Cost: heavy LLM spend at ingest and real pipeline complexity. Reach for it only when your query log actually contains corpus-level questions — most document-QA workloads don't.

## 16. Agentic RAG: Self-RAG, CRAG, and Iterative Retrieval

The single-pass pipeline (retrieve → generate) becomes a loop with judgment:

- **Self-RAG**: the model itself decides *whether* to retrieve, critiques retrieved passages for relevance, and critiques its own draft for support — via trained reflection tokens or, more practically, prompted critique steps.
- **CRAG (Corrective RAG)**: a lightweight evaluator grades retrieval quality; low-confidence results trigger corrective action (query reformulation, fallback to web search, or abstention) before generation.
- **Iterative / multi-hop retrieval**: generate → notice a missing fact → issue a follow-up query → continue. Essential for questions whose evidence is distributed ("compare X's approach in doc A with Y's in doc B").

The trade is always the same: each loop iteration adds an LLM round-trip of latency. Agentic RAG belongs where answer quality dominates latency (research assistants, analyst tooling) — not in a sub-second chat product. A useful design stance: build the single-pass pipeline to be *measurably good*, then add loops only for the query classes your eval proves it fails.

## 17. Learning Components: Fine-Tuning the Retriever Stack

When off-the-shelf models plateau, three targeted options — strictly in order of an eval harness existing first:

- **Embedding fine-tuning**: contrastive training on (query, relevant-chunk) pairs mined from your own telemetry (clicked citations, judged answers). Highest ROI on jargon-heavy domains where general models cluster everything together.
- **Reranker distillation**: label pairs with a large LLM judge, train a small cross-encoder on them — LLM-quality relevance at cross-encoder latency.
- **RAFT (Retrieval-Augmented Fine-Tuning)**: fine-tune the *generator* on examples containing golden chunks mixed with distractors, teaching it to quote what matters and ignore what doesn't — targeting the last-mile failure where retrieval is right and the model still answers from the wrong passage.

## 18. Multimodal RAG

Real corpora are not text. The maturity ladder:

1. **OCR** for scanned documents (this project: tesseract behind a text-layer check turned a 162-page scanned PDF from *zero* indexed chunks into 191).
2. **VLM captioning**: describe figures, charts, and diagrams with a vision-language model at ingest; index the descriptions alongside text.
3. **Table-aware handling**: tables are structured data wearing a text costume — row-group chunking with headers (Shift 2) is the floor; for aggregation queries, route to actual computation (§12) instead of retrieval.
4. **Native multimodal embeddings** (CLIP-family, ColPali): embed page *images* directly — ColPali-style late interaction over page screenshots skips parsing entirely and excels on layout-heavy documents (invoices, slides), at significant index cost.

## 19. Caching Strategies

Three distinct caches, often conflated:

- **Exact answer caching** — key on the *normalized rewritten* question + every retrieval knob + a **corpus version counter** bumped on any ingest/delete. The version-in-key trick makes stale answers structurally impossible rather than TTL-probable (this project's design).
- **Semantic caching** — hit when a new query's *embedding* is close to a cached one. Real latency wins, real risk: "revenue in 2023" vs "revenue in 2024" are cosine-close and factually disjoint. Use tight thresholds and treat it as a suggestion, not truth.
- **KV/prompt caching** — provider- or runtime-level reuse of attention states for repeated prompt prefixes. Design prompts for it: static system message first, stable corpus preamble next, volatile question last.

## 20. RAG vs Long Context: Why Not Both

Million-token windows did not kill RAG; they changed its economics. Stuffing the corpus into every request costs tokens × queries forever, buries provenance, and degrades reasoning even when needle-retrieval benchmarks look clean. Retrieval remains the mechanism for *selection*, freshness, and access control. What long context changes is the **assembly budget**: retrieve precisely, then afford to inject whole sections or documents rather than fragments — small-to-big with a much bigger "big," fewer boundary artifacts, and prompt caching amortizing the stable prefix. The endpoint is a spectrum, not a rivalry: precision selection from RAG, generous context from the window.

---

# Part IV — Operating RAG in Production

## 21. Evaluation and Observability

**Offline: the golden set.** 30–60 (question → expected source/keywords) pairs from the *real* corpus, deliberately including the hard classes: cross-language queries, table lookups, and unanswerable questions (abstention cases). Core metrics, each isolating one pipeline stage:

- **recall@fetch** — is the right chunk anywhere in the pre-rerank candidates? (Isolates retrieval; the ceiling for everything downstream.)
- **hit@k / MRR / nDCG** — did reranking put it in the final top-k, and how high?
- **abstention accuracy** — did unanswerable questions correctly return nothing?
- **faithfulness / answer relevance** (RAGAS-style, LLM-as-judge) — is the generated answer supported by the retrieved context? Judge scores are noisy; treat them as regression signals, not absolute truth.

The operational rule this project learned the expensive way: **build the harness before the techniques.** Three phases of retrieval sophistication shipped unmeasured; the first eval run found the highest-impact defect (reranker miscalibration) in an afternoon and turned every subsequent knob change into a 20-minute ablation.

**Online:** one structured event per query (trace id, original vs rewritten question, chunk IDs + rerank scores, per-stage latency), rolled into p50/p95 dashboards. The two leading indicators worth alerting on: **abstention-rate drift** (the floor or the corpus moved) and **retrieval-stage p95** (index or filter degradation) — both move before users complain.

## 22. Security

- **The corpus is untrusted input.** Retrieved chunks can contain instructions ("ignore your rules and…") — indirect prompt injection. Mitigations: structural separation of instructions from evidence (§5), spotlighting/delimiting retrieved text as data, never granting the generation step tool permissions triggered by retrieved content, and treating any action-taking RAG agent as operating on attacker-controllable input.
- **Access control lives at retrieval time.** Multi-tenancy = mandatory metadata filters (or collection-per-tenant at higher isolation), enforced server-side — never by the client's query. An index without ACL filtering is a data-leak instrument with a search API.
- **Credentials stay server-side.** UI processes should reach the backend through an authenticating proxy (this project: a Next.js Route Handler injecting the API key), never carry keys into the browser. Rate-limit the query surface; scope read-only keys separately from destructive ones.

## 23. A Symptom → Technique Decision Table

| Symptom | Likely cause | First technique to reach for |
|---|---|---|
| Misses exact terms, codes, names | Dense-only retrieval | Hybrid BM25 + RRF |
| Right chunk retrieved, ranked too low | No precision stage | Cross-encoder reranking |
| Answers confidently on out-of-corpus questions | No relevance floor | Rerank floor + instructed abstention |
| Chunks retrieved are correct but answers lack context | Chunks too small for generation | Small-to-big / sentence-window / parent retrieval |
| Retrieval fails on paraphrased questions | Vocabulary mismatch | Multi-query expansion; SPLADE; (HyDE if generator is strong) |
| Follow-up questions retrieve garbage | Anaphora | Conversational rewriting, gated |
| Table questions fail | Structure-destroyed chunks | Header-carrying row groups; route aggregations to compute |
| "Themes across the corpus" questions fail | No chunk contains the answer | GraphRAG / corpus summarization |
| Everything fails on scanned PDFs | No text layer | OCR gate; VLM captioning; ColPali |
| Quality unknown, tuning feels random | No measurement | Golden set + eval harness — before anything else |
| Duplicates crowd the top-k | Non-idempotent ingestion | Deterministic content-derived IDs |
| Answers stale after document updates | Cache without invalidation | Corpus-version counter in cache keys |

---

# Golden Rules for Production RAG

1. **Hunt silent corruption before adding intelligence.** Misaligned embeddings, duplicated vectors, truncated prompts, and errors-returned-as-answers all *look like a working system*. Enforce invariants, raise on violation, make failure loud and typed. No retrieval technique compensates for an index that lies.
2. **Make writes idempotent and crash-states valid.** Content-derived IDs, staged swaps, durable queues. Retries are inevitable; idempotency makes them free.
3. **No measurement, no tuning.** The golden set precedes the technique — always. Every knob without an eval number is a superstition.
4. **Every chunk must stand alone.** Structure-aware segmentation with context moved *inside* the chunk is the highest-ROI intervention in the entire stack — cheaper than any model swap and compounding with all of them.
5. **Embed small and clean; assemble context at read time.** The retrieval representation and the generation payload have different optima. Systems that conflate them sacrifice one for the other.
6. **Design abstention as a feature.** A relevance floor plus an instructed refusal string is the difference between a grounded system and a confident hallucination engine.
7. **Add sophistication only against a measured failure.** Hybrid before learned-sparse, reranking before fine-tuning, single-pass before agentic loops. Each rung of the ladder costs latency and complexity — climb only when the eval says the current rung fails.
