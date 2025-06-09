import os
import pandas as pd
import chardet
import csv
from typing import List
from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter
import logging

from app.config import Config
from .helper import generate_metadata

config = Config()

logging.basicConfig(level=logging.INFO)

class ExtractCSV:
    
    @staticmethod
    def detect_encoding(file_path:str) -> str:
        with open(file_path, "rb") as f:
            result = chardet.detect(f.read(10000))
        return result["encoding"] or "utf-8"
    
    @staticmethod
    def detect_delimiter(file_path:str, encoding:str = "utf-8") -> str:
        with open(file_path, "r", encoding=encoding) as csv_file:
            sample = csv_file.read(2048)
            sniffer = csv.Sniffer()
            return sniffer.sniff(sample).delimiter
        
    @staticmethod
    def split_csv_into_tables(file_path: str, encoding: str, delimiter: str) -> List[pd.DataFrame]:
        """
        Extract multiple tables if they exist in the CSV file.
        Returns list of those tables as DataFrames.
        """
        tables = []
        current_rows = []

        with open(file_path, "r", encoding=encoding) as f:
            reader = csv.reader(f, delimiter=delimiter)
            for line in reader:
                if not any(cell.strip() for cell in line):  # blank line
                    if current_rows:
                        df = pd.DataFrame(current_rows[1:], columns=current_rows[0]) if len(current_rows) > 1 else None
                        if df is not None:
                            tables.append(df)
                        current_rows = []
                else:
                    current_rows.append(line)
            if current_rows:  # final table
                df = pd.DataFrame(current_rows[1:], columns=current_rows[0]) if len(current_rows) > 1 else None
                if df is not None:
                    tables.append(df)
        return tables

    @staticmethod
    def extract_and_chunk(file_path: str) -> List:
        """
        Main method to be called by ExtractStrategy.
        Reads and chunks CSV content with metadata.
        """
        ext = os.path.splitext(file_path)[-1][1:].lower()
        source = os.path.basename(file_path)

        if os.path.getsize(file_path) == 0:
            logging.warning(f"Skipping empty CSV file: {file_path}")
            return []

        try:
            encoding = ExtractCSV.detect_encoding(file_path)
            delimiter = ExtractCSV.detect_delimiter(file_path, encoding)
            tables = ExtractCSV.split_csv_into_tables(file_path, encoding, delimiter)
        except Exception as e:
            logging.error(f"Error reading CSV file: {e}")
            return []

        all_nodes = []
        for table_id, df in enumerate(tables):
            if df.empty:
                continue

            lines = [f"{i}: {row.to_json()}" for i, row in df.iterrows()]
            document = Document(text="\n".join(lines))

            splitter = SentenceSplitter(
                chunk_size=config.CHUNK_SIZE,
                chunk_overlap=config.CHUNK_OVERLAP
            )
            nodes = splitter.get_nodes_from_documents([document])

            for i, node in enumerate(nodes):
                # Extract row range
                lines_in_chunk = node.text.splitlines()
                try:
                    first_idx = int(lines_in_chunk[0].split(":", 1)[0])
                    last_idx = int(lines_in_chunk[-1].split(":", 1)[0])
                    row_range = f"{first_idx} - {last_idx}"
                except Exception as e:
                    logging.warning(f"Could not determine row range: {e}")
                    row_range = "unknown"
                
                metadata = generate_metadata(
                    source=source,
                    index=i,
                    max_index=len(nodes),
                    file_format=ext,
                    sheet_name=None,
                    table_id=f"table_{table_id}",
                    headers=df.columns.tolist(),
                    row_range=row_range
                )
                node.metadata = metadata
                all_nodes.extend(nodes)

        return all_nodes
    
if __name__ == "__main__":
    nodes = ExtractCSV.extract_and_chunk("./documents/test.csv")
    for node in nodes:
        print(node.metadata)
        print(node.text[:150])
        print("---")