"""QueryService: the full ask-a-question orchestration — rewrite gating,
concurrent multi-query expansion, retrieval, prompt assembly, generation
(blocking or streamed NDJSON events), answer caching, session memory, and
telemetry. Transport-free: routers only wrap its outputs.
"""
import hashlib
import json
import logging
import math
import os
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from starlette.concurrency import run_in_threadpool

from core.config import Settings, get_settings
from core.constants import CORPUS_VERSION_KEY
from core.exceptions import InvalidRequestError
from core.interfaces import CacheStore, DenseEmbedder, LLMClient
from core.telemetry import Telemetry, log_event, new_trace_id, timed
from core.token_budget import fit_context_budget
from models.schemas import QueryRequest, RetrievedChunk
from services import grounding, output_guard, passage_guard
from services.memory import SessionMemory
from services.retrieval import RetrievalService

logger = logging.getLogger(__name__)

NO_ANSWER_MESSAGE = "I could not find this information in the provided documents."


# Instructions live in the system message; only context + question go in the
# user turn, so instruction-following survives long contexts.
_BASE_RULES = f"""You are a document question-answering assistant.
Rules:
1. Answer using ONLY the numbered context passages provided by the user.
2. Cite the passage number(s) in square brackets, e.g. [1] or [1][3], for every factual claim.
3. If the context does not contain the information needed to answer, reply exactly: "{NO_ANSWER_MESSAGE}" Do not guess and do not use outside knowledge.
4. Be concise and factual."""

# P-3 candidates D1+D6. The ONLY sanctioned change to the generation prompt
# (R5 approval was scoped to exactly this and nothing else in the prompt moves).
#
# Phrased as open-ended copying, not as a judgement, because D3's control
# showed this model emits a fixed "NO" under any binary-verdict framing but
# reads and extracts correctly when simply asked.
_SUPPORT_RULE = """
5. After your answer, write a line containing only SUPPORT: and then, for each
passage you cited, one line of the form [n] followed by a sentence copied
word-for-word from passage n. Copy exactly; do not paraphrase."""

# The containment clause is what makes the fence mean something; without it
# the fence is decoration the model has no reason to respect. Both move with
# the same flag, so disabling it reproduces pre-2.3 assembly exactly.
#
# NOT resolved at import time: that would freeze one Settings instance into a
# module constant and make the flag untestable and un-overridable per request.
SYSTEM_PROMPT = _BASE_RULES + passage_guard.CONTAINMENT_RULE
SYSTEM_PROMPT_NO_CONTAINMENT = _BASE_RULES
SYSTEM_PROMPT_WITH_SUPPORT = _BASE_RULES + _SUPPORT_RULE

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


# Citation markers the model emits: [1], [2][3], [1] [4].
_CITATION_RE = re.compile(r"\[\s*\d+\s*\]")


def substantive_text(answer: str) -> str:
    """What is left after stripping citation markers and punctuation.

    Finding #32: the generator sometimes emits "[1] [1][3]" and nothing else —
    citation markers with no prose. That is neither an answer nor an
    abstention, and it passes every pre-existing check: non-empty, correctly
    sized, and it even contains citations. It reaches the user as an empty
    answer bubble.
    """
    return _CITATION_RE.sub("", answer).strip(" \t\n\r.,;:—-[]()")


@dataclass(frozen=True)
class RewriteResult:
    """What the rewrite did, and why — so a rejection is visible in the trace
    instead of looking identical to "the question was already standalone"."""
    text: str
    fired: bool
    reason: str                        # no-history | llm-error | empty | too-long | drift | ok
    similarity: float | None = None
    rejected_text: str | None = None   # the drifted rewrite, kept for forensics


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
                 settings: Settings, embedder: DenseEmbedder) -> None:
        self._retrieval = retrieval
        self._llm = llm
        self._cache = cache
        self._memory = memory
        self._telemetry = telemetry
        self._settings = settings
        # Only used by the rewrite drift guard (#28). Query embeddings are
        # cached, so this shares work with retrieval rather than duplicating it.
        self._embedder = embedder

    # --- rewrite & expansion ---------------------------------------------------

    @staticmethod
    def needs_rewrite(question: str, history: list[dict[str, str]]) -> bool:
        """Skip the rewrite LLM call when the question is clearly standalone."""
        if not history:
            return False
        if len(question.split()) <= 6:
            return True  # short follow-ups are usually elliptical
        return bool(_ANAPHORA_RE.search(question))

    def _rewrite_similarity(self, original: str, rewritten: str) -> float | None:
        """Cosine between the original and the rewritten query, in the same
        embedding space retrieval uses.

        None means "could not measure" — never a rejection. Query embeddings
        are cached, and the original is embedded moments later by retrieval, so
        the marginal cost is one embedding call on a rewrite (~20% of queries).
        """
        try:
            a = self._embedder.embed_query(original)
            b = self._embedder.embed_query(rewritten)
        except Exception as e:
            logger.warning(f"Rewrite similarity unavailable, guard skipped: {e}")
            return None
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
        return (dot / norm) if norm else None

    def standalone_question(self, question: str, history: list[dict[str, str]]) -> str:
        return self.rewrite(question, history).text

    def rewrite(self, question: str, history: list[dict[str, str]]) -> RewriteResult:
        """Rewrite a follow-up into a standalone query. Best-effort: any
        failure, degenerate output, or SEMANTIC DRIFT falls back to the
        original question.

        Finding #28: the previous guards caught exceptions, empty output and
        gross length overruns — every failure mode except the one that
        actually happens. A records-retention follow-up came back rewritten as
        "What is the policy on disposing of hazardous waste?": fluent,
        correctly sized, and past every check. The similarity guard below is
        the one that can see that, because it measures meaning rather than
        shape, in the same space retrieval scores in.
        """
        if not history:
            return RewriteResult(question, fired=False, reason="no-history")
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
            return RewriteResult(question, fired=False, reason="llm-error")
        # Sanity bounds: an empty or rambling rewrite is worse than the original.
        if not rewritten:
            return RewriteResult(question, fired=False, reason="empty")
        if len(rewritten) > 4 * max(len(question), 80):
            return RewriteResult(question, fired=False, reason="too-long")

        similarity = self._rewrite_similarity(question, rewritten)
        floor = self._settings.rewrite_min_similarity
        if similarity is not None and similarity < floor:
            logger.warning(
                f"Query rewrite REJECTED as semantic drift "
                f"(similarity {similarity:.3f} < {floor}). "
                f"original={question!r} rewritten={rewritten!r}"
            )
            return RewriteResult(question, fired=False, reason="drift",
                                 similarity=similarity, rejected_text=rewritten)
        return RewriteResult(rewritten, fired=True, reason="ok", similarity=similarity)

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
    def build_prompt(question: str, chunks: list[RetrievedChunk],
                     settings: Settings | None = None) -> str:
        # Per-chunk provenance tags ground citations in source/page.
        settings = settings or get_settings()
        blocks: list[str] = []
        neutralised: dict[str, int] = {}
        for idx, chunk in enumerate(chunks, 1):
            page = f", Page: {chunk.page_number}" if chunk.page_number is not None else ""
            header = f"[{idx}] (Source: {chunk.source}{page})"
            if settings.contain_untrusted_passages:
                # Phase 2.3: fence + neutralise. The fence alone is decoration
                # a poisoned chunk can close and step outside of; stripping
                # fence-shaped text from the body is what makes it mean
                # anything. See services/passage_guard.py.
                block, counts = passage_guard.fence_passage(idx, header, chunk.text)
                for key, n in counts.items():
                    if n:
                        neutralised[key] = neutralised.get(key, 0) + n
                blocks.append(block)
            else:
                blocks.append(f"{header}\n{chunk.text}")

        if neutralised:
            # Counted and surfaced, never silently rewritten: a passage that
            # trips several of these is itself a signal.
            logger.warning(
                f"Passage containment neutralised injection-shaped content: "
                f"{neutralised}"
            )

        # Finding #3: DEGRADE GRACEFULLY. Over-budget context is truncated by
        # the runtime from the FRONT, which is where the system prompt's
        # grounding rules live — the model would lose rule 3 and keep every
        # passage. Dropping the lowest-ranked passages instead is the opposite
        # trade and the correct one. `chunks` arrives in rank order.
        system = (SYSTEM_PROMPT if settings.contain_untrusted_passages
                  else SYSTEM_PROMPT_NO_CONTAINMENT)
        kept, _, dropped = fit_context_budget(system, question, blocks)
        if dropped:
            logger.warning(
                f"Prompt assembly dropped {dropped} of {len(blocks)} passages "
                f"to stay inside the context budget."
            )
        context = "\n\n".join(kept)
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
                rewrite = self.rewrite(req.question, history)
            else:
                rewrite = RewriteResult(req.question, fired=False, reason="not-needed")
        standalone = rewrite.text

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
                trace: dict[str, Any] = {
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
            # Finding #28: a rewrite that was rejected as drift must not look
            # identical in the trace to one that was never attempted.
            "rewrite_fired": rewrite.fired,
            "rewrite_reason": rewrite.reason,
            "rewrite_similarity": rewrite.similarity,
            "rewrite_rejected_text": rewrite.rejected_text,
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
            # R2 step 3. Was `answer.strip() == NO_ANSWER_MESSAGE` — a
            # comparison against one fixed English sentence, which missed any
            # reworded decline and every non-English one. Now structural: an
            # answer that attributes nothing is a decline whatever it says.
            abstained=output_guard.is_decline(answer, NO_ANSWER_MESSAGE)[0],
            cache_hit=prepared.trace.get("cache_hit", False),
        )
        log_event("rag_query", answer_chars=len(answer), **prepared.trace)

    @property
    def _system_prompt(self) -> str:
        if self._settings.require_support_quotes:
            return SYSTEM_PROMPT_WITH_SUPPORT
        # 2.3's clause and 2.3's fences move together: with containment off,
        # neither appears, and assembly is byte-identical to pre-2.3.
        return (SYSTEM_PROMPT if self._settings.contain_untrusted_passages
                else SYSTEM_PROMPT_NO_CONTAINMENT)

    def _check_grounding(self, answer: str, prepared: PreparedQuery) -> str:
        """P-3 D1+D6. Strip the SUPPORT block and verify every cited passage
        carries a quote that actually occurs in it.

        Reversible: require_support_quotes=false skips this entirely and
        reproduces the pre-2.4 behaviour, which a test pins.
        """
        if not self._settings.require_support_quotes or not answer:
            return answer
        if answer == NO_ANSWER_MESSAGE:
            return answer

        result = grounding.check(answer, prepared.citations)
        prepared.trace["grounding_reason"] = result.reason
        prepared.trace["grounding_emitted_quotes"] = result.emitted_quotes
        prepared.trace["grounding_cited"] = result.cited
        if result.supported:
            return result.body

        prepared.trace["grounding_rejected"] = True
        prepared.trace["grounding_unverified"] = result.unverified
        prepared.trace["grounding_raw"] = answer
        logger.warning(
            f"Answer REJECTED as ungrounded (#5/D6): reason={result.reason} "
            f"cited={result.cited} unverified={result.unverified} "
            f"raw={answer[:160]!r}"
        )
        return NO_ANSWER_MESSAGE

    def _guard_output(self, answer: str, prepared: PreparedQuery) -> str:
        """R2. The last thing that touches an answer before the user sees it.

        Runs AFTER the malformed-generation and grounding checks: those decide
        whether the generation counts as an answer at all, and there is no point
        cleaning text that is about to become the abstention message.
        """
        if answer == NO_ANSWER_MESSAGE:
            return answer
        outcome = output_guard.apply(answer, self._settings,
                                     decline_message=NO_ANSWER_MESSAGE)
        output_guard.log_counters(outcome, trace_id=prepared.trace["trace_id"])
        prepared.trace["output_guard"] = outcome.counters
        return outcome.text

    def _reject_if_malformed(self, answer: str, prepared: PreparedQuery) -> str:
        """Finding #32 (P-3 candidate D5). A generation carrying no substantive
        content is a FAILED generation, not an answer and not an abstention.

        Reversible: min_answer_chars = 0 disables the guard entirely and
        reproduces the pre-2.4 behaviour, which a test pins.
        """
        floor = self._settings.min_answer_chars
        if floor <= 0 or not answer:
            return answer
        if answer == NO_ANSWER_MESSAGE:
            return answer
        remainder = substantive_text(answer)
        if len(remainder) >= floor:
            return answer
        logger.warning(
            f"Malformed generation REJECTED (#32): {len(remainder)} substantive "
            f"chars below {floor}. raw={answer[:120]!r}"
        )
        prepared.trace["malformed_generation"] = True
        prepared.trace["malformed_raw"] = answer
        return NO_ANSWER_MESSAGE

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
                prompt=prepared.prompt, system_prompt=self._system_prompt
            )).strip()

        answer = self._reject_if_malformed(answer, prepared)
        answer = self._check_grounding(answer, prepared)
        answer = self._guard_output(answer, prepared)
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
                                                             system_prompt=self._system_prompt):
                            answer_parts.append(token)
                            yield json.dumps({"type": "token", "text": token}) + "\n"
                except Exception as e:
                    logger.error(f"LLM streaming failed: {e}")
                    yield json.dumps({"type": "error", "detail": str(e)}) + "\n"
                    return
                # Reached only when generation completed: never cache a
                # partial answer from a disconnected stream.
                answer = "".join(answer_parts).strip()
                # Finding #32: the stream has already delivered the tokens, so
                # the guard cannot un-send them. It emits a correction event so
                # the client replaces an empty bubble with the abstention, and
                # keeps the malformed text out of the cache and out of memory.
                checked = self._check_grounding(
                    self._reject_if_malformed(answer, prepared), prepared)
                if checked != answer:
                    answer_parts[:] = [checked]
                    answer = checked
                    yield json.dumps({"type": "replace", "text": checked}) + "\n"
                if prepared.cache_key and answer:
                    self._cache_set(prepared.cache_key, answer, prepared.citations)
            yield json.dumps({"type": "done"}) + "\n"
        finally:
            # Runs on client disconnect too (aclose -> GeneratorExit).
            await run_in_threadpool(self._finish, prepared, "".join(answer_parts).strip())
