from dataclasses import dataclass

@dataclass
class Config:
    EXTENSIONS:tuple = ("pdf", "csv", "xlsx", "docx", "doc", "pptx", "ppt", "md", "txt", "msg", "helm")
    PDF_EXTENSIONS_CONVERSION = ("docx", "pptx", "doc", "ppt")
    TXT_EXTENSIONS_CONVERSION = ("md", "msg", "helm")

    CHUNK_SIZE:int = 800
    CHUNK_OVERLAP:int = 150

    EMBED_MODEL:str = "nomic-embed-text-v1"

    QDRANT_HOST:str = "localhost"
    QDRANT_PORT:int = 6333
    COLLECTION_NAME:str = "docs_chunks"