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

    texts = [node.text for node in nodes if node.text.strip()]
    if not texts:
        return []

    try:
        response = embed.text(
            texts=texts,
            model=config.EMBED_MODEL
        )
        embeddings = response["embeddings"]
    except Exception as e:
        raise RuntimeError(f"Embedding API failed: {e}")

    results = []
    for node, embedding in zip(nodes, embeddings):
        results.append({
            "embedding": embedding,
            "text": node.text,
            "metadata": node.metadata
        })

    return results


# Test
if __name__ == "__main__":
    class DummyNode:
        def __init__(self, text, metadata=None):
            self.text = text
            self.metadata = metadata or {}

    # Sample data for testing
    test_nodes = [
        DummyNode("What is the capital of France?", {"source": "test1"}),
        DummyNode("Explain the concept of recursion.", {"source": "test2"})
    ]

    try:
        results = embed_nodes(test_nodes)
        for r in results:
            print(f"Text: {r['text'][:30]}...")
            print(f"Metadata: {r['metadata']}")
            print(f"Embedding length: {len(r['embedding'])}")
            print("---")
    except Exception as e:
        print("Error during embedding:", e)
