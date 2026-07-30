"""Manual smoke check: inspect the Qdrant collection contents.
Run inside the api container: python tests/check_qdrant.py"""
from qdrant_client import QdrantClient

from core.config import get_settings

settings = get_settings()
client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)

collections = [c.name for c in client.get_collections().collections]
print("[Qdrant] Available collections:", collections)

if settings.qdrant_collection not in collections:
    print("Collection does not exist.")
else:
    info = client.get_collection(settings.qdrant_collection)
    print(f"Collection '{settings.qdrant_collection}': {info.points_count} points.")

    points, _ = client.scroll(
        collection_name=settings.qdrant_collection,
        limit=5,
        with_payload=True,
    )
    for p in points:
        payload = p.payload or {}
        print("-> Point ID:", p.id)
        print("   Source:", payload.get("source"), "| chunk_seq:", payload.get("chunk_seq"),
              "| etag:", payload.get("etag"))
        print("   Text:", (payload.get("text") or "")[:80].replace("\n", " "), "...")
