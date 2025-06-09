from dataclasses import dataclass

@dataclass
class Config:
    EXTENSIONS:tuple = ("pdf", "csv", "xlsx", "docx", "md", "txt", "pptx")

    CHUNK_SIZE:int = 512
    CHUNK_OVERLAP:int = 100