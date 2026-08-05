"""Centralized, validated configuration.

Every environment variable the system reads is declared here with a type and
a default; pydantic-settings performs casting and validation at startup, so a
malformed value fails fast instead of surfacing as a runtime type error.

Access pattern: `get_settings()` (cached). FastAPI code paths receive the
instance through dependency injection; tests construct `Settings(...)`
directly or override the dependency.
"""
from functools import lru_cache
from typing import Literal

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Real env vars (compose env_file) win; the .env files serve local runs.
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Ingestion pipeline ---
    # Chunks embedded + upserted per batch. Bounds peak RAM: a document is no
    # longer materialized as (all chunks + all embeddings + all payloads).
    ingest_batch_size: int = 256
    # Hard ceiling per document. Exceeding it fails the job loudly instead of
    # letting the worker get OOM-killed mid-write.
    max_chunks_per_document: int = 20_000
    # Wall-clock ceiling per ingest job; enforced by killing the subprocess.
    ingest_job_timeout: int = 1800
    # Pending-queue depth at which uploads start shedding load with 503.
    max_queue_depth: int = 100
    # Subprocesses in the worker pool (CPU-bound extraction/embedding).
    worker_processes: int = 2

    # --- Chunking ---
    chunk_size: int = 550
    chunk_overlap: int = 100
    table_chunk_char_budget: int = 1600  # ~400 tokens per table chunk
    table_max_rows_per_chunk: int = 30

    # --- Embeddings ---
    use_openai_embedding: bool = False
    openai_embed_model: str = "text-embedding-3-small"
    ollama_embed_model: str = "nomic-embed-text:latest"
    # Identity pin for the embedding model. Ollama cannot pull BY digest
    # (`name@sha256:…` -> "invalid model name"), so drift is caught by
    # assertion instead: unset = loud warning, set = hard fail on mismatch at
    # API startup, worker startup and the eval head. See core/model_identity.py.
    expected_embed_model_digest: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def embed_model(self) -> str:
        return self.openai_embed_model if self.use_openai_embedding else self.ollama_embed_model

    @computed_field  # type: ignore[prop-decorator]
    @property
    def embed_dim(self) -> int:
        return 1536 if self.use_openai_embedding else 768

    # --- LLM generation ---
    use_openai_llm: bool = False
    openai_llm_model: str = "gpt-4o-mini"
    ollama_llm_model: str = "llama3.2:1b"
    # 8192 fits k=5 section-expanded chunks + instructions + answer headroom.
    llm_num_ctx: int = 8192
    llm_temperature: float = 0.1
    llm_num_predict: int = 1024
    llm_read_timeout: int = 300  # CPU inference is slow, but never unbounded
    openai_api_key: str | None = None
    # Finding #24 extended to the GENERATOR. Same moving-tag exposure the
    # embedding model had, different blast radius: embedding drift invalidates
    # stored vectors, generation drift invalidates every measured claim about
    # abstention, grounding and instruction-following. All of P-3 is a
    # statement about one specific generator.
    # Unset = loud warning; set = hard fail on mismatch.
    expected_llm_model_digest: str | None = None

    # Phase 2.1 — the marker that makes "unknown" temporary.
    #
    # Set to an ISO date by the reindex once every point carries an
    # embed_model_digest. From then on a point WITHOUT one is not "unknown",
    # it is a point that escaped the reindex, and verify_three_way() treats it
    # as fatal. Unset, the pre-2.1 semantics hold: no digest means unknown.
    #
    # Without this, "unknown" would be permanent and a genuinely unverifiable
    # collection would be indistinguishable from a verified one forever.
    digest_enforcement_from: str | None = None

    # Finding #5 / P-3 candidates D1+D6 — quote-backed grounding.
    #
    # The generator must copy a supporting sentence out of each passage it
    # cites; the quote is then checked to occur in that passage by string
    # comparison, with no model judgement anywhere in the check.
    #
    # Elicited as open-ended COPYING rather than a yes/no judgement because
    # D3's control showed this model emits a fixed "NO" under any binary
    # verdict framing, while reading and extracting correctly when asked plainly.
    #
    # DOCUMENTED GAP: catches claims with no textual basis in the cited
    # passage. Does NOT catch a claim that quotes truthfully and reasons
    # wrongly from it — the benchmark deadline-into-entitlement inversion
    # survives this. Candidate D2 (entailment) remains OPEN, not closed.
    #
    # SHIPS OFF. MEASURED 2026-08-05 on llama3.2:1b: adding rule 5 collapsed
    # generation. Same 15 answerable questions, same passages, only the prompt
    # rule differing:
    #
    #     base prompt (4 rules)   answered 13/15   abstained  2/15
    #     with rule 5             answered  2/15   abstained 13/15
    #
    # The model responded "I could not find this information in the provided
    # documents." to questions whose passage states the answer verbatim. The
    # SUPPORT requirement is a GENERATION REGRESSION on a 1B model, not a
    # grounding mechanism. The verification code is correct and tested and
    # would work against a model that can satisfy the output contract — this
    # one cannot.
    #
    # Left in place, off, rather than deleted: it is the only mechanism P-3
    # produced that survives its own unit tests, and a larger generator would
    # make it viable without any code change.
    require_support_quotes: bool = False

    # Finding #32 / P-3 candidate D5 — malformed-generation guard.
    #
    # Minimum SUBSTANTIVE characters (citation markers stripped) for a
    # generation to count as an answer. The model sometimes emits "[1] [1][3]"
    # and nothing else: not an answer, not an abstention, and it passes every
    # other check because it is non-empty, correctly sized and even cites.
    # Below this it is treated as a FAILED generation and becomes the
    # abstention message.
    #
    # REVERSIBLE: 0 disables the guard and reproduces pre-2.4 behaviour exactly.
    min_answer_chars: int = 20

    # Finding #28 — semantic-drift guard on query rewrite. A rewrite whose
    # cosine similarity to the original question falls below this is discarded
    # and the original is used. Deliberately LOW: this is a safety net against
    # gross topic replacement (measured: a records-retention follow-up rewritten
    # as a hazardous-waste question), not a quality knob. Raising it starts
    # rejecting legitimate rewrites, which is a retrieval-quality change and
    # needs a measured before/after. NOT calibrated against tier A yet.
    rewrite_min_similarity: float = 0.55

    @computed_field  # type: ignore[prop-decorator]
    @property
    def llm_model(self) -> str:
        return self.openai_llm_model if self.use_openai_llm else self.ollama_llm_model

    # --- External services ---
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str = "knowall"
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "knowall_collection"
    qdrant_api_key: str | None = None
    # Internal Docker network is plaintext. Setting api_key alone makes
    # qdrant-client assume TLS, so this must stay explicit.
    qdrant_https: bool = False
    qdrant_timeout: int = 15          # seconds; unset default hangs threads
    s3_max_pool_connections: int = 50 # must exceed the request threadpool
    s3_connect_timeout: int = 5
    s3_read_timeout: int = 60         # large uploads/downloads stream through
    ollama_api_url: str = "http://localhost:11434/api/"
    # Durable ingestion queue + shared caches; None = in-process fallbacks.
    redis_url: str | None = None

    # --- OCR (scanned PDFs) ---
    enable_ocr: bool = True
    ocr_languages: str = "eng+fra"
    ocr_dpi: int = 200

    # --- Retrieval ---
    sparse_model: str = "Qdrant/bm25"
    reranker_model: str = "BAAI/bge-reranker-base"
    retrieval_fetch_k: int = 20      # candidates fetched pre-rerank
    rerank_top_n: int = 5            # chunks kept after reranking
    # Finding #27 / P-2 candidate C3 separated two jobs one number was doing.
    #
    # ABSTENTION — "did retrieval return anything coherent?"
    #
    # JUSTIFICATION (primary, and the only one that survives a corpus change):
    # a cross-encoder sigmoid below 0.01 is a logit below about -4.6. The model
    # is CONFIDENTLY rejecting even its own best candidate. That is the
    # principled reading of "nothing coherent came back", tied to the model's
    # own confidence semantics rather than to any corpus.
    #
    # CORROBORATION ONLY: 0.01 also sits near the 1st percentile of the
    # reranker's observed rank-1 output on tier B (range 0.0003-0.9999). That
    # is a sanity check on the logit reasoning, NOT its basis — a bar justified
    # by a percentile moves when the corpus composition moves, and this one
    # must not.
    #
    # It is NOT a relevance judgement and must not be tuned as one.
    abstention_score_floor: float = 0.01

    # RELEVANCE — an optional per-chunk cut, now OFF by default. At 0.25 this
    # discarded correctly-ranked first-place answers whose absolute score was
    # low because they were tables, lists or OCR text: chunk SHAPE moves this
    # score as much as relevance does. Ordering is the reranker's job and
    # rerank_top_n bounds the count. Raising this above 0 restores the pre-C3
    # behaviour and is a retrieval-quality change.
    rerank_score_floor: float = 0.0
    # "section" = budgeted parent-section assembly, "window" = ±N chunks
    retrieval_context_mode: Literal["section", "window", "off"] = "section"
    neighbor_window: int = 1
    parent_char_budget: int = 4000

    # --- Conversation & query expansion ---
    memory_max_turns: int = 5
    enable_multi_query: bool = True
    query_expansion_count: int = 2

    # --- Answer cache ---
    enable_answer_cache: bool = True
    answer_cache_ttl: int = 3600

    # --- API surface ---
    api_key: str | None = None        # unset = auth disabled (dev mode)
    api_query_keys: str = ""          # comma-separated read-only keys
    rate_limit_per_minute: int = 30   # 0 = disabled, per identity per window
    max_upload_bytes: int = 100 * 1024 * 1024  # mirrored at the Next.js proxy
    # Admission control: hard ceiling on in-flight queries per replica.
    max_concurrent_queries: int = 20
    # X-User-Id / X-Forwarded-For are only trusted because reaching the API
    # already requires a valid API key, held solely by the authenticated proxy.
    trust_proxy_identity: bool = True

    # Conversation memory TTL (seconds) — sessions expire, not evict.
    session_ttl_seconds: int = 24 * 3600

    @property
    def query_keys(self) -> tuple[str, ...]:
        return tuple(k.strip() for k in self.api_query_keys.split(",") if k.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
