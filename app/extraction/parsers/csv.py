import os
import pandas as pd
import chardet
import csv
from typing import List
from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter
from llama_index.readers.file import CSVReader
import logging
import io

from app.config import Config
from .helper import generate_metadata_csv_excel

config = Config()

logging.basicConfig(level=logging.INFO)

class ExtractCSV:
    
    @staticmethod
    def detect_encoding(file_path: str) -> str:
        with open(file_path, "rb") as f:
            result = chardet.detect(f.read(10000))
        encoding = result["encoding"] or "utf-8"
        if encoding.lower() == "ascii":
            encoding = "utf-8"
        return encoding
    
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
        content = pd.read_csv(file_path, encoding=encoding, delimiter=delimiter, skip_blank_lines=False, header=None)
        tables = []
        current_table = []

        for idx, row in content.iterrows():
            if row.isnull().all():
                if current_table:
                    # Current table -> Dataframe
                    df_raw = pd.DataFrame(current_table).dropna(how='all', axis=1)
                    df_raw.columns = df_raw.iloc[0]  # First row = header
                    df = df_raw[1:].reset_index(drop=True)
                    tables.append(df)
                    current_table = []
            else:
                current_table.append(row.tolist())

        # Last table
        if current_table:
            df_raw = pd.DataFrame(current_table).dropna(how='all', axis=1)
            df_raw.columns = df_raw.iloc[0]
            df = df_raw[1:].reset_index(drop=True)
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
        csv_reader = CSVReader()
        for table_id, csv_text in enumerate(tables):
            try:
                # Read table as a Document using CSVReader
                documents = csv_reader.load_data(file=csv_text)
                document = documents[0] if documents else None
                if document is None or not document.text.strip():
                    continue

                splitter = SentenceSplitter(
                    chunk_size=config.CHUNK_SIZE,
                    chunk_overlap=config.CHUNK_OVERLAP
                )
                nodes = splitter.get_nodes_from_documents([document])

                for i, node in enumerate(nodes):
                    # Attempt to extract row indices
                    lines_in_chunk = node.text.splitlines()
                    try:
                        first_idx = int(lines_in_chunk[0].split(":", 1)[0])
                        last_idx = int(lines_in_chunk[-1].split(":", 1)[0])
                        row_range = f"{first_idx} - {last_idx}"
                    except Exception as e:
                        logging.warning(f"Could not determine row range: {e}")
                        row_range = "unknown"

                    df = pd.read_csv(pd.compat.StringIO(csv_text))  # recreate DataFrame from text
                    metadata = generate_metadata_csv_excel(
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
            except Exception as e:
                logging.error(f"Failed processing table {table_id}: {e}")

        return all_nodes
    
if __name__ == "__main__":
    nodes = ExtractCSV.extract_and_chunk("./documents/advertising.csv")
    for node in nodes:
        print(node.metadata)
        print(node.text[:150])
        print("---")