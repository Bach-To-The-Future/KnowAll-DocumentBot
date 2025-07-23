from dataclasses import dataclass
import os
import subprocess

def has_nvidia_gpu():
    """Check for NVIDIA GPU using nvidia-smi."""
    try:
        subprocess.check_output(['nvidia-smi'], stderr=subprocess.STDOUT)
        return 'gpu'
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 'cpu'

@dataclass(frozen=True)
class Config:
    EXTENSIONS: tuple = ("pdf", "csv", "xlsx", "docx", "doc", "pptx", "ppt", "md", "txt", "msg", "helm")
    PDF_EXTENSIONS_CONVERSION = ("docx", "pptx", "doc", "ppt")
    TXT_EXTENSIONS_CONVERSION = ("md", "msg", "helm")

    DEVICE = has_nvidia_gpu()
    CHUNK_SIZE: int = 550
    CHUNK_OVERLAP: int = 100

    # Embedding model configuration
    USE_OPENAI_EMBEDDING: bool = os.getenv("USE_OPENAI_EMBEDDING", "false").lower() == "true"
    EMBED_MODEL: str = "text-embedding-3-small" if USE_OPENAI_EMBEDDING else "nomic-embed-text:latest"
    EMBED_DIM: int = 1536 if USE_OPENAI_EMBEDDING else 768  # text-embedding-3-small uses 1536 dimensions

    # LLM model configuration
    USE_OPENAI_LLM: bool = os.getenv("USE_OPENAI_LLM", "false").lower() == "true"
    LLM_MODEL: str = "gpt-4o-mini" if USE_OPENAI_LLM else "llama3.2:1b"

    # OpenAI API configuration
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")

    MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT")
    MINIO_ACCESS_KEY: str = os.getenv("MINIO_ACCESS_KEY")
    MINIO_SECRET_KEY: str = os.getenv("MINIO_SECRET_KEY")
    MINIO_BUCKET: str = os.getenv("MINIO_BUCKET")

    MONGO_URI: str = os.getenv("MONGO_URI")
    MONGO_DB: str = os.getenv("MONGO_DB")
    MONGO_COLLECTION: str = os.getenv("MONGO_COLLECTION")

    QDRANT_HOST: str = os.getenv("QDRANT_HOST")
    QDRANT_PORT: int = os.getenv("QDRANT_PORT")
    QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION")

    OLLAMA_API_URL: str = os.getenv("OLLAMA_API_URL")

    STREAMLIT_API_URL: str = os.getenv("STREAMLIT_API_URL")
    STREAMLIT_PAGE_SIZE: int = 5