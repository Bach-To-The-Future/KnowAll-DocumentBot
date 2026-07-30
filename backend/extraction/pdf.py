import os
import fitz
import pandas as pd
import pdfplumber
from typing import List, Optional
import logging
from llama_index.core import Document
from core.config import get_settings
from core.exceptions import ExtractionError
from extraction.base import BaseExtractor
from extraction.helper import generate_metadata

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config = get_settings()

# Cached availability probe: "ok" or a human-readable reason. Checked once
# per process — OCR degrades gracefully to a clear error, never a crash.
_ocr_status: Optional[str] = None


def ocr_availability() -> str:
    global _ocr_status
    if _ocr_status is None:
        if not config.enable_ocr:
            _ocr_status = "disabled via ENABLE_OCR"
        else:
            try:
                import pytesseract
                pytesseract.get_tesseract_version()
                _ocr_status = "ok"
            except Exception as e:
                _ocr_status = f"unavailable ({e})"
                logger.warning(f"OCR not available: {_ocr_status}")
    return _ocr_status


class ExtractPDF(BaseExtractor):
    @staticmethod
    def _ocr_page(fitz_page) -> str:
        """Rasterize one page via PyMuPDF and OCR it with tesseract."""
        import pytesseract
        from PIL import Image
        pix = fitz_page.get_pixmap(dpi=config.ocr_dpi)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return pytesseract.image_to_string(image, lang=config.ocr_languages) or ""

    def extract_and_chunk(self, file_path: str) -> List[Document]:
        """Extract and chunk PDF content with metadata.

        Pages without an extractable text layer (scanned documents) fall back
        to OCR. Images are recorded as metadata only — embedding placeholder
        text pollutes retrieval.
        """
        if not self.validate_file(file_path):
            return []

        self.logger.info(f"Extracting and chunking: {file_path}")
        source = os.path.basename(file_path)
        ext = "pdf"
        ocr_state = ocr_availability()
        ocr_pages = 0

        all_nodes = []
        with pdfplumber.open(file_path) as pdf, fitz.open(file_path) as pdf_doc:
            image_counts = {}
            for page_index in range(pdf_doc.page_count):
                count = len(pdf_doc[page_index].get_images(full=True))
                if count:
                    image_counts[page_index + 1] = count

            for page_num, page in enumerate(pdf.pages, start=1):
                # Extract text; OCR only when the text layer is empty.
                text = page.extract_text()
                content_type = "text"
                if (not text or not text.strip()) and ocr_state == "ok":
                    try:
                        text = self._ocr_page(pdf_doc[page_num - 1])
                        content_type = "ocr"
                        if text.strip():
                            ocr_pages += 1
                    except Exception as e:
                        self.logger.warning(f"OCR failed on page {page_num} of {source}: {e}")
                        text = None

                if text and text.strip():
                    metadata = generate_metadata(
                        source=source,
                        index=page_num,
                        max_index=len(pdf.pages),
                        file_format=ext,
                        page_number=page_num,
                        content_type=content_type
                    )
                    if page_num in image_counts:
                        metadata["image_count"] = image_counts[page_num]
                    doc = self.create_document(text, metadata=metadata)
                    if doc:
                        nodes = self.chunk_document(doc)
                        for i, node in enumerate(nodes):
                            node.metadata.update({"chunk_index": i, "total_chunks": len(nodes)})
                        all_nodes.extend(nodes)

                # Extract tables (text-layer PDFs only; OCR'd pages have none)
                tables = page.extract_tables()
                for table_id, table in enumerate(tables):
                    if table:
                        df = pd.DataFrame(table[1:], columns=table[0])
                        if not df.empty:
                            csv_str = df.to_csv(index=False)
                            doc = self.create_document(csv_str, metadata=generate_metadata(
                                source=source,
                                index=table_id,
                                max_index=len(tables),
                                file_format=ext,
                                page_number=page_num,
                                content_type="table",
                                table_id=f"table_{table_id}",
                                headers=df.columns.tolist()
                            ))
                            if doc:
                                nodes = self.chunk_document(doc)
                                for i, node in enumerate(nodes):
                                    node.metadata.update({"chunk_index": i, "total_chunks": len(nodes)})
                                all_nodes.extend(nodes)

        if ocr_pages:
            self.logger.info(f"OCR recovered text from {ocr_pages} scanned page(s) in {source}")

        if not all_nodes:
            # Surface a diagnosable error instead of a generic "no content":
            # this is almost always a scanned document.
            hint = f"OCR is {ocr_state}" if ocr_state != "ok" else "OCR produced no text"
            raise ExtractionError(
                f"No extractable content in '{source}': the PDF appears to be "
                f"image-only/scanned and {hint}."
            )

        self.logger.info(f"Extracted {len(all_nodes)} chunks from {file_path}")
        return all_nodes
