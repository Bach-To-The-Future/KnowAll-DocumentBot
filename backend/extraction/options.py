import logging
from enum import Enum
from pathlib import Path

from core.exceptions import UnsupportedFormatError
from extraction.base import BaseExtractor
from extraction.csv import ExtractCSV
from extraction.docx_format import ExtractDOCX
from extraction.excel import ExtractXLSX
from extraction.pdf import ExtractPDF
from extraction.pptx import ExtractPPTX
from extraction.txt import ExtractTXT

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
    # Phase 4.4: ExtractHELM was a subclass of ExtractTXT that added a log
    # line and nothing else. The CLASS was dead; the EXTENSION was not —
    # dispatch is by suffix, so a .helm upload reached it. Mapped straight
    # to ExtractTXT so behaviour is byte-identical and the capability
    # survives. Not offered by the UI's accept list, which is a product
    # decision, not a code one.
    HELM = ExtractTXT

    @classmethod
    def get_extractor(cls, file_path: str) -> BaseExtractor:
        """Get the appropriate extractor based on file extension.
        Raises UnsupportedFormatError for extensions with no extractor."""
        ext = Path(file_path).suffix.lstrip(".").upper()
        logging.info(f"Extracting file with type {ext}")
        extractor_cls = cls.__members__.get(ext, None)
        if not extractor_cls:
            raise UnsupportedFormatError(f"No extractor for extension: {ext.lower() or '(none)'}")
        extractor: BaseExtractor = extractor_cls.value()
        return extractor
