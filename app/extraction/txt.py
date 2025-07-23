import os
import chardet
from typing import List
from llama_index.core import Document
import logging
import re
from extraction.base import BaseExtractor
from extraction.helper import generate_metadata

logging.basicConfig(level=logging.INFO)

class ExtractTXT(BaseExtractor):
    @staticmethod
    def detect_encoding(file_path: str) -> str:
        """Detect file encoding using chardet."""
        with open(file_path, "rb") as f:
            result = chardet.detect(f.read(10000))
        encoding = result["encoding"] or "utf-8"
        if encoding.lower() == "ascii":
            encoding = "utf-8"
        return encoding

    def extract_and_chunk(self, file_path: str) -> List[Document]:
        """Extract and chunk TXT/MD content with metadata."""
        if not self.validate_file(file_path):
            return []

        self.logger.info(f"Extracting and chunking: {file_path}")
        source = os.path.basename(file_path)
        ext = os.path.splitext(file_path)[-1][1:].lower()

        try:
            encoding = self.detect_encoding(file_path)
            with open(file_path, "r", encoding=encoding) as f:
                text = f.read()

            all_nodes = []
            sections = re.split(r"^(#+.*$)", text, flags=re.MULTILINE)
            for section_id, section in enumerate(sections):
                section = section.strip()
                if not section:
                    continue
                section_title = section.split("\n")[0] if section.startswith("#") else None
                doc = self.create_document(section, metadata=generate_metadata(
                    source=source,
                    index=section_id,
                    max_index=len(sections),
                    file_format=ext,
                    page_number=1,
                    section_title=section_title
                ))
                if doc:
                    nodes = self.chunk_document(doc)
                    for i, node in enumerate(nodes):
                        node.metadata.update({"chunk_index": i, "total_chunks": len(nodes)})
                    all_nodes.extend(nodes)

            self.logger.info(f"Extracted {len(all_nodes)} chunks from {file_path}")
            return all_nodes
        except Exception as e:
            self.logger.error(f"Error processing TXT file: {e}")
            return []