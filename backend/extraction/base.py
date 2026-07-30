"""Shared extractor machinery. Concrete extractors implement the
core.interfaces.DocumentExtractor contract through this base class."""
import logging
import os
from typing import List

from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter

from core.config import get_settings
from core.interfaces import DocumentExtractor

logging.basicConfig(level=logging.INFO)


class BaseExtractor(DocumentExtractor):
    """Base class for document extractors."""

    def __init__(self, chunk_size: int | None = None, chunk_overlap: int | None = None) -> None:
        settings = get_settings()
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
        self.splitter = SentenceSplitter(chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap)
        self.logger = logging.getLogger(self.__class__.__name__)

    def validate_file(self, file_path: str) -> bool:
        """Validate file existence and size."""
        if not os.path.exists(file_path):
            self.logger.error(f"File not found: {file_path}")
            return False
        if os.path.getsize(file_path) == 0:
            self.logger.warning(f"Skipping empty file: {file_path}")
            return False
        return True

    def create_document(self, text: str, metadata: dict) -> Document | None:
        """Create a Document with text and metadata."""
        if not text.strip():
            return None
        doc = Document(text=text)
        doc.metadata = metadata
        return doc

    def chunk_document(self, document: Document | None) -> List[Document]:
        """Chunk a Document using SentenceSplitter."""
        if not document:
            return []
        return self.splitter.get_nodes_from_documents([document])

    def chunk_text(self, text: str) -> List[str]:
        """Split raw text into chunk strings (used when the extractor builds
        its own Documents, e.g. to prepend a heading path to every chunk)."""
        if not text or not text.strip():
            return []
        return self.splitter.split_text(text)
