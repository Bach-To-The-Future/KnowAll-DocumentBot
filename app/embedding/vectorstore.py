from qdrant_client import QdrantClient
from qdrant_client.http import models
from config import Config
import uuid

config = Config()
COLLECTION_NAME = config.QDRANT_COLLECTION
QDRANT_HOST = config.QDRANT_HOST
QDRANT_PORT = config.QDRANT_PORT
EMBED_DIM = config.EMBED_DIM  

# --- Initialize Qdrant connection ---
try:
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    client.get_collections()
except Exception as e:
    raise RuntimeError(f"Failed to connect to Qdrant at {QDRANT_HOST}:{QDRANT_PORT} -> {e}")

def ensure_collection():
    existing = [c.name for c in client.get_collections().collections]
    print(f"[Qdrant] Existing collections: {existing}")
    if COLLECTION_NAME not in existing:
        print(f"[Qdrant] Creating collection: {COLLECTION_NAME}")
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=EMBED_DIM,  # Use the correct dimension for your embedding model!
                distance=models.Distance.COSINE
            )
        )

def upsert_vectors(vectors):
    ensure_collection()
    points = []
    for v in vectors:
        emb = v['embedding']
        if len(emb) != EMBED_DIM:
            print(f"[WARN] Embedding size {len(emb)} does not match expected {EMBED_DIM}. Skipping.")
            continue
        print(f"Upserting vector -> text: {v['text'][:50]}..., emb_len: {len(emb)}, meta: {v['metadata']}")
        points.append(
            models.PointStruct(
                id=str(uuid.uuid4()),
                vector=emb,
                payload={
                    "text": v["text"],
                    **v["metadata"]  # Must include 'source'
                }
            )
        )
    if not points:
        print("No vectors to upsert.")
    else:
        print(f"Upserting {len(points)} vectors to Qdrant.")
        client.upsert(collection_name=COLLECTION_NAME, points=points)

def search_similar(query_embedding, k=5, filter_docs=None):
    if COLLECTION_NAME not in [c.name for c in client.get_collections().collections]:
        raise RuntimeError(f"[Qdrant] Collection '{COLLECTION_NAME}' does not exist. Cannot perform search.")

    filter_payload = None
    if filter_docs:
        filter_payload = models.Filter(
            must=[
                models.FieldCondition(
                    key="source",
                    match=models.MatchAny(any=filter_docs)
                )
            ]
        )

    print("[Qdrant] Filter:", filter_payload)
    print("[Qdrant] Querying with embedding length:", len(query_embedding))
    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_embedding,
        limit=k,
        query_filter=filter_payload
    )
    print("[Qdrant] Matches found:", len(results))

    unique = {}
    for r in results:
        key = (r.payload.get("text"), r.payload.get("source"))
        if key not in unique:
            unique[key] = r

    deduped_results = list(unique.values())
    print(f"[Qdrant] Deduplicated to {len(deduped_results)} results.")
    return deduped_results

def delete_vectors_by_source(source_name: str):
    if COLLECTION_NAME not in [c.name for c in client.get_collections().collections]:
        print(f"[Qdrant] Collection '{COLLECTION_NAME}' does not exist.")
        return

    filter_payload = models.Filter(
        must=[
            models.FieldCondition(
                key="source",
                match=models.MatchValue(value=source_name)
            )
        ]
    )

    hits = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=filter_payload,
        with_payload=False,
        with_vectors=False,
        limit=10000
    )

    ids_to_delete = [point.id for point in hits[0]]

    if not ids_to_delete:
        print(f"[Qdrant] No vectors found for source: {source_name}")
    else:
        print(f"Deleting {len(ids_to_delete)} vectors for source: {source_name}")
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=models.PointIdsList(points=ids_to_delete)
        )

def delete_collection():
    client.delete_collection(collection_name=COLLECTION_NAME)

def reset_collection():
    delete_collection()
    ensure_collection()