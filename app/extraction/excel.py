import os
import pandas as pd
from typing import List
import logging
from llama_index.core import Document
from extraction.base import BaseExtractor
from extraction.helper import generate_metadata

logging.basicConfig(level=logging.INFO)

class ExtractXLSX(BaseExtractor):
    def extract_and_chunk(self, file_path: str) -> List[Document]:
        """Extract and chunk Excel content with metadata."""
        if not self.validate_file(file_path):
            return []

        self.logger.info(f"Extracting and chunking: {file_path}")
        source = os.path.basename(file_path)
        ext = os.path.splitext(file_path)[-1][1:].lower()

        try:
            xl = pd.ExcelFile(file_path)
            all_nodes = []

            for sheet_name in xl.sheet_names:
                # Stream sheets to handle large files
                df = pd.read_excel(file_path, sheet_name=sheet_name, engine="openpyxl")
                if df.empty:
                    continue

                # Convert to CSV string
                csv_str = df.to_csv(index=False)
                doc = self.create_document(csv_str, metadata=generate_metadata(
                    source=source,
                    index=0,
                    max_index=1,
                    file_format=ext,
                    sheet_name=sheet_name,
                    headers=df.columns.tolist(),
                    row_range=f"0-{len(df)-1}"
                ))
                if doc:
                    nodes = self.chunk_document(doc)
                    for i, node in enumerate(nodes):
                        node.metadata.update({"chunk_index": i, "total_chunks": len(nodes)})
                    all_nodes.extend(nodes)

            self.logger.info(f"Extracted {len(all_nodes)} chunks from {file_path}")
            return all_nodes
        except Exception as e:
            self.logger.error(f"Error processing Excel file: {e}")
            return []