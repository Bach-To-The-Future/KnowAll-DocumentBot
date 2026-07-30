import os
import pandas as pd
from typing import List
import logging
from llama_index.core import Document
from extraction.base import BaseExtractor
from extraction.helper import generate_metadata, dynamic_rows_per_chunk

logging.basicConfig(level=logging.INFO)


class ExtractXLSX(BaseExtractor):
    def extract_and_chunk(self, file_path: str) -> List[Document]:
        """Row-group chunking per sheet: never sentence-split serialized
        tables; every chunk carries the sheet name and the header row."""
        if not self.validate_file(file_path):
            return []

        self.logger.info(f"Extracting and chunking: {file_path}")
        source = os.path.basename(file_path)
        ext = os.path.splitext(file_path)[-1][1:].lower()

        xl = pd.ExcelFile(file_path, engine="openpyxl")
        all_nodes: List[Document] = []

        for sheet_name in xl.sheet_names:
            df = xl.parse(sheet_name)
            if df.empty:
                continue

            # Rows per chunk adapt to row width (token-aware, header excluded).
            sheet_body_chars = len(df.to_csv(index=False, header=False))
            rows_per_chunk = dynamic_rows_per_chunk(sheet_body_chars, len(df))
            for start in range(0, len(df), rows_per_chunk):
                group = df.iloc[start:start + rows_per_chunk]
                last_row = start + len(group) - 1
                # Sheet context + per-chunk header keep each chunk standalone.
                text = f"Sheet: {sheet_name}\n{group.to_csv(index=False)}"
                doc = self.create_document(
                    text,
                    metadata=generate_metadata(
                        source=source,
                        index=0,
                        max_index=1,
                        file_format=ext,
                        content_type="table",
                        sheet_name=sheet_name,
                        headers=df.columns.tolist(),
                        row_range=f"{start}-{last_row}",
                    )
                )
                if doc:
                    all_nodes.append(doc)

        for i, node in enumerate(all_nodes):
            node.metadata.update({"chunk_index": i, "total_chunks": len(all_nodes)})

        self.logger.info(f"Extracted {len(all_nodes)} chunks from {file_path}")
        return all_nodes
