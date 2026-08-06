"""Cross-layer constants.

Phase 4.5. `CORPUS_VERSION_KEY` lived in `services/query.py`, so
`services/ingestion.py` imported from `services/query.py` to invalidate the
answer cache — a service reaching sideways into a peer for a bare string. The
layering rule is that `services/` depends on `core/`, never on each other.
"""
from __future__ import annotations

# Bumped by ingestion whenever the corpus changes; folded into the answer-cache
# key so a stale answer cannot outlive the documents it was derived from.
CORPUS_VERSION_KEY = "corpus:version"
