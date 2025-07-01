from qdrant_client import QdrantClient
from app.config import Config

config = Config()
client = QdrantClient(host=config.QDRANT_HOST, port=config.QDRANT_PORT)

# Check collection existence and size
collections = client.get_collections().collections
print("[🧠 Qdrant] Available collections:", [c.name for c in collections])

if config.COLLECTION_NAME not in [c.name for c in collections]:
    print("❌ Collection does not exist.")
else:
    info = client.get_collection(config.COLLECTION_NAME)
    print(f"✅ Collection '{config.COLLECTION_NAME}' has {info.vectors_count} vectors.")

    # Check actual content
    points, _ = client.scroll(
        collection_name=config.COLLECTION_NAME,
        limit=5,
        with_payload=True
    )
    for p in points:
        print("→ Point ID:", p.id)
        print("→ Embedding length:", len(p.vector))
        print("→ Payload:", p.payload)
