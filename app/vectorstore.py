from qdrant_client import QdrantClient
from qdrant_client.http import models
from app.config import Config
import uuid

config = Config()
COLLECTION_NAME = config.COLLECTION_NAME

# --- ✅ Initialize Qdrant connection ---
try:
    client = QdrantClient(host=config.QDRANT_HOST, port=config.QDRANT_PORT)
    client.get_collections()
except Exception as e:
    raise RuntimeError(f"❌ Failed to connect to Qdrant at {config.QDRANT_HOST}:{config.QDRANT_PORT} → {e}")

# --- ✅ Ensure collection exists ---
def ensure_collection():
    existing = [c.name for c in client.get_collections().collections]
    print(f"[Qdrant] Existing collections: {existing}")
    if COLLECTION_NAME not in existing:
        print(f"[Qdrant] Creating collection: {COLLECTION_NAME}")
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=768,
                distance=models.Distance.COSINE
            )
        )

# --- ✅ Upsert document chunks into Qdrant ---
def upsert_vectors(vectors):
    ensure_collection()
    points = []
    for v in vectors:
        print(f"🔍 Upserting vector → text: {v['text'][:50]}..., emb_len: {len(v['embedding'])}, meta: {v['metadata']}")
        points.append(
            models.PointStruct(
                id=str(uuid.uuid4()),
                vector=v["embedding"],
                payload={
                    "text": v["text"],
                    **v["metadata"]  # Must include 'source'
                }
            )
        )
    if not points:
        print("⚠️ No vectors to upsert.")
    else:
        print(f"🚀 Upserting {len(points)} vectors to Qdrant.")
        client.upsert(collection_name=COLLECTION_NAME, points=points)

# --- ✅ Search with optional filtering by document source ---
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

    # --- ✅ Deduplicate by (text + source) ---
    unique = {}
    for r in results:
        key = (r.payload.get("text"), r.payload.get("source"))
        if key not in unique:
            unique[key] = r

    deduped_results = list(unique.values())
    print(f"[Qdrant] Deduplicated to {len(deduped_results)} results.")
    return deduped_results

# --- ✅ Delete vectors by source (document name) ---
def delete_vectors_by_source(source_name: str):
    if COLLECTION_NAME not in [c.name for c in client.get_collections().collections]:
        print(f"[Qdrant] Collection '{COLLECTION_NAME}' does not exist.")
        return

    # Search for all points with this source
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
        limit=10000  # Adjust depending on your chunk volume
    )

    ids_to_delete = [point.id for point in hits[0]]

    if not ids_to_delete:
        print(f"[Qdrant] No vectors found for source: {source_name}")
    else:
        print(f"🗑️ Deleting {len(ids_to_delete)} vectors for source: {source_name}")
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=models.PointIdsList(points=ids_to_delete)
        )


# --- ✅ Optional utilities ---
def delete_collection():
    client.delete_collection(collection_name=COLLECTION_NAME)

def reset_collection():
    delete_collection()
    ensure_collection()
