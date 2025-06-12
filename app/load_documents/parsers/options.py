from enum import Enum
 
import logging
from app.load_documents.parsers.csv import ExtractCSV
from app.load_documents.parsers.excel import ExtractXLSX
from app.load_documents.parsers.txt import ExtractText
from app.load_documents.parsers.pdf import ExtractPDF
 
logging.basicConfig(level=logging.INFO)

class ExtractStrategy(Enum):
    PDF = ExtractPDF
    CSV = ExtractCSV
    DOCX = ExtractPDF
    DOC = ExtractPDF
    XLSX = ExtractXLSX
    PPTX = ExtractPDF
    PPT = ExtractPDF
    TXT = ExtractText
    MD = ExtractText
    MSG = ExtractText
 
    @classmethod
    def get_extractor(cls, file_path: str):
        """
        Determines the appropriate extraction class based on file extension.
 
        Args:
            file_path (str): The file path or URL.
 
        Returns:
            Extractor class if found, otherwise None.
        """
        from pathlib import Path
 
        ext = Path(file_path).suffix.lstrip(".").lower()
        logging.info(f"Extracting file with type {ext}")
        return cls.__members__.get(ext, None).value if ext in cls.__members__ else None