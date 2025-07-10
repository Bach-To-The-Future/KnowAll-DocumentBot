from dataclasses import dataclass
import torch
import os

@dataclass(frozen=True)
class Config:
    EXTENSIONS:tuple = ("pdf", "csv", "xlsx", "docx", "doc", "pptx", "ppt", "md", "txt", "msg", "helm")
    PDF_EXTENSIONS_CONVERSION = ("docx", "pptx", "doc", "ppt")
    TXT_EXTENSIONS_CONVERSION = ("md", "msg", "helm")

    DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    CHUNK_SIZE:int = 550
    CHUNK_OVERLAP:int = 100

    EMBED_MODEL:str = "nomic-embed-text"
    EMBED_DIM:int = 768
    LLM_MODEL:str = "llama3.2:1b"

    MINIO_ENDPOINT:str = os.getenv("MINIO_ENDPOINT")
    MINIO_ACCESS_KEY:str = os.getenv("MINIO_ACCESS_KEY")
    MINIO_SECRET_KEY:str = os.getenv("MINIO_SECRET_KEY")
    MINIO_BUCKET:str = os.getenv("MINIO_BUCKET")

    MONGO_URI:str = os.getenv("MONGO_URI")
    MONGO_DB:str = os.getenv("MONGO_DB")
    MONGO_COLLECTION: str = os.getenv("MONGO_COLLECTION")

    QDRANT_HOST:str = os.getenv("QDRANT_HOST")
    QDRANT_PORT:int = os.getenv("QDRANT_PORT")
    QDRANT_COLLECTION:str = os.getenv("QDRANT_COLLECTION")

    OLLAMA_API_URL:str = os.getenv("OLLAMA_API_URL")

    STREAMLIT_API_URL:str = os.getenv("STREAMLIT_API_URL")
    STREAMLIT_PAGE_SIZE:int = 5