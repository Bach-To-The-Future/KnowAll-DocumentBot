"""QueryService: the full ask-a-question orchestration — rewrite gating,
concurrent multi-query expansion, retrieval, prompt assembly, generation
(blocking or streamed NDJSON events), answer caching, session memory, and
telemetry. Transport-free: routers only wrap its outputs.
"""
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from starlette.concurrency import run_in_threadpool

from core.config import Settings
from core.exceptions import InvalidRequestError
from core.interfaces import CacheStore, LLMClient
from core.telemetry import Telemetry, log_event, new_trace_id, timed
from models.schemas import QueryRequest, RetrievedChunk
from services.memory import SessionMemory
from services.retrieval import RetrievalService

logger = logging.getLogger(__name__)

NO_ANSWER_MESSAGE = "I could not find this information in the provided documents."

CORPUS_VERSION_KEY = "corpus:version"

# Instructions live in the system message; only context + question go in the
# user turn, so instruction-following survives long contexts.
SYSTEM_PROMPT = f"""You are a document question-answering assistant.
Rules:
1. Answer using ONLY the numbered context passages provided by the user.
2. Cite the passage number(s) in square brackets, e.g. [1] or [1][3], for every factual claim.
3. If the context does not contain the information needed to answer, reply exactly: "{NO_ANSWER_MESSAGE}" Do not guess and do not use outside knowledge.
4. Be concise and factual."""

REWRITE_SYSTEM_PROMPT = (
    "You rewrite follow-up questions into standalone questions. Given a "
    "conversation and a follow-up, output ONLY the rewritten standalone "
    "question, resolving pronouns and references (e.g. 'it', 'that one') "
    "using the conversation. If the question is already standalone, output "
    "it unchanged. Never answer the question."
)

EXPANSION_SYSTEM_PROMPT = (
    "You generate alternative search queries. Given a question, output "
    "{n} differently-phrased versions of it (synonyms, more specific or "
    "more general wording), one per line, with no numbering and no other text."
)

# Anaphora heuristic (English + French pronouns/demonstratives). A false
# positive only costs one extra LLM call; a false negative retrieves on an
# elliptical question — so the net is tuned slightly toward rewriting.
_ANAPHORA_RE = re.compile(
    r"\b(it|its|they|them|their|theirs|this|that|these|those|he|she|him|her|his|hers|"
    r"one|ones|same|former|latter|previous|above|earlier|"
    r"il|elle|ils|elles|ça|cela|celui|celle|ceux|celles|cette|ces|même)\b",
    re.IGNORECASE,
)


@dataclass
class PreparedQuery:
    citations: list[dict[str, Any]]
    prompt: str
    trace: dict[str, Any]
    cache_key: str | None
    cached_answer: str | None = None
    request: QueryRequest = field(default=None)  # type: ignore[assignment]


class QueryService:
    def __init__(self, retrieval: RetrievalService, llm: LLMClient,
                 cache: CacheStore, memory: SessionMemory, telemetry: Telemetry,
                 settings: Settings) -> None:
        self._retrieval = retrieval
        self._llm = llm
        self._cache = cache
        self._memory = memory
        self._telemetry = telemetry
        self._settings = settings

    # --- rewrite & expansion ---------------------------------------------------

    @staticmethod
    def needs_rewrite(question: str, history: list[dict[str, str]]) -> bool:
        """Skip the rewrite LLM call when the question is clearly standalone."""
        if not history:
            return False
        if len(question.split()) <= 6:
            return True  # short follow-ups are usually elliptical
        return bool(_ANAPHORA_RE.search(question))

    def standalone_question(self, question: str, history: list[dict[str, str]]) -> str:
        """Rewrite a follow-up into a standalone query. Best-effort: any
        failure or degenerate output falls back to the original question."""
        if not history:
            return question
        transcript = "\n".join(
            f"User: {turn['question']}\nAssistant: {turn['answer']}" for turn in history
        )
        prompt = f"Conversation:\n{transcript}\n\nFollow-up question: {question}\n\nStandalone question:"
        try:
            raw = self._llm.complete(prompt=prompt, system_prompt=REWRITE_SYSTEM_PROMPT)
            lines = [line.strip() for line in raw.strip().strip('"').splitlines() if line.strip()]
            rewritten = lines[0] if lines else ""
        except Exception as e:
            logger.warning(f"Query rewrite failed, using original question: {e}")
            return question
        # Sanity bounds: an empty or rambling rewrite is worse than the original.
        if not rewritten or len(rewritten) > 4 * max(len(question), 80):
            return question
        return rewritten

    def expand_queries(self, question: str) -> list[str]:
        """Generate query variations for recall. Best-effort: failures mean
        no expansion, never a failed request."""
        if not self._settings.enable_multi_query or self._settings.query_expansion_count <= 0:
            return []
        try:
            raw = self._llm.complete(
                prompt=f"Question: {question}",
                system_prompt=EXPANSION_SYSTEM_PROMPT.format(n=self._settings.query_expansion_count),
            )
        except Exception as e:
            logger.warning(f"Query expansion failed, continuing without: {e}")
            return []
        variations: list[str] = []
        for line in raw.splitlines():
            # Strip numbering/bullets the model may add despite instructions.
            cleaned = line.strip().lstrip("0123456789.-*) ").strip()
            if cleaned and cleaned.lower() != question.lower() and cleaned not in variations:
                variations.append(cleaned)
        return variations[: self._settings.query_expansion_count]

    # --- prompt & cache ---------------------------------------------------------

    @staticmethod
    def build_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
        # Per-chunk provenance tags ground citations in source/page.
        blocks = []
        for idx, chunk in enumerate(chunks, 1):
            page = f", Page: {chunk.page_number}" if chunk.page_number is not None else ""
            blocks.append(f"[{idx}] (Source: {chunk.source}{page})\n{chunk.text}")
        context = "\n\n".join(blocks)
        return f"Context:\n{context}\n\nQuestion:\n{question}"

    def _cache_knobs(self) -> dict[str, Any]:
        # Everything that changes an answer besides corpus content (the
        # corpus version is added in _make_cache_key).
        s = self._settings
        return {
            "model": s.llm_model,
            "reranker": s.reranker_model,
            "floor": s.rerank_score_floor,
            "k": s.rerank_top_n,
            "ctx_mode": s.retrieval_context_mode,
        }

    def _make_cache_key(self, question: str, filters: list[str] | None) -> str:
        payload = {
            "q": " ".join(question.lower().split()),
            "f": sorted(filters or []),
            "v": self._cache.get(CORPUS_VERSION_KEY) or "0",
            **self._cache_knobs(),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        return f"answer:{digest}"

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        raw = self._cache.get(key)
        return json.loads(raw) if raw else None

    def _cache_set(self, key: str, answer: str, citations: list[dict[str, Any]]) -> None:
        self._cache.set(
            key,
            json.dumps({"answer": answer, "citations": citations}, ensure_ascii=False),
            ttl_seconds=self._settings.answer_cache_ttl,
        )

    # --- orchestration ------------------------------------------------------------

    def prepare(self, req: QueryRequest) -> PreparedQuery:
        """Everything before generation: rewrite -> cache lookup -> concurrent
        expansion + retrieval -> citations + prompt + trace."""
        if not req.question.strip():
            raise InvalidRequestError("Question field is required.")

        timings: dict[str, float] = {}
        history = self._memory.get_history(req.session_id)

        with timed(timings, "rewrite_ms"):
            if self.needs_rewrite(req.question, history):
                standalone = self.standalone_question(req.question, history)
            else:
                standalone = req.question

        # Vectors store `source` as the sanitized basename; clients may send
        # full MinIO keys. Normalize so prefixed keys still match.
        filters = None
        if req.documents:
            filters = [os.path.basename(d.replace("\\", "/")) for d in req.documents]

        cache_key = None
        if self._settings.enable_answer_cache:
            cache_key = self._make_cache_key(standalone, filters)
            cached = self._cache_get(cache_key)
            if cached is not None:
                trace = {
                    "trace_id": new_trace_id(),
                    "session_id": req.session_id,
                    "original_question": req.question,
                    "standalone_question": standalone,
                    "cache_hit": True,
                    "timings": timings,
                    "model": self._settings.llm_model,
                }
                return PreparedQuery(cached["citations"], "", trace, cache_key,
                                     cached["answer"], req)

        expander = None
        if self._settings.enable_multi_query and self._settings.query_expansion_count > 0:
            def expander() -> list[str]:  # runs concurrently with the primary fetch
                with timed(timings, "expansion_ms"):
                    return self.expand_queries(standalone)

        with timed(timings, "retrieval_ms"):
            chunks, expansions = self._retrieval.retrieve_with_expansion(
                standalone, filters=filters, expander=expander
            )

        citations = [
            {
                "index": idx,
                "text": chunk.text,
                "source": chunk.source,
                "page_number": chunk.page_number if chunk.page_number is not None else "?",
                "score": chunk.score,
            }
            for idx, chunk in enumerate(chunks, 1)
        ]
        prompt = self.build_prompt(standalone, chunks) if chunks else ""
        trace = {
            "trace_id": new_trace_id(),
            "session_id": req.session_id,
            "original_question": req.question,
            "standalone_question": standalone,
            "expanded_queries": expansions,
            "filters": req.documents,
            "chunks": [
                {"point_id": c.point_id, "source": c.source, "score": c.score} for c in chunks
            ],
            "timings": timings,
            "model": self._settings.llm_model,
        }
        return PreparedQuery(citations, prompt, trace, cache_key, None, req)

    def _finish(self, prepared: PreparedQuery, answer: str) -> None:
        """Post-generation bookkeeping (memory, rolling stats, JSON event).

        Sync because both writes go through the blocking CacheStore; async
        callers hand it to a worker thread.
        """
        if answer:  # an aborted/failed generation still gets telemetry, not memory
            self._memory.append_turn(prepared.request.session_id,
                                     prepared.request.question, answer)
        self._telemetry.record_query(
            timings=prepared.trace.get("timings", {}),
            abstained=(answer.strip() == NO_ANSWER_MESSAGE),
            cache_hit=prepared.trace.get("cache_hit", False),
        )
        log_event("rag_query", answer_chars=len(answer), **prepared.trace)

    async def answer_prepared(self, prepared: PreparedQuery) -> dict[str, Any]:
        """Non-streaming path over an already-prepared query.

        Async so generation (seconds to minutes on CPU) awaits on httpx
        instead of occupying an anyio worker thread. Bookkeeping is blocking,
        so it is handed to a thread.
        """
        def payload(answer: str, cached: bool) -> dict[str, Any]:
            return {
                "answer_with_refs": answer,
                "citations": prepared.citations if answer != NO_ANSWER_MESSAGE else [],
                "standalone_question": prepared.trace["standalone_question"],
                "trace_id": prepared.trace["trace_id"],
                "cached": cached,
            }

        if prepared.cached_answer is not None:
            await run_in_threadpool(self._finish, prepared, prepared.cached_answer)
            return payload(prepared.cached_answer, cached=True)

        if not prepared.citations:
            if prepared.cache_key:
                self._cache_set(prepared.cache_key, NO_ANSWER_MESSAGE, [])
            await run_in_threadpool(self._finish, prepared, NO_ANSWER_MESSAGE)
            return payload(NO_ANSWER_MESSAGE, cached=False)

        with timed(prepared.trace["timings"], "generation_ms"):
            answer = (await self._llm.acomplete(
                prompt=prepared.prompt, system_prompt=SYSTEM_PROMPT
            )).strip()

        if prepared.cache_key and answer:
            self._cache_set(prepared.cache_key, answer, prepared.citations)
        await run_in_threadpool(self._finish, prepared, answer)
        return payload(answer, cached=False)

    async def stream_prepared(self, prepared: PreparedQuery) -> AsyncIterator[str]:
        """NDJSON stream over an ALREADY-PREPARED query.

        prepare() must be called by the caller *before* the StreamingResponse
        is constructed: a generator body does not execute until the first
        iteration, which happens after 200 OK is already on the wire. Running
        retrieval in here meant a Qdrant/embedder outage produced HTTP 200
        with an empty body — invisible to the client's res.ok check.

        Errors *during generation* still can't change the status, so they are
        emitted as 'error' events. The finally block runs on client disconnect
        too (GeneratorExit), so partial turns are still recorded — never cached.
        """
        answer_parts: list[str] = []
        try:
            yield json.dumps({
                "type": "citations",
                "citations": prepared.citations,
                "standalone_question": prepared.trace["standalone_question"],
                "trace_id": prepared.trace["trace_id"],
            }) + "\n"

            if prepared.cached_answer is not None:
                answer_parts.append(prepared.cached_answer)
                yield json.dumps({"type": "token", "text": prepared.cached_answer}) + "\n"
            elif not prepared.citations:
                answer_parts.append(NO_ANSWER_MESSAGE)
                if prepared.cache_key:
                    self._cache_set(prepared.cache_key, NO_ANSWER_MESSAGE, [])
                yield json.dumps({"type": "token", "text": NO_ANSWER_MESSAGE}) + "\n"
            else:
                try:
                    with timed(prepared.trace["timings"], "generation_ms"):
                        async for token in self._llm.astream(prompt=prepared.prompt,
                                                             system_prompt=SYSTEM_PROMPT):
                            answer_parts.append(token)
                            yield json.dumps({"type": "token", "text": token}) + "\n"
                except Exception as e:
                    logger.error(f"LLM streaming failed: {e}")
                    yield json.dumps({"type": "error", "detail": str(e)}) + "\n"
                    return
                # Reached only when generation completed: never cache a
                # partial answer from a disconnected stream.
                answer = "".join(answer_parts).strip()
                if prepared.cache_key and answer:
                    self._cache_set(prepared.cache_key, answer, prepared.citations)
            yield json.dumps({"type": "done"}) + "\n"
        finally:
            # Runs on client disconnect too (aclose -> GeneratorExit).
            await run_in_threadpool(self._finish, prepared, "".join(answer_parts).strip())
