import os
import fitz
import re
import pandas as pd
import json
from typing import List
import pdfplumber
import docx2pdf
import pptxtopdf
import logging
from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter

from app.config import Config
from .helper import generate_metadata_pdf

config = Config()
logging.basicConfig(level=logging.INFO)

class ExtractPDF:

    @staticmethod
    def extract_text(file_path: str) -> str:
        '''
            Extract text from pdf file using PyMuPDF
        '''
        page_texts = []
        try:
            with fitz.open(file_path) as doc:
                for page_num, page in enumerate(doc, start=1):
                    text = page.get_text()
                    if text.strip():
                        page_texts.append((page_num, text.strip()))
        except Exception as e:
            logging.error(f"Text extraction failed: {e}")
        return page_texts
    
    @staticmethod
    def extract_tables(file_path:str) -> List[pd.DataFrame]:
        '''
            Extract tables from pdf file using pdfPlumber
        '''
        tables = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    page_tables = page.extract_tables()
                    for raw_table in page_tables:
                        df = pd.DataFrame(raw_table)
                        if not df.dropna(how="all").empty:
                            df.columns = df.iloc[0]  # Use first row as headers
                            df = df[1:].reset_index(drop=True)
                            tables.append((df, page_num)) # Include page number
        except Exception as e:
            logging.warning(f"Table extraction failed: {e}")
        return tables
    
    @staticmethod
    def detect_figures(file_path:str) -> List[str]:
        '''
            Detect figures/images and log their presence
        '''
        image_descriptions = []
        try:
            with fitz.open(file_path) as doc:
                for page_num, page in enumerate(doc):
                    images = page.get_images(full=True)
                    if images:
                        image_descriptions.append(f"Page {page_num + 1}: {len(images)} image(s) detected")
        except Exception as e:
            logging.warning(f"Image detection failed: {e}")
        return image_descriptions
    
    @staticmethod
    def convert_to_pdf(file_path:str, overwrite:bool = False) -> str:
        '''
            Convert files to pdf if the file is currently docx, pptx
            Return the file path to the converted pdf file
        '''
        pdf_path = os.path.splitext(file_path)[0] + ".pdf"
        dir_name = os.path.dirname(file_path)
        ext = os.path.splitext(file_path)[-1].lower()

        # Remove existing pdf
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

        # Convert docx/pptx to pdf
        try:
            if ext == ".docx":
                docx2pdf.convert(file_path, pdf_path)
            elif ext == ".pptx":
                pptxtopdf.convert(file_path, dir_name)
            else:
                raise ValueError("Only .docx and .pptx files are supported.")
        except Exception as e:
            raise RuntimeError(f"Conversion failed: {e}")

        if not os.path.exists(pdf_path):
            raise FileNotFoundError("Output pdf not found")
        return pdf_path

    @staticmethod
    def extract_and_chunk(file_path: str) -> List:
        ext = os.path.splitext(file_path)[-1][1:].lower()

        # Convert to pdf if file format is not pdf already
        if ext in config.PDF_EXTENSIONS_CONVERSION:
            file_path = ExtractPDF.convert_to_pdf(file_path)
            ext = "pdf"
        source = os.path.basename(file_path)

        if os.path.getsize(file_path) == 0:
            logging.warning(f"Skipping empty PDF file: {file_path}")
            return []

        # Extract all content types
        page_texts = ExtractPDF.extract_text(file_path)
        tables = ExtractPDF.extract_tables(file_path)
        figures = ExtractPDF.detect_figures(file_path)

        all_nodes = []

        # Chunk plain text
        for page_num, page_text in page_texts:
            document = Document(text=page_text)
            splitter = SentenceSplitter(
                chunk_size=config.CHUNK_SIZE,
                chunk_overlap=config.CHUNK_OVERLAP
            )
            nodes = splitter.get_nodes_from_documents([document])
            for i, node in enumerate(nodes):
                metadata = generate_metadata_pdf(
                    source=source,
                    index=i,
                    max_index=len(nodes),
                    file_format=ext,
                    page_num=page_num,
                    headers=None,
                    row_range="text"
                )
                node.metadata = metadata
                all_nodes.append(node)

        # Chunk extracted tables
        for table_id, (df, page_num) in enumerate(tables):
            if df.empty:
                continue
            # Drop completely empty columns
            df = df.dropna(how='all', axis=1)
            # Use first row as header
            df.columns = df.iloc[0].fillna("").astype(str)
            # Deduplicate column names manually
            def deduplicate_columns(columns):
                seen = {}
                new_columns = []
                for col in columns:
                    if col not in seen:
                        seen[col] = 0
                        new_columns.append(col)
                    else:
                        seen[col] += 1
                        new_columns.append(f"{col}_{seen[col]}")
                return new_columns

            # Header detection
            if df.iloc[0].dropna().nunique() < df.shape[1] // 2:
                df.columns = [f"col_{i}" for i in range(df.shape[1])]
            else:
                df.columns = df.iloc[0].fillna("").astype(str)
                df = df[1:]
            df = df.reset_index(drop=True)

            # Safely convert each row to JSON
            lines = []
            for i, row in df.iterrows():
                row_dict = {df.columns[j]: val for j, val in enumerate(row.values)}
                lines.append(f"{i}: {json.dumps(row_dict, ensure_ascii=False)}")

            document = Document(text="\n".join(lines))
            splitter = SentenceSplitter(
                chunk_size=config.CHUNK_SIZE,
                chunk_overlap=config.CHUNK_OVERLAP
            )
            nodes = splitter.get_nodes_from_documents([document])
            for i, node in enumerate(nodes):
                row_range = f"{i * config.CHUNK_SIZE} - {(i + 1) * config.CHUNK_SIZE}"
                metadata = generate_metadata_pdf(
                    source=source,
                    index=i,
                    max_index=len(nodes),
                    file_format=ext,
                    sheet_name=None,
                    table_id=f"table_{table_id}",
                    headers=df.columns.tolist(),
                    row_range=row_range,
                    page_num=page_num  # Include page number
                )
                node.metadata = metadata
                all_nodes.append(node)

        # Add figure placeholders
        for i, desc in enumerate(figures):
            document = Document(text=desc)

            # Extract page_num from string - "Page 5: 2 image(s) detected"
            match = re.search(r"Page\s+(\d+)", desc)
            page_num = int(match.group(1)) if match else -1  # Default to -1 if not found

            metadata = generate_metadata_pdf(
                source=source,
                index=i,
                max_index=len(figures),
                file_format=ext,
                page_num=page_num, 
                table_id=f"figure_{i}",
                headers=None,
                row_range="image_detected"
            )
            document.metadata = metadata
            all_nodes.append(document)

        return all_nodes

if __name__ == "__main__":
    nodes = ExtractPDF.extract_and_chunk("./app/documents/ABC DELF junior A2.pdf")
    for node in nodes:
        print(node.metadata)
        print(node.text[:300])
        print("---")