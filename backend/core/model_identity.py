"""Embedding-model identity: detect model drift instead of absorbing it.

Why this exists (finding #24). `nomic-embed-text:latest` is a moving tag. If
upstream republishes it, every vector already in Qdrant was produced by a
different model than the one now answering queries — same 768 dimensions, so
the dimension guard in `qdrant_store.upsert` cannot see it, and retrieval
quietly degrades while every metric and every committed baseline silently
becomes incomparable.

The prescribed fix was to pin the model by digest. **That is not possible**:
Ollama 0.9.3 accepts only `name:tag`, and `ollama pull nomic-embed-text@sha256:…`
returns `Error: invalid model name`. `/api/show` exposes no digest at all;
`/api/tags` does. So identity is pinned by *assertion* rather than by
reference — which addresses the actual harm, since the harm was never that the
tag can move but that it can move **undetectably**.

Enforcement points (all three share this module, deliberately — one policy,
not three copies):
  * API startup      — `api/main.py` lifespan
  * worker startup   — `worker.py` on_startup
  * eval head        — `eval/run_eval.py`, before any query runs

Semantics:
  * digest mismatch                → hard fail
  * `expected_embed_model_digest` unset → loud WARNING, never a failure
  * Ollama unreachable             → defer to the existing readiness path;
                                     this module does not duplicate liveness
                                     checking and does not fail on it

Extension point for 2.1 (embed_model identity in vector payloads): the
three-way check — configured model vs. live Ollama vs. the digest recorded on
a stored point — is `verify_three_way()` below. It is written now so 2.1 wires
a payload value into an existing policy instead of growing parallel machinery.
NOTE: it cannot be retroactive. Points indexed before 2.1 carry no digest, so
`stored_digest=None` is treated as "unknown, not mismatched"; the three-way
check only becomes authoritative from the first reindex forward.
"""
from __future__ import annotations

import logging

import httpx

from core.config import Settings
from core.exceptions import ModelIdentityError

logger = logging.getLogger(__name__)

_TAGS_TIMEOUT = 10.0


def fetch_ollama_digest(settings: Settings, model: str) -> str | None:
    """Digest Ollama reports for `model`, or None if it cannot be determined.

    None covers both "Ollama unreachable" and "model not pulled yet"; callers
    must treat None as *unknown*, never as *mismatch*.
    """
    try:
        response = httpx.get(f"{settings.ollama_api_url}tags", timeout=_TAGS_TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning(
            f"Could not reach Ollama to resolve the digest for '{model}' ({e}); "
            f"deferring to the readiness check."
        )
        return None
    for entry in response.json().get("models", []):
        if entry.get("name") == model:
            digest = entry.get("digest")
            return str(digest) if digest else None
    logger.warning(f"Ollama does not list model '{model}'; digest unknown.")
    return None


def verify_embedding_model(settings: Settings, *, context: str) -> str | None:
    """Assert the live embedding model matches the pinned digest.

    Returns the observed digest (or None if undeterminable). Raises
    ModelIdentityError on a genuine mismatch.
    """
    if settings.use_openai_embedding:
        # OpenAI model names are immutable identifiers; there is no tag to move.
        return None

    observed = fetch_ollama_digest(settings, settings.embed_model)
    expected = settings.expected_embed_model_digest

    if not expected:
        logger.warning(
            "EXPECTED_EMBED_MODEL_DIGEST is not set. Embedding-model drift is "
            "UNDETECTABLE: '%s' is a moving tag, and a republish would silently "
            "invalidate every stored vector and every committed baseline. "
            "Observed digest is %s — pin it to enable enforcement.",
            settings.embed_model,
            observed or "unavailable",
        )
        return observed

    if observed is None:
        # Unknown != mismatch. Liveness is the readiness check's job.
        logger.warning(
            f"[{context}] Embedding-model digest could not be resolved; "
            f"skipping identity enforcement this time."
        )
        return None

    if observed != expected:
        raise ModelIdentityError(
            f"Embedding model identity mismatch at {context}.",
            detail=(
                f"model={settings.embed_model} expected={expected} observed={observed}. "
                f"Every vector in the collection was produced by a different model than "
                f"the one now serving queries. Re-index before continuing, or correct "
                f"EXPECTED_EMBED_MODEL_DIGEST if the change was intentional."
            ),
        )

    logger.info(f"[{context}] Embedding model identity verified: {settings.embed_model} @ {observed[:16]}…")
    return observed


def verify_generation_model(settings: Settings, *, context: str) -> str | None:
    """Assert the live generation model matches its pinned digest.

    Extends finding #24 to the generator, which carries the SAME moving-tag
    exposure the embedding model had and had no enforcement at all.

    The consequence differs, which is why this is a separate function rather
    than a parameter:

        embedding drift   invalidates every STORED VECTOR. Retrieval silently
                          degrades and no committed baseline is comparable.
        generation drift  invalidates every measured claim about ANSWER
                          BEHAVIOUR — abstention, grounding, instruction
                          following. The whole of P-3 is a statement about one
                          specific generator, and swapping it silently makes
                          those findings describe a model that is no longer
                          running.

    Same semantics as the embedding check: mismatch is fatal, unset is a loud
    warning, unreachable is not a mismatch, OpenAI is exempt.
    """
    if settings.use_openai_llm:
        # OpenAI model names are immutable identifiers; no tag to move.
        return None

    observed = fetch_ollama_digest(settings, settings.llm_model)
    expected = settings.expected_llm_model_digest

    if not expected:
        logger.warning(
            "EXPECTED_LLM_MODEL_DIGEST is not set. Generation-model drift is "
            "UNDETECTABLE: '%s' is a moving tag, and a republish would silently "
            "invalidate every measured claim about abstention, grounding and "
            "instruction-following. Observed digest is %s — pin it to enable "
            "enforcement.",
            settings.llm_model,
            observed or "unavailable",
        )
        return observed

    if observed is None:
        logger.warning(
            f"[{context}] Generation-model digest could not be resolved; "
            f"skipping identity enforcement this time."
        )
        return None

    if observed != expected:
        raise ModelIdentityError(
            f"Generation model identity mismatch at {context}.",
            detail=(
                f"model={settings.llm_model} expected={expected} observed={observed}. "
                f"Every measured claim about answer behaviour was made against a "
                f"different generator than the one now serving requests. Re-run the "
                f"generator battery before continuing, or correct "
                f"EXPECTED_LLM_MODEL_DIGEST if the change was intentional."
            ),
        )

    logger.info(
        f"[{context}] Generation model identity verified: "
        f"{settings.llm_model} @ {observed[:16]}…"
    )
    return observed


def verify_three_way(
    settings: Settings, *, context: str, stored_digest: str | None
) -> str | None:
    """Config vs. live Ollama vs. the digest recorded on a stored point.

    `stored_digest=None` means the point carries no digest. What that MEANS
    depends on whether the reindex has happened:

      digest_enforcement_from unset   the point predates phase 2.1 and is
                                      genuinely unknown. Not a mismatch.
      digest_enforcement_from set     every point was rewritten by the reindex,
                                      so a missing digest is a point that
                                      escaped it — fatal, not unknown.

    Without that marker "unknown" would be permanent, and a genuinely
    unverifiable collection would be indistinguishable from a verified one
    forever. The marker is what makes the ambiguity temporary.
    """
    observed = verify_embedding_model(settings, context=context)
    if stored_digest is None and settings.digest_enforcement_from:
        raise ModelIdentityError(
            f"A stored point carries no embedding-model digest at {context}, but "
            f"digest enforcement has been active since "
            f"{settings.digest_enforcement_from}.",
            detail=(
                "Every point should have been rewritten by the phase 2.1 reindex. "
                "This one was not, so its vector cannot be attributed to any model. "
                "Re-run eval/../reindex, or clear DIGEST_ENFORCEMENT_FROM if the "
                "reindex is known to be incomplete."
            ),
        )
    if stored_digest is None or observed is None:
        return observed
    if stored_digest != observed:
        raise ModelIdentityError(
            f"Stored vectors were produced by a different embedding model at {context}.",
            detail=(
                f"stored={stored_digest} observed={observed}. "
                f"Retrieval results from this collection are not comparable to any "
                f"baseline recorded under the stored digest."
            ),
        )
    return observed
