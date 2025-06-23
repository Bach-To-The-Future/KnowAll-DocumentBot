import os
import chardet
from typing import List
from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter
import logging

from app.config import Config
from .helper import generate_metadata_txt

config = Config()
logging.basicConfig(level=logging.INFO)

class ExtractTXT:

    @staticmethod
    def detect_encoding(file_path: str) -> str:
        with open(file_path, "rb") as f:
            result = chardet.detect(f.read(10000))
        encoding = result["encoding"] or "utf-8"
        if encoding.lower() == "ascii":
            encoding = "utf-8"
        return encoding

    @staticmethod
    def extract_and_chunk(file_path: str) -> List:
        """
        Reads and chunks .txt/.md file content with metadata.
        """
        ext = os.path.splitext(file_path)[-1][1:].lower()
        source = os.path.basename(file_path)

        if os.path.getsize(file_path) == 0:
            logging.warning(f"Skipping empty file: {file_path}")
            return []

        try:
            encoding = ExtractTXT.detect_encoding(file_path)
            with open(file_path, "r", encoding=encoding) as f:
                text = f.read()
        except Exception as e:
            logging.error(f"Error reading file '{source}': {e}")
            return []

        document = Document(text=text)
        splitter = SentenceSplitter(
            chunk_size=config.CHUNK_SIZE,
            chunk_overlap=config.CHUNK_OVERLAP
        )
        nodes = splitter.get_nodes_from_documents([document])

        all_nodes = []
        for i, node in enumerate(nodes):
            metadata = generate_metadata_txt(
                source=source,
                index=i,
                max_index=len(nodes),
                file_format=ext,
                page_num=1  # Default just 1
            )
            node.metadata = metadata
            all_nodes.append(node)

        return all_nodes

if __name__ == "__main__":
    nodes = ExtractTXT.extract_and_chunk("./app/documents/Data quality.txt")
    for node in nodes:
        print(node.metadata)
        print(node.text[:300])
        print("---")
