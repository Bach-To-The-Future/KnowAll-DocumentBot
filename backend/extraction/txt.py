import os
import chardet
from typing import List
from llama_index.core import Document
import logging
import re
from extraction.base import BaseExtractor
from extraction.helper import generate_metadata

logging.basicConfig(level=logging.INFO)

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


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
        """Heading-path chunking for TXT/MD: split on markdown heading
        boundaries and prepend the heading hierarchy to every chunk."""
        if not self.validate_file(file_path):
            return []

        self.logger.info(f"Extracting and chunking: {file_path}")
        source = os.path.basename(file_path)
        stem = os.path.splitext(source)[0]
        ext = os.path.splitext(file_path)[-1][1:].lower()

        encoding = self.detect_encoding(file_path)
        with open(file_path, "r", encoding=encoding) as f:
            lines = f.read().splitlines()

        all_nodes: List[Document] = []
        heading_stack: List[tuple] = []  # [(level, heading_text)]
        buffer: List[str] = []

        def current_path() -> str:
            return " > ".join([stem] + [text for _, text in heading_stack])

        def flush_buffer():
            text = "\n".join(buffer).strip()
            buffer.clear()
            if not text:
                return
            path = current_path()
            for piece in self.chunk_text(text):
                doc = self.create_document(
                    f"{path}\n\n{piece}",  # heading path travels with every chunk
                    metadata=generate_metadata(
                        source=source,
                        index=0,
                        max_index=1,
                        file_format=ext,
                        content_type="text",
                        section_title=path,
                    )
                )
                if doc:
                    all_nodes.append(doc)

        for line in lines:
            match = HEADING_RE.match(line)
            if match:
                # Heading boundary: the section body stays under the heading
                # it belongs to (the old regex-split inverted this).
                flush_buffer()
                level = len(match.group(1))
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, match.group(2)))
            else:
                buffer.append(line)
        flush_buffer()

        for i, node in enumerate(all_nodes):
            node.metadata.update({"chunk_index": i, "total_chunks": len(all_nodes)})

        self.logger.info(f"Extracted {len(all_nodes)} chunks from {file_path}")
        return all_nodes
