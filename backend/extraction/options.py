import logging
from enum import Enum
from pathlib import Path
from core.exceptions import UnsupportedFormatError
from extraction.base import BaseExtractor
from extraction.csv import ExtractCSV
from extraction.excel import ExtractXLSX
from extraction.txt import ExtractTXT
from extraction.pdf import ExtractPDF
from extraction.docx_format import ExtractDOCX
from extraction.pptx import ExtractPPTX
from extraction.helm import ExtractHELM

logging.basicConfig(level=logging.INFO)


class ExtractStrategy(Enum):
    # Only formats these libraries can actually parse. Legacy doc/ppt and msg
    # were removed: python-docx/python-pptx reject the old binary formats and
    # the MSG extractor was an unimplemented stub.
    PDF = ExtractPDF
    CSV = ExtractCSV
    DOCX = ExtractDOCX
    XLSX = ExtractXLSX
    PPTX = ExtractPPTX
    TXT = ExtractTXT
    MD = ExtractTXT
    HELM = ExtractHELM

    @classmethod
    def get_extractor(cls, file_path: str) -> BaseExtractor:
        """Get the appropriate extractor based on file extension.
        Raises UnsupportedFormatError for extensions with no extractor."""
        ext = Path(file_path).suffix.lstrip(".").upper()
        logging.info(f"Extracting file with type {ext}")
        extractor_cls = cls.__members__.get(ext, None)
        if not extractor_cls:
            raise UnsupportedFormatError(f"No extractor for extension: {ext.lower() or '(none)'}")
        return extractor_cls.value()
