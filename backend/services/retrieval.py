"""RetrievalService: hybrid fetch -> optional multi-query pooling ->
cross-encoder rerank -> context expansion (section-parent or ±window).

Depends only on the VectorStore / DenseEmbedder / Reranker interfaces.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from core.config import Settings
from core.interfaces import DenseEmbedder, Reranker, VectorStore
from models.schemas import RetrievedChunk, ScoredChunk

logger = logging.getLogger(__name__)


class RetrievalService:
    def __init__(self, vector_store: VectorStore, embedder: DenseEmbedder,
                 reranker: Reranker, settings: Settings) -> None:
        self._vector_store = vector_store
        self._embedder = embedder
        self._reranker = reranker
        self._settings = settings
        # Fan-out pool for query variants. Small on purpose: the win is
        # overlapping the expansion LLM call with the primary retrieval.
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="retrieval")

    # --- candidate fetch -----------------------------------------------------

    def fetch_candidates(self, query: str, filters: list[str] | None) -> list[ScoredChunk]:
        dense = self._embedder.embed_query(query)
        return self._vector_store.hybrid_search(
            dense_vector=dense,
            query_text=query,
            k=self._settings.retrieval_fetch_k,
            filter_sources=filters,
        )

    # --- context expansion -----------------------------------------------------

    def _expand_with_neighbors(self, selected: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """±window mode. A per-source 'claimed' set prevents the same neighbor
        text from being attached to two overlapping windows."""
        window = self._settings.neighbor_window
        if window <= 0 or not selected:
            return selected

        claimed: dict[str, set[int]] = {}
        for chunk in selected:
            seq = chunk.metadata.get("chunk_seq")
            if seq is not None:
                claimed.setdefault(chunk.source, set()).add(seq)

        for chunk in selected:  # rank order: best chunks claim neighbors first
            seq = chunk.metadata.get("chunk_seq")
            if seq is None:
                continue
            wanted = [
                seq + delta
                for delta in range(-window, window + 1)
                if delta != 0 and seq + delta >= 0 and (seq + delta) not in claimed[chunk.source]
            ]
            if not wanted:
                continue
            neighbors = self._vector_store.fetch_chunks_by_seq(chunk.source, wanted)
            claimed[chunk.source].update(neighbors.keys())

            dedup = self._prefix_stripper(chunk.metadata.get("section_title"))
            before = [dedup(neighbors[s]) for s in sorted(neighbors) if s < seq]
            after = [dedup(neighbors[s]) for s in sorted(neighbors) if s > seq]
            chunk.text = "\n".join(before + [chunk.text] + after)
        return selected

    @staticmethod
    def _prefix_stripper(section: str | None) -> Callable[[str], str]:
        """Same-section neighbors repeat the heading-path prefix the core
        chunk already carries; strip it so the merged passage reads as one
        text. Cross-section prefixes are kept — they're informative."""
        prefix = f"{section}\n\n" if section else None

        def strip(text: str) -> str:
            if prefix and text.startswith(prefix):
                return text[len(prefix):]
            return text

        return strip

    def _expand_with_sections(self, selected: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Parent-document retrieval: walk outward from the winner's chunk_seq
        through its section — alternating before/after, stopping per direction
        at a seq gap — until parent_char_budget is spent."""
        claimed: dict[str, set[int]] = {}
        for chunk in selected:
            seq = chunk.metadata.get("chunk_seq")
            if seq is not None:
                claimed.setdefault(chunk.source, set()).add(seq)

        for chunk in selected:
            seq = chunk.metadata.get("chunk_seq")
            if seq is None:
                continue
            section = chunk.metadata.get("section_title")
            if section:
                section_texts = self._vector_store.fetch_section_chunks(chunk.source, section)
            else:
                # No section metadata (e.g. PDF pages): plain ±1 window.
                wanted = [s for s in (seq - 1, seq + 1) if s >= 0]
                section_texts = self._vector_store.fetch_chunks_by_seq(chunk.source, wanted)
                section_texts[seq] = chunk.text

            dedup = self._prefix_stripper(section)
            budget = self._settings.parent_char_budget - len(chunk.text)
            taken = claimed.setdefault(chunk.source, set())
            before: list[str] = []
            after: list[str] = []
            lo, hi = seq - 1, seq + 1
            lo_open, hi_open = True, True
            while budget > 0 and (lo_open or hi_open):
                if lo_open:
                    if lo >= 0 and lo in section_texts and lo not in taken:
                        text = dedup(section_texts[lo])
                        if len(text) <= budget:
                            before.insert(0, text)
                            budget -= len(text)
                            taken.add(lo)
                            lo -= 1
                        else:
                            lo_open = False
                    else:
                        lo_open = False  # gap, claimed, or start of section
                if hi_open and budget > 0:
                    if hi in section_texts and hi not in taken:
                        text = dedup(section_texts[hi])
                        if len(text) <= budget:
                            after.append(text)
                            budget -= len(text)
                            taken.add(hi)
                            hi += 1
                        else:
                            hi_open = False
                    else:
                        hi_open = False

            if before or after:
                chunk.text = "\n".join(before + [chunk.text] + after)
        return selected

    def _expand_context(self, selected: list[RetrievedChunk]) -> list[RetrievedChunk]:
        mode = self._settings.retrieval_context_mode
        if mode == "off" or not selected:
            return selected
        if mode == "window":
            return self._expand_with_neighbors(selected)
        return self._expand_with_sections(selected)

    # --- rerank ---------------------------------------------------------------

    def _rerank_pool(self, query: str, pooled: dict[str, ScoredChunk], k: int) -> list[RetrievedChunk]:
        """Rerank a pooled candidate set against the ORIGINAL query, apply the
        score floor (empty result drives instructed abstention), expand."""
        candidates = [c for c in pooled.values() if c.text.strip()]
        if not candidates:
            return []

        scores = self._reranker.scores(query, [c.text for c in candidates])
        scored = sorted(zip(scores, candidates), key=lambda item: item[0], reverse=True)

        floor = self._settings.rerank_score_floor
        selected = [
            RetrievedChunk(
                text=candidate.text,
                source=candidate.payload.get("source", "unknown"),
                page_number=candidate.payload.get("page_number"),
                score=round(score, 4),
                point_id=candidate.point_id,
                metadata=candidate.payload,
            )
            for score, candidate in scored[:k]
            if score >= floor
        ]
        logger.info(
            f"Reranked {len(candidates)} candidates -> {len(selected)} above score "
            f"floor {floor} (top score: {scored[0][0]:.3f})"
        )
        return self._expand_context(selected)

    @staticmethod
    def _clean_variants(query: str, variants: list[str] | None) -> list[str]:
        return [
            v.strip() for v in (variants or [])
            if v and v.strip() and v.strip().lower() != query.strip().lower()
        ]

    # --- public API -------------------------------------------------------------

    def retrieve(self, query: str, filters: list[str] | None = None,
                 k: int | None = None,
                 expanded_queries: list[str] | None = None) -> list[RetrievedChunk]:
        """Sequential retrieval (eval harness and simple callers)."""
        k = k or self._settings.rerank_top_n
        pooled: dict[str, ScoredChunk] = {}
        for variant in [query] + self._clean_variants(query, expanded_queries):
            for candidate in self.fetch_candidates(variant, filters):
                pooled.setdefault(candidate.point_id, candidate)
        return self._rerank_pool(query, pooled, k)

    def retrieve_with_expansion(
        self,
        query: str,
        filters: list[str] | None = None,
        k: int | None = None,
        expander: Optional[Callable[[], list[str]]] = None,
    ) -> tuple[list[RetrievedChunk], list[str]]:
        """Latency-optimized: `expander` (an LLM call producing variants) runs
        CONCURRENTLY with the primary hybrid fetch, then variant fetches fan
        out in parallel. Returns (chunks, variants_used)."""
        k = k or self._settings.rerank_top_n
        expansion_future = self._executor.submit(expander) if expander else None

        pooled: dict[str, ScoredChunk] = {}
        for candidate in self.fetch_candidates(query, filters):
            pooled.setdefault(candidate.point_id, candidate)

        variants: list[str] = []
        if expansion_future is not None:
            try:
                variants = self._clean_variants(query, expansion_future.result())
            except Exception as e:
                logger.warning(f"Query expansion failed, continuing without: {e}")

        if variants:
            futures = [self._executor.submit(self.fetch_candidates, v, filters) for v in variants]
            for future in futures:
                try:
                    for candidate in future.result():
                        pooled.setdefault(candidate.point_id, candidate)
                except Exception as e:
                    # A failed variant fetch costs recall, never the request.
                    logger.warning(f"Variant fetch failed: {e}")

        return self._rerank_pool(query, pooled, k), variants
