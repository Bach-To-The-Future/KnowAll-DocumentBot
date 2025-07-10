import os
import pandas as pd
import chardet
import csv
from typing import List
from llama_index.core import Document
import logging
import io
from extraction.base import BaseExtractor
from extraction.helper import generate_metadata

logging.basicConfig(level=logging.INFO)

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
        """Extract and chunk CSV content with metadata."""
        if not self.validate_file(file_path):
            return []

        self.logger.info(f"Extracting and chunking: {file_path}")
        source = os.path.basename(file_path)
        ext = os.path.splitext(file_path)[-1][1:].lower()

        try:
            encoding = self.detect_encoding(file_path)
            delimiter = self.detect_delimiter(file_path, encoding)
            all_nodes = []

            # Stream CSV to handle large files
            chunks = pd.read_csv(file_path, encoding=encoding, delimiter=delimiter, chunksize=1000)
            for table_id, chunk in enumerate(chunks):
                if chunk.empty:
                    continue

                # Convert chunk to CSV string
                csv_str = chunk.to_csv(index=False)
                doc = self.create_document(csv_str, metadata=generate_metadata(
                    source=source,
                    index=table_id,
                    max_index=1,  # Updated per chunk
                    file_format=ext,
                    table_id=f"table_{table_id}",
                    headers=chunk.columns.tolist(),
                    row_range=f"{chunk.index[0]}-{chunk.index[-1]}"
                ))
                if doc:
                    nodes = self.chunk_document(doc)
                    for i, node in enumerate(nodes):
                        node.metadata.update({"chunk_index": i, "total_chunks": len(nodes)})
                    all_nodes.extend(nodes)

            self.logger.info(f"Extracted {len(all_nodes)} chunks from {file_path}")
            return all_nodes
        except Exception as e:
            self.logger.error(f"Error processing CSV file: {e}")
            return []