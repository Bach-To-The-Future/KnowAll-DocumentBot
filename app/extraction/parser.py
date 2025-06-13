import os
from llama_index.core import Document
from llama_index.readers.file import (
    PDFReader,
    CSVReader,
    DocxReader,
    PandasExcelReader,
    PptxReader,
    TextFileReader,
    MarkdownReader
)
from llama_index.core.node_parser import TokenTextSplitter

def load_documents(file_path:str, ext:str) -> list[Document]:
    ext = ext.lower()
    match ext:
        case "pdf":
            return PDFReader().load_data(file_path)
        case "csv":
            return CSVReader().load_data(file_path)
        case "docx":
            return DocxReader().load_data(file_path)
        case "xlsx":
            return PandasExcelReader().load_data(file_path)
        case "pptx":
            return PptxReader().load_data(file_path)
        case "txt":
            return TextFileReader().load_data(file_path)
        case "md":
            return MarkdownReader().load_data(file_path)
        case _:
            raise ValueError(f"File type not supported '{ext}'")
        
def parse_chunk(doc_path:str):
    ext = os.path.splitext(doc_path)[-1][1:].lower()
    documents = load_documents(doc_path, ext)

    splitter = TokenTextSplitter(
        separator = " ",
        chunksize = 512,
        chunk_overlap = 50
    )
    nodes = splitter.get_nodes_from_documents(documents)

    for i, node in enumerate(nodes):
        node.metadata["chunk_id"] = i
        node.metadata["source"] = os.path.basename(doc_path)
        node.metadata["file_type"] = ext

        # Add page number if available
        page_num = node.metadata.get("page_label") or node.metadata.get("page_number")
        if page_num:
            node.metadata["page_number"] = page_num
    
    return nodes