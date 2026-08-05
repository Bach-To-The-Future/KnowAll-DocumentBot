"""Finding #24: embedding-model drift must be impossible to miss.

Ollama cannot pull by digest, so identity is enforced by assertion. These
tests pin the exact semantics agreed with the maintainer:

    mismatch            -> hard fail
    expected unset      -> loud warning, never a failure
    Ollama unreachable  -> not a mismatch (readiness owns liveness)
    three-way, no stored digest -> not retroactive
"""
import logging

import pytest

from core.config import Settings
from core.exceptions import ModelIdentityError
from core.model_identity import (
    verify_embedding_model,
    verify_generation_model,
    verify_three_way,
)

LIVE = "sha256:0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f"
OTHER = "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"


def settings(**kw) -> Settings:
    """`_env_file=None` skips the dotenv file but NOT os.environ, and the api and
    worker services both export EXPECTED_EMBED_MODEL_DIGEST (that export is the
    F24 enforcement — it must stay). Without pinning the fields under test here,
    the in-container run inherits a real digest and the "unset" case silently
    becomes the "set" case. Explicit defaults, overridable per test."""
    kw.setdefault("expected_embed_model_digest", None)
    kw.setdefault("use_openai_embedding", False)
    return Settings(_env_file=None, **kw)


@pytest.fixture
def observed(monkeypatch):
    """Patch the digest lookup; returns a setter so each test picks a value."""
    import core.model_identity as mod

    def _set(value):
        monkeypatch.setattr(mod, "fetch_ollama_digest", lambda s, m: value)

    return _set


def test_mismatch_is_fatal(observed):
    observed(LIVE)
    with pytest.raises(ModelIdentityError, match="identity mismatch"):
        verify_embedding_model(settings(expected_embed_model_digest=OTHER), context="test")


def test_match_passes_and_returns_digest(observed):
    observed(LIVE)
    result = verify_embedding_model(
        settings(expected_embed_model_digest=LIVE), context="test"
    )
    assert result == LIVE


def test_unset_expectation_warns_but_does_not_fail(observed, caplog):
    observed(LIVE)
    with caplog.at_level(logging.WARNING):
        result = verify_embedding_model(settings(), context="test")
    assert result == LIVE  # no exception
    assert "UNDETECTABLE" in caplog.text


def test_unreachable_ollama_is_not_a_mismatch(observed):
    # None means "unknown". Failing here would duplicate the readiness check
    # and make a slow Ollama boot look like model drift.
    observed(None)
    assert verify_embedding_model(
        settings(expected_embed_model_digest=LIVE), context="test"
    ) is None


def test_openai_backend_is_exempt(monkeypatch):
    # OpenAI model names are immutable; there is no moving tag to police.
    import core.model_identity as mod

    monkeypatch.setattr(mod, "fetch_ollama_digest",
                        lambda s, m: pytest.fail("must not query Ollama"))
    assert verify_embedding_model(
        settings(use_openai_embedding=True, expected_embed_model_digest=OTHER),
        context="test",
    ) is None


# --- three-way (2.1 extension point) ---------------------------------------

def test_three_way_flags_stored_vectors_from_another_model(observed):
    observed(LIVE)
    with pytest.raises(ModelIdentityError, match="different embedding model"):
        verify_three_way(
            settings(expected_embed_model_digest=LIVE),
            context="test", stored_digest=OTHER,
        )


def test_three_way_is_not_retroactive(observed):
    # Points indexed before 2.1 carry no digest. Unknown != mismatch, or every
    # existing deployment would fail closed on first boot.
    observed(LIVE)
    assert verify_three_way(
        settings(expected_embed_model_digest=LIVE),
        context="test", stored_digest=None,
    ) == LIVE


# --- phase 2.1: digest_enforcement_from makes "unknown" temporary ------------

def test_missing_digest_is_unknown_before_enforcement(observed):
    """The 376 legacy points predate 2.1. Until the reindex has run, a point
    without a digest is genuinely unverifiable, not wrong."""
    observed(LIVE)
    assert verify_three_way(
        settings(expected_embed_model_digest=LIVE), context="test",
        stored_digest=None,
    ) == LIVE


def test_missing_digest_is_FATAL_after_enforcement(observed):
    """Once the reindex has rewritten every point, a point without a digest is
    one that escaped it. Without this the ambiguity would be permanent."""
    observed(LIVE)
    with pytest.raises(ModelIdentityError, match="no embedding-model digest"):
        verify_three_way(
            settings(expected_embed_model_digest=LIVE,
                     digest_enforcement_from="2026-08-05T00:00:00Z"),
            context="test", stored_digest=None,
        )


def test_a_matching_stored_digest_passes_under_enforcement(observed):
    observed(LIVE)
    assert verify_three_way(
        settings(expected_embed_model_digest=LIVE,
                 digest_enforcement_from="2026-08-05T00:00:00Z"),
        context="test", stored_digest=LIVE,
    ) == LIVE


def test_a_mismatched_stored_digest_is_fatal_either_way(observed):
    observed(LIVE)
    for marker in (None, "2026-08-05T00:00:00Z"):
        with pytest.raises(ModelIdentityError, match="different embedding model"):
            verify_three_way(
                settings(expected_embed_model_digest=LIVE,
                         digest_enforcement_from=marker),
                context="test", stored_digest=OTHER,
            )


# --- F24 extended to the GENERATION model -------------------------------------

def gen_settings(**kw) -> Settings:
    kw.setdefault("expected_llm_model_digest", None)
    kw.setdefault("use_openai_llm", False)
    return settings(**kw)


@pytest.fixture
def observed_llm(monkeypatch):
    import core.model_identity as mod

    def _set(value):
        monkeypatch.setattr(mod, "fetch_ollama_digest", lambda s, m: value)

    return _set


def test_generation_mismatch_is_fatal(observed_llm):
    observed_llm(LIVE)
    with pytest.raises(ModelIdentityError, match="Generation model identity mismatch"):
        verify_generation_model(gen_settings(expected_llm_model_digest=OTHER),
                                context="test")


def test_generation_match_passes(observed_llm):
    observed_llm(LIVE)
    assert verify_generation_model(
        gen_settings(expected_llm_model_digest=LIVE), context="test") == LIVE


def test_generation_unset_warns_but_does_not_fail(observed_llm, caplog):
    """Same semantics as the embedding check: unset is loud, never fatal."""
    observed_llm(LIVE)
    with caplog.at_level(logging.WARNING):
        assert verify_generation_model(gen_settings(), context="test") == LIVE
    assert "UNDETECTABLE" in caplog.text
    # The warning must name the consequence specific to the GENERATOR.
    assert "grounding" in caplog.text and "instruction-following" in caplog.text


def test_generation_unreachable_is_not_a_mismatch(observed_llm):
    observed_llm(None)
    assert verify_generation_model(
        gen_settings(expected_llm_model_digest=LIVE), context="test") is None


def test_openai_generation_is_exempt(monkeypatch):
    import core.model_identity as mod
    monkeypatch.setattr(mod, "fetch_ollama_digest",
                        lambda s, m: pytest.fail("must not query Ollama"))
    assert verify_generation_model(
        gen_settings(use_openai_llm=True, expected_llm_model_digest=OTHER),
        context="test") is None


def test_the_two_checks_are_independent(observed_llm):
    """A pinned embedding model must not imply a pinned generator, or the
    generator's exposure hides behind the embedding model's enforcement."""
    observed_llm(LIVE)
    s = gen_settings(expected_embed_model_digest=LIVE, expected_llm_model_digest=OTHER)
    assert verify_embedding_model(s, context="test") == LIVE
    with pytest.raises(ModelIdentityError):
        verify_generation_model(s, context="test")
