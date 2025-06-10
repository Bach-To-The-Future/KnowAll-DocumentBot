from enum import Enum
 
from app.load_documents.parsers.csv import ExtractCSV
from app.load_documents.parsers.excel import ExtractXLSX
from app.load_documents.parsers.txt import ExtractText
from app.load_documents.parsers import ExtractTextConvertedFromMSG
from app.load_documents.parsers.pdf import ExtractPDF
from app.load_documents.parsers.convert_to_pdf import ExtractPDFConverted
 
 
class ExtractStrategy(Enum):
    PDF = ExtractPDF
    CSV = ExtractCSV
    DOCX = ExtractPDFConverted
    DOC = ExtractPDFConverted
    XLSX = ExtractXLSX
    PPTX = ExtractPDFConverted
    PPT = ExtractPDFConverted
    TXT = ExtractText
    MD = ExtractText
    MSG = ExtractTextConvertedFromMSG
 
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
        logger.info(f"Extracting file with type {ext}")
        return cls.__members__.get(ext, None).value if ext in cls.__members__ else None