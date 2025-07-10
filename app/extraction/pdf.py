import os
import fitz
import pandas as pd
import pdfplumber
from typing import List
import logging
from llama_index.core import Document
from extraction.base import BaseExtractor
from extraction.helper import generate_metadata

logging.basicConfig(level=logging.INFO)

class ExtractPDF(BaseExtractor):
    def extract_and_chunk(self, file_path: str) -> List[Document]:
        """Extract and chunk PDF content with metadata."""
        if not self.validate_file(file_path):
            return []

        self.logger.info(f"Extracting and chunking: {file_path}")
        source = os.path.basename(file_path)
        ext = "pdf"

        all_nodes = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    # Extract text
                    text = page.extract_text()
                    if text and text.strip():
                        doc = self.create_document(text, metadata=generate_metadata(
                            source=source,
                            index=page_num,
                            max_index=len(pdf.pages),
                            file_format=ext,
                            page_number=page_num,
                            content_type="text"
                        ))
                        if doc:
                            nodes = self.chunk_document(doc)
                            for i, node in enumerate(nodes):
                                node.metadata.update({"chunk_index": i, "total_chunks": len(nodes)})
                            all_nodes.extend(nodes)

                    # Extract tables
                    tables = page.extract_tables()
                    for table_id, table in enumerate(tables):
                        if table:
                            df = pd.DataFrame(table[1:], columns=table[0])
                            if not df.empty:
                                csv_str = df.to_csv(index=False)
                                doc = self.create_document(csv_str, metadata=generate_metadata(
                                    source=source,
                                    index=table_id,
                                    max_index=len(tables),
                                    file_format=ext,
                                    page_number=page_num,
                                    content_type="table",
                                    table_id=f"table_{table_id}",
                                    headers=df.columns.tolist()
                                ))
                                if doc:
                                    nodes = self.chunk_document(doc)
                                    for i, node in enumerate(nodes):
                                        node.metadata.update({"chunk_index": i, "total_chunks": len(nodes)})
                                    all_nodes.extend(nodes)

            # Extract images with PyMuPDF
            with fitz.open(file_path) as doc:
                for page_num, page in enumerate(doc, start=1):
                    images = page.get_images(full=True)
                    for img_id, img in enumerate(images):
                        doc = self.create_document(f"Image detected on page {page_num}", metadata=generate_metadata(
                            source=source,
                            index=img_id,
                            max_index=len(images),
                            file_format=ext,
                            page_number=page_num,
                            content_type="image",
                            figure_id=f"figure_{img_id}"
                        ))
                        if doc:
                            all_nodes.append(doc)

            self.logger.info(f"Extracted {len(all_nodes)} chunks from {file_path}")
            return all_nodes
        except Exception as e:
            self.logger.error(f"Error processing PDF file: {e}")
            return []