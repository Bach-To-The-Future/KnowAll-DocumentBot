from enum import Enum
 
import logging
from extraction.csv import ExtractCSV
from extraction.excel import ExtractXLSX
from extraction.txt import ExtractTXT
from extraction.pdf import ExtractPDF
from extraction.docx_format import ExtractDOCX
 
logging.basicConfig(level=logging.INFO)

class ExtractStrategy(Enum):
    PDF = ExtractPDF
    CSV = ExtractCSV
    DOCX = ExtractDOCX
    DOC = ExtractDOCX
    XLSX = ExtractXLSX
    PPTX = ExtractPDF
    PPT = ExtractPDF
    TXT = ExtractTXT
    MD = ExtractTXT
    MSG = ExtractTXT
 
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
 
        ext = Path(file_path).suffix.lstrip(".").upper()
        logging.info(f"Extracting file with type {ext}")
        return cls.__members__.get(ext, None).value if ext in cls.__members__ else None