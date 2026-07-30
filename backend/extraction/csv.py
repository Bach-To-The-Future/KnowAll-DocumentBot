import os
import pandas as pd
import chardet
import csv
from typing import List
from llama_index.core import Document
import logging
from extraction.base import BaseExtractor
from extraction.helper import generate_metadata, dynamic_rows_per_chunk

logging.basicConfig(level=logging.INFO)

READ_BLOCK_ROWS = 3000   # streaming block size for large files


class ExtractCSV(BaseExtractor):
    @staticmethod
    def detect_encoding(file_path: str) -> str:
        """Detect file encoding using chardet."""
        with open(file_path, "rb") as f:
            result = chardet.detect(f.read(10000))
        encoding = result["encoding"] or "utf-8"
        if encoding.lower() == "ascii":
            encoding = "utf-8"
        return encoding

    @staticmethod
    def detect_delimiter(file_path: str, encoding: str = "utf-8") -> str:
        """Detect CSV delimiter using csv.Sniffer."""
        with open(file_path, "r", encoding=encoding) as csv_file:
            sample = csv_file.read(2048)
            try:
                sniffer = csv.Sniffer()
                return sniffer.sniff(sample).delimiter
            except csv.Error:
                return ","

    def extract_and_chunk(self, file_path: str) -> List[Document]:
        """Row-group chunking: never sentence-split serialized tables.

        Each chunk is a standalone mini-CSV — to_csv() re-emits the header
        row, so every chunk is interpretable on its own.
        """
        if not self.validate_file(file_path):
            return []

        self.logger.info(f"Extracting and chunking: {file_path}")
        source = os.path.basename(file_path)
        ext = os.path.splitext(file_path)[-1][1:].lower()

        encoding = self.detect_encoding(file_path)
        delimiter = self.detect_delimiter(file_path, encoding)
        all_nodes: List[Document] = []
        row_offset = 0

        for block in pd.read_csv(file_path, encoding=encoding, delimiter=delimiter,
                                 chunksize=READ_BLOCK_ROWS):
            if block.empty:
                continue
            # Rows per chunk adapt to row width (token-aware, header excluded).
            block_body_chars = len(block.to_csv(index=False, header=False))
            rows_per_chunk = dynamic_rows_per_chunk(block_body_chars, len(block))
            for start in range(0, len(block), rows_per_chunk):
                group = block.iloc[start:start + rows_per_chunk]
                first_row = row_offset + start
                last_row = first_row + len(group) - 1
                doc = self.create_document(
                    group.to_csv(index=False),  # header row included per chunk
                    metadata=generate_metadata(
                        source=source,
                        index=0,
                        max_index=1,
                        file_format=ext,
                        content_type="table",
                        table_id=f"rows_{first_row}_{last_row}",
                        headers=block.columns.tolist(),
                        row_range=f"{first_row}-{last_row}",
                    )
                )
                if doc:
                    all_nodes.append(doc)
            row_offset += len(block)

        for i, node in enumerate(all_nodes):
            node.metadata.update({"chunk_index": i, "total_chunks": len(all_nodes)})

        self.logger.info(f"Extracted {len(all_nodes)} chunks from {file_path}")
        return all_nodes
