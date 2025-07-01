import os
import fitz
import re
import pandas as pd
import json
from typing import List
import pdfplumber
import logging
from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter

from app.config import Config
from .helper import generate_metadata_pdf

config = Config()
logging.basicConfig(level=logging.INFO)

class ExtractPDF:

    @staticmethod
    def extract_text(file_path: str) -> List[tuple[int, str]]:
        """Extract plain text from each PDF page using PyMuPDF."""
        page_texts = []
        try:
            with fitz.open(file_path) as doc:
                for page_num, page in enumerate(doc, start=1):
                    text = page.get_text()
                    if text.strip():
                        page_texts.append((page_num, text.strip()))
        except Exception as e:
            logging.error(f"[ExtractPDF] Text extraction failed: {e}")
        return page_texts

    @staticmethod
    def extract_tables(file_path: str) -> List[tuple[pd.DataFrame, int]]:
        """Extract tables from PDF using pdfplumber, returns (DataFrame, page_number)."""
        tables = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    page_tables = page.extract_tables()
                    for raw_table in page_tables:
                        df = pd.DataFrame(raw_table)
                        if not df.dropna(how="all").empty:
                            df.columns = df.iloc[0]
                            df = df[1:].reset_index(drop=True)
                            tables.append((df, page_num))
        except Exception as e:
            logging.warning(f"[ExtractPDF] Table extraction failed: {e}")
        return tables

    @staticmethod
    def detect_figures(file_path: str) -> List[str]:
        """Detect presence of figures/images in PDF."""
        image_descriptions = []
        try:
            with fitz.open(file_path) as doc:
                for page_num, page in enumerate(doc):
                    images = page.get_images(full=True)
                    if images:
                        image_descriptions.append(f"Page {page_num + 1}: {len(images)} image(s) detected")
        except Exception as e:
            logging.warning(f"[ExtractPDF] Image detection failed: {e}")
        return image_descriptions

    @staticmethod
    def extract_and_chunk(file_path: str) -> List[Document]:
        print(f"📂 Extracting and chunking: {file_path}")
        if not os.path.exists(file_path):
            logging.error(f"[ExtractPDF] File not found: {file_path}")
            return []

        if os.path.getsize(file_path) == 0:
            logging.warning(f"[ExtractPDF] Skipping empty file: {file_path}")
            return []

        source = os.path.basename(file_path)
        ext = "pdf"  # Force format tag since this extractor is PDF-specific

        page_texts = ExtractPDF.extract_text(file_path)
        tables = ExtractPDF.extract_tables(file_path)
        figures = ExtractPDF.detect_figures(file_path)

        all_nodes = []
        splitter = SentenceSplitter(
            chunk_size=config.CHUNK_SIZE,
            chunk_overlap=config.CHUNK_OVERLAP
        )

        # Chunk plain text
        for page_num, page_text in page_texts:
            document = Document(text=page_text)
            nodes = splitter.get_nodes_from_documents([document])
            for i, node in enumerate(nodes):
                node.metadata = generate_metadata_pdf(
                    source=source,
                    index=i,
                    max_index=len(nodes),
                    file_format=ext,
                    page_num=page_num,
                    headers=None,
                    row_range="text"
                )
                all_nodes.append(node)

        # Chunk tables
        for table_id, (df, page_num) in enumerate(tables):
            if df.empty:
                continue

            df = df.dropna(how='all', axis=1)
            df.columns = df.iloc[0].fillna("").astype(str)
            df = df[1:].reset_index(drop=True)

            lines = []
            for i, row in df.iterrows():
                row_dict = {col: val for col, val in zip(df.columns, row.values)}
                lines.append(f"{i}: {json.dumps(row_dict, ensure_ascii=False)}")

            document = Document(text="\n".join(lines))
            nodes = splitter.get_nodes_from_documents([document])
            for i, node in enumerate(nodes):
                row_range = f"{i * config.CHUNK_SIZE} - {(i + 1) * config.CHUNK_SIZE}"
                node.metadata = generate_metadata_pdf(
                    source=source,
                    index=i,
                    max_index=len(nodes),
                    file_format=ext,
                    page_num=page_num,
                    headers=df.columns.tolist(),
                    row_range=row_range,
                    table_id=f"table_{table_id}"
                )
                all_nodes.append(node)

        # Chunk figure/image descriptions
        for i, desc in enumerate(figures):
            document = Document(text=desc)
            match = re.search(r"Page\s+(\d+)", desc)
            page_num = int(match.group(1)) if match else -1

            document.metadata = generate_metadata_pdf(
                source=source,
                index=i,
                max_index=len(figures),
                file_format=ext,
                page_num=page_num,
                headers=None,
                row_range="image_detected",
                table_id=f"figure_{i}"
            )
            all_nodes.append(document)

        return all_nodes

# --- Optional test run ---
if __name__ == "__main__":
    nodes = ExtractPDF.extract_and_chunk("./app/documents/sample.pdf")
    for node in nodes:
        print(node.metadata)
        print(node.text[:300])
        print("---")
