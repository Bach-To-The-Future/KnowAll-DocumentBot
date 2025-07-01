from docx import Document as DocxDocument
from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter
from app.config import Config
from .helper import generate_metadata_pdf
import os

config = Config()

class ExtractDOCX:

    @staticmethod
    def extract_and_chunk(file_path: str):
        print(f"📂 Extracting and chunking: {file_path}")
        doc = DocxDocument(file_path)

        # --- Extract text paragraphs ---
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        print(f"📝 Found {len(paragraphs)} non-empty paragraphs")

        # --- Extract tables ---
        table_texts = []
        for table_idx, table in enumerate(doc.tables):
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells)
                if row_text.strip():
                    table_texts.append(row_text)
        print(f"📊 Extracted {len(table_texts)} table rows")

        # --- Combine all extracted content ---
        full_text = "\n".join(paragraphs + table_texts)
        print(f"📄 Full extracted text length: {len(full_text)} characters")

        if not full_text.strip():
            print("⚠️ No text content found in .docx document.")
            return []

        # --- Chunking ---
        document = Document(text=full_text)
        splitter = SentenceSplitter(
            chunk_size=config.CHUNK_SIZE,
            chunk_overlap=config.CHUNK_OVERLAP
        )
        nodes = splitter.get_nodes_from_documents([document])

        all_nodes = []
        source = os.path.basename(file_path)

        for i, node in enumerate(nodes):
            metadata = generate_metadata_pdf(
                source=source,
                index=i,
                max_index=len(nodes),
                file_format="docx",
                page_num=None
            )
            node.metadata = metadata
            all_nodes.append(node)

        print(f"✅ Total chunks created: {len(all_nodes)}")
        return all_nodes

if __name__ == "__main__":
    nodes = ExtractDOCX.extract_and_chunk("./app/documents/Data Engineer Concepts.docx")
    for node in nodes:
        print(node.metadata)
        print(node.text[:150])
        print("---")
