from app.extraction.options import ExtractStrategy
from app.embedding import embed_nodes
from app.vectorstore import upsert_vectors

def process_documents(file_path:str):
    extractor_cls = ExtractStrategy.get_extractor(file_path)
    if not extractor_cls:
        raise ValueError(f"No extractor found for file type: {file_path}")
    
    nodes = extractor_cls.extract_and_chunk(file_path)
    if not nodes:
        return []
    
    vectors = embed_nodes(nodes)
    upsert_vectors(vectors)
    return vectors