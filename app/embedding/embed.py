import os
import requests
from typing import List, Dict, Any
import warnings
from config import Config

config = Config()

OLLAMA_EMBEDDING_URL = f"{config.OLLAMA_API_URL}embeddings"
EMBED_MODEL = config.EMBED_MODEL  

def get_ollama_embeddings(texts: List[str], model: str) -> List[List[float]]:
    try:
        response = requests.post(
            OLLAMA_EMBEDDING_URL,
            json={"model": model, "prompt": texts}
        )
        response.raise_for_status()
        data = response.json()
        # Ollama returns {"embeddings": [embedding1, embedding2, ...]}
        return data.get("embeddings", [])
    except Exception as e:
        raise RuntimeError(f"❌ Failed to fetch embeddings from Ollama: {e}")

def embed_nodes(nodes: List[Any]) -> List[Dict[str, Any]]:
    """
    Given a list of nodes (each with .text and .metadata), get embeddings using Ollama.
    """
    if not nodes or not all(hasattr(n, "text") for n in nodes):
        raise ValueError("Each node must have a 'text' attribute.")

    filtered_nodes = [n for n in nodes if n.text and n.text.strip()]
    texts = [n.text for n in filtered_nodes]

    print(f"[🔢] Total nodes: {len(nodes)} | Non-blank: {len(filtered_nodes)}")

    if not texts:
        print("⚠️ No valid text chunks found for embedding.")
        return []

    results = []
    failed = []

    try:
        embeddings = get_ollama_embeddings(texts, EMBED_MODEL)
    except Exception as e:
        raise RuntimeError(f"❌ Embedding failed for all chunks: {e}")

    for node, emb in zip(filtered_nodes, embeddings):
        if emb is not None:
            results.append({
                "embedding": emb,  # Already a list
                "text": node.text,
                "metadata": node.metadata
            })
        else:
            warnings.warn(f"❌ Embedding returned None for chunk: {node.text[:30]!r}")
            failed.append({"text": node.text, "metadata": node.metadata, "error": "None embedding"})

    print(f"[✅] Embedded {len(results)} chunks.")
    if failed:
        print(f"[⚠️] {len(failed)} chunk(s) failed to embed.")
        for f in failed[:2]:
            print(f"[WARN] Failed chunk: {f['text'][:40]!r} | Error: {f['error']}")

    for r in results[:2]:
        print(f"[🧠 Vector] Text: {r['text'][:40]} | Embedding: {len(r['embedding'])} | Meta: {r['metadata']}")

    return results