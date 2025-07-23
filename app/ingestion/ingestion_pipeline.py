import os
from extraction.options import ExtractStrategy
from embedding.embed import embed_nodes
from embedding.vectorstore import upsert_vectors
import logging

logging.basicConfig(level=logging.INFO)

def process_documents(file_path: str):
    """Process a document through extraction, embedding, and vector storage."""
    logger = logging.getLogger(__name__)
    extractor = ExtractStrategy.get_extractor(file_path)
    if not extractor:
        logger.error(f"No extractor found for file: {file_path}")
        return []

    logger.info(f"Using extractor: {extractor.__class__.__name__}")
    try:
        nodes = extractor.extract_and_chunk(file_path)
        logger.info(f"Extracted {len(nodes)} chunks")
        if not nodes:
            return []

        for i, node in enumerate(nodes[:3]):
            logger.debug(f"Chunk {i+1}: {node.text[:100]}...")

        vectors = embed_nodes(nodes)
        logger.info(f"Embedded {len(vectors)} vectors")

        upsert_vectors(vectors)
        logger.info(f"Upserted {len(vectors)} vectors to Qdrant")

        return vectors
    except Exception as e:
        logger.error(f"Error processing document {file_path}: {e}")
        return []