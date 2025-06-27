from qdrant_client import QdrantClient
from qdrant_client.http import models
from app.config import Config
import uuid

config = Config()

client = QdrantCLient(host=config.QDRANT_HOST, port=config.QDRANT_PORT)
COLLECTION_NAME = config.COLLECTION_NAME

def ensure_collection():
    if COLLECTION_NAME not in [c.name for c in client.get_collections().collections]:
        client.create_collection(
            collection_name = COLLECTION_NAME,
            vectors_config = models.VectorParams(size = 768, distance = models.Distance.COSINE)
        )

def upsert_vectors(vectors):
    ensure_collection()
    points = []
    for v in vectors:
        points.append(
            models.PointStruct(
                id = str(uuid.uuid4()),
                vector = v["embedding"],
                payload = {
                    "text": v["text"],
                    **v["metadata"]
                }
            )
        )
    client.upsert(collection_name=COLLECTION_NAME, points=points)

def search_similar(query_embedding, k=5):
    results = client.search(
        collection_name = COLLECTION_NAME,
        query_vector = query_embedding,
        limit = k
    )
    return results