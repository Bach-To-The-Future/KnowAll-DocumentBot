from typing import List
from llama_index.core import Document
import logging
import os
from extraction.base import BaseExtractor
from extraction.helper import generate_metadata

logging.basicConfig(level=logging.INFO)

class ExtractMSG(BaseExtractor):
    def extract_and_chunk(self, file_path: str) -> List[Document]:
        """Placeholder for MSG (Outlook email) extraction."""
        if not self.validate_file(file_path):
            return []

        self.logger.info(f"Extracting and chunking: {file_path}")
        source = os.path.basename(file_path)
        ext = os.path.splitext(file_path)[-1][1:].lower()

        self.logger.warning("MSG extraction not implemented. Returning empty list.")
        return []