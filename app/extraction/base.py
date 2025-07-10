import os
from abc import ABC, abstractmethod
from typing import List
import logging
from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter
from config import Config

config = Config()
CHUNK_SIZE = config.CHUNK_SIZE
CHUNK_OVERLAP = config.CHUNK_OVERLAP

logging.basicConfig(level=logging.INFO)

class BaseExtractor(ABC):
    """Base class for document extractors."""
    
    def __init__(self, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def extract_and_chunk(self, file_path: str) -> List[Document]:
        """Extract content and chunk it into Document objects with metadata."""
        pass

    def validate_file(self, file_path: str) -> bool:
        """Validate file existence and size."""
        if not os.path.exists(file_path):
            self.logger.error(f"File not found: {file_path}")
            return False
        if os.path.getsize(file_path) == 0:
            self.logger.warning(f"Skipping empty file: {file_path}")
            return False
        return True

    def create_document(self, text: str, metadata: dict) -> Document:
        """Create a Document with text and metadata."""
        if not text.strip():
            return None
        doc = Document(text=text)
        doc.metadata = metadata
        return doc

    def chunk_document(self, document: Document) -> List[Document]:
        """Chunk a Document using SentenceSplitter."""
        if not document:
            return []
        nodes = self.splitter.get_nodes_from_documents([document])
        return nodes
