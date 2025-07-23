import os
import requests
from typing import List, Dict, Any
import warnings
import logging
from config import Config
import openai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config = Config()
OLLAMA_EMBEDDING_URL = f"{config.OLLAMA_API_URL}embeddings"
EMBED_MODEL = config.EMBED_MODEL
USE_OPENAI_EMBEDDING = config.USE_OPENAI_EMBEDDING

def check_ollama_model(model: str) -> bool:
    """Check if the specified model is available in Ollama."""
    try:
        response = requests.get(f"{config.OLLAMA_API_URL}tags", timeout=10)
        response.raise_for_status()
        models = response.json().get("models", [])
        model_names = [m["name"] for m in models]
        logger.info(f"Available Ollama models: {model_names}")
        if model not in model_names:
            logger.error(f"Model '{model}' not found in Ollama. Available models: {model_names}")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to check Ollama models: {e}")
        return False

def get_ollama_embeddings(texts: List[str], model: str) -> List[List[float]]:
    """Generate embeddings using the local Ollama server."""
    if not check_ollama_model(model):
        raise RuntimeError(f"Model '{model}' not found in Ollama. Ensure it is pulled and loaded.")

    embeddings = []
    for text in texts:
        try:
            if not text.strip():
                logger.warning(f"Skipping empty text for embedding")
                continue
            response = requests.post(
                OLLAMA_EMBEDDING_URL,
                json={"model": model, "prompt": text},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            embedding = data.get("embedding")
            if not embedding or not isinstance(embedding, list):
                logger.warning(f"No valid embedding returned for text: {text[:30]!r}")
                continue
            embeddings.append(embedding)
            logger.debug(f"Generated embedding for text: {text[:30]!r}, length: {len(embedding)}")
        except Exception as e:
            logger.error(f"Failed to fetch embedding for text: {text[:30]!r}, error: {e}")
    if not embeddings:
        raise RuntimeError("❌ Embedding failed for all chunks")
    return embeddings

def get_openai_embeddings(texts: List[str], model: str) -> List[List[float]]:
    """Generate embeddings using OpenAI API."""
    try:
        client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
        response = client.embeddings.create(input=texts, model=model)
        embeddings = [data.embedding for data in response.data]
        logger.info(f"Generated {len(embeddings)} embeddings using OpenAI {model}")
        return embeddings
    except Exception as e:
        logger.error(f"Failed to fetch OpenAI embeddings: {e}")
        raise RuntimeError(f"❌ OpenAI embedding failed: {e}")

def get_embeddings(texts: List[str], model: str) -> List[List[float]]:
    """Generate embeddings based on configuration."""
    if USE_OPENAI_EMBEDDING:
        return get_openai_embeddings(texts, model)
    return get_ollama_embeddings(texts, model)

def embed_nodes(nodes: List[Any]) -> List[Dict[str, Any]]:
    if not nodes or not all(hasattr(n, "text") for n in nodes):
        raise ValueError("Each node must have a 'text' attribute.")

    filtered_nodes = [n for n in nodes if n.text and n.text.strip()]
    texts = [n.text for n in filtered_nodes]

    logger.info(f"[🔢] Total nodes: {len(nodes)} | Non-blank: {len(filtered_nodes)}")

    if not texts:
        logger.warning("⚠️ No valid text chunks found for embedding.")
        return []

    results = []
    failed = []

    try:
        embeddings = get_embeddings(texts, EMBED_MODEL)
    except Exception as e:
        raise RuntimeError(f"❌ Embedding failed for all chunks: {e}")

    for node, emb in zip(filtered_nodes, embeddings):
        if emb is not None:
            results.append({
                "embedding": emb,
                "text": node.text,
                "metadata": node.metadata
            })
        else:
            logger.warning(f"Embedding returned None for chunk: {node.text[:30]!r}")
            failed.append({"text": node.text, "metadata": node.metadata, "error": "None embedding"})

    logger.info(f"[✅] Embedded {len(results)} chunks.")
    if failed:
        logger.warning(f"[⚠️] {len(failed)} chunk(s) failed to embed.")
        for f in failed[:2]:
            logger.warning(f"[WARN] Failed chunk: {f['text'][:40]!r} | Error: {f['error']}")

    for r in results[:2]:
        logger.info(f"[🧠 Vector] Text: {r['text'][:40]} | Embedding: {len(r['embedding'])} | Meta: {r['metadata']}")

    return results