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
from core.model_identity import verify_embedding_model, verify_three_way

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
