import os
from typing import List, Dict, Any
from dotenv import load_dotenv
from nomic import embed
import nomic
from app.config import Config

load_dotenv()
config = Config()

# Login to nomic
nomic.login(token=os.getenv("NOMIC_API_KEY"))

def embed_nodes(nodes: List[Any]) -> List[Dict[str, Any]]:
    """
    Given a list of nodes (each with .text and .metadata), get embeddings from Nomic API.

    Returns:
        List of dicts with 'embedding', 'text', and 'metadata' keys.
    """
    if not nodes or not all(hasattr(n, "text") for n in nodes):
        raise ValueError("Each node must have a 'text' attribute.")

    # Filter only nodes with non-blank text
    filtered_nodes = [n for n in nodes if n.text and n.text.strip()]
    texts = [n.text for n in filtered_nodes]

    print(f"[🔢] Total nodes: {len(nodes)} | Non-blank: {len(filtered_nodes)}")

    if not texts:
        print("⚠️ No valid text chunks found for embedding.")
        return []

    try:
        response = embed.text(
            texts=texts,
            model=config.EMBED_MODEL
        )
        embeddings = response["embeddings"]
    except Exception as e:
        raise RuntimeError(f"❌ Embedding API failed: {e}")

    # Sanity check
    if len(embeddings) != len(filtered_nodes):
        raise ValueError(f"❌ Mismatch: {len(embeddings)} embeddings vs {len(filtered_nodes)} nodes")

    results = []
    for node, emb in zip(filtered_nodes, embeddings):
        results.append({
            "embedding": emb,
            "text": node.text,
            "metadata": node.metadata
        })

    print(f"[✅] Embedded {len(results)} chunks.")
    for r in results[:2]:
        print(f"[🧠 Vector] Text: {r['text'][:40]} | Embedding: {len(r['embedding'])} | Meta: {r['metadata']}")
    return results

# ✅ Standalone test
if __name__ == "__main__":
    class DummyNode:
        def __init__(self, text, metadata=None):
            self.text = text
            self.metadata = metadata or {}

    test_nodes = [
        DummyNode("What is the capital of France?", {"source": "test1"}),
        DummyNode("Explain the concept of recursion.", {"source": "test2"}),
        DummyNode("   ", {"source": "blank"}),  # Should be ignored
    ]

    try:
        results = embed_nodes(test_nodes)
        for r in results:
            print(f"\n📌 Text: {r['text'][:40]}...")
            print(f"🔖 Metadata: {r['metadata']}")
            print(f"📐 Embedding length: {len(r['embedding'])}")
    except Exception as e:
        print("❌ Error during embedding:", e)
