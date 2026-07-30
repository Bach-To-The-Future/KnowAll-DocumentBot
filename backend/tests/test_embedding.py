"""Manual smoke test for the Ollama embedding endpoint (batched /api/embed —
the /api/embeddings endpoint the app used previously is deprecated)."""
import requests

resp = requests.post(
    "http://ollama:11434/api/embed",
    json={"model": "nomic-embed-text", "input": ["hello world", "second text"]},
    timeout=60,
)
print(resp.status_code)
data = resp.json()
embeddings = data.get("embeddings", [])
print(f"{len(embeddings)} embeddings, dim={len(embeddings[0]) if embeddings else 0}")
