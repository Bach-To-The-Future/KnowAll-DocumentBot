"""Manual smoke test for the Ollama embedding endpoint (batched /api/embed —
the /api/embeddings endpoint the app used previously is deprecated).

    docker compose exec api python tests/smoke_embedding.py

RENAMED from test_embedding.py: it has no test function, but pytest imports a
module to collect it and this body performs a real HTTP embedding call. See
smoke_ollama.py for the measurement. The smoke_ prefix removes it from the
discovery pattern rather than relying on testpaths staying narrow.
"""
import httpx

resp = httpx.post(
    "http://ollama:11434/api/embed",
    json={"model": "nomic-embed-text", "input": ["hello world", "second text"]},
    timeout=60,
)
print(resp.status_code)
data = resp.json()
embeddings = data.get("embeddings", [])
print(f"{len(embeddings)} embeddings, dim={len(embeddings[0]) if embeddings else 0}")
