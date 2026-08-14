"""Manual smoke check: inspect the Qdrant collection contents.

    docker compose exec api python tests/check_qdrant.py

NOT a pytest test despite living under tests/ — it has no test function and
pytest.ini restricts collection to tests/unit. It is the only interactive way to
look at what is actually stored.

Both keyword arguments below are load-bearing, and they arrive together:

  api_key  — without it this raised 401 on every run once Qdrant authentication
             was enabled, and the traceback reads as "Qdrant is down" rather
             than "this script is stale". A diagnostic that lies is worse than
             one that is missing.
  https    — qdrant-client implicitly switches to HTTPS the moment an api_key is
             set. Adding only the key turns the 401 into
             "[SSL] record layer failure", which is not an improvement.

integrations/qdrant_store.py is the authority on constructing this client; keep
this in step with it rather than rediscovering the pair.
"""
from qdrant_client import QdrantClient

from core.config import get_settings

settings = get_settings()
client = QdrantClient(
    host=settings.qdrant_host,
    port=settings.qdrant_port,
    api_key=settings.qdrant_api_key,
    https=settings.qdrant_https,
    timeout=settings.qdrant_timeout,
)

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
