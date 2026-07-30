import logging

from llama_index.core import Document

from extraction.txt import ExtractTXT

logging.basicConfig(level=logging.INFO)

class ExtractHELM(ExtractTXT):
    """HELM extractor (assumed text-based, uses TXT extractor)."""
    def extract_and_chunk(self, file_path: str) -> list[Document]:
        """Extract and chunk HELM content with metadata."""
        self.logger.info(f"Using TXT extractor for HELM file: {file_path}")
        return super().extract_and_chunk(file_path)
