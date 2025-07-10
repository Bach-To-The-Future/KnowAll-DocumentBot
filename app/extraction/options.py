import os
from enum import Enum
import logging
from pathlib import Path
from extraction.base import BaseExtractor
from extraction.csv import ExtractCSV
from extraction.excel import ExtractXLSX
from extraction.txt import ExtractTXT
from extraction.pdf import ExtractPDF
from extraction.docx_format import ExtractDOCX
from extraction.pptx import ExtractPPTX
from extraction.msg import ExtractMSG
from extraction.helm import ExtractHELM

logging.basicConfig(level=logging.INFO)

class ExtractStrategy(Enum):
    PDF = ExtractPDF
    CSV = ExtractCSV
    DOCX = ExtractDOCX
    DOC = ExtractDOCX
    XLSX = ExtractXLSX
    PPTX = ExtractPPTX
    PPT = ExtractPPTX
    TXT = ExtractTXT
    MD = ExtractTXT
    MSG = ExtractMSG
    HELM = ExtractHELM

    @classmethod
    def get_extractor(cls, file_path: str) -> BaseExtractor:
        """Get the appropriate extractor based on file extension."""
        ext = Path(file_path).suffix.lstrip(".").upper()
        logging.info(f"Extracting file with type {ext}")
        extractor_cls = cls.__members__.get(ext, None)
        if not extractor_cls:
            logging.error(f"No extractor found for extension: {ext}")
            return None
        return extractor_cls.value()