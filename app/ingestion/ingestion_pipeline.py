from extraction.options import ExtractStrategy
from embedding.embed import embed_nodes
from embedding.vectorstore import upsert_vectors

def process_documents(file_path: str):
    extractor_cls = ExtractStrategy.get_extractor(file_path)
    if not extractor_cls:
        raise ValueError(f"No extractor found for file type: {file_path}")

    print(f"🔍 Using extractor: {extractor_cls.__name__}")
    nodes = extractor_cls.extract_and_chunk(file_path)
    print(f"📄 Extracted {len(nodes)} chunks")
    if not nodes:
        return []

    for i, n in enumerate(nodes[:3]):
        print(f"📎 Chunk {i+1}: {n.text[:100]}...")

    vectors = embed_nodes(nodes)
    print(f"🧠 Embedded {len(vectors)} vectors")

    upsert_vectors(vectors)
    print(f"✅ Upserted {len(vectors)} vectors to Qdrant")

    return vectors
