import os
import pandas as pd
from typing import List, Dict
import logging
from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter

from app.config import Config
from .helper import generate_metadata

config = Config()
logging.basicConfig(level=logging.INFO)

class ExtractXLSX:

    @staticmethod
    def extract_and_chunk(file_path:str) -> List:
        ext = os.path.splitext(file_path)[-1][1:].lower()
        source = os.path.basename(file_path)

        if os.path.getsize(file_path) == 0:
            logging.warning(f"Skipping empty Excel file: {file_path}")
            return []
        
        try:
            xl = pd.ExcelFile(file_path)
            all_nodes = []

            for sheet_name in xl.sheet_names:
                try:
                    df = xl.parse(sheet_name)
                except Exception as e:
                    logging.warning(f"Failed to parse sheet '{sheet_name}' in {source}: {e}")
                    continue
                if df.empty:
                    continue
                
                lines = [f"{i}: {row.to_json()}" for i, row in df.iterrows()]
                document = Document(text="\n".join(lines))
                
                splitter = SentenceSplitter(
                    chunk_size = config.CHUNK_SIZE,
                    chunk_overlap = config.CHUNK_OVERLAP
                )
                nodes = splitter.get_nodes_from_document([document])

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
                        sheet_name=sheet_name,
                        headers=df.columns.tolist(),
                        row_range=row_range
                    )
                    node.metadata = metadata
                    all_nodes.append(node)

            return all_nodes
        except Exception as e:
            logging.error(f"Failed to process excel file '{source}': {e}")
            return []
        
if __name__ == "__main__":
    nodes = ExtractXLSX.extract_and_chunk("./documents/test.xlsx")
    for node in nodes:
        print(node.metadata)
        print(node.text[:150])
        print("---")