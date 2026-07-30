import logging
import os
from collections.abc import Iterator

from docx import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from llama_index.core import Document

from extraction.base import BaseExtractor
from extraction.helper import dynamic_rows_per_chunk, generate_metadata

logging.basicConfig(level=logging.INFO)


class ExtractDOCX(BaseExtractor):
    @staticmethod
    def _iter_block_items(docx) -> Iterator[Paragraph | Table]:
        """Yield paragraphs and tables in true document order (python-docx
        exposes doc.tables separately, which loses their position)."""
        for child in docx.element.body.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, docx)
            elif isinstance(child, CT_Tbl):
                yield Table(child, docx)

    @staticmethod
    def _heading_level(paragraph: Paragraph) -> int | None:
        style = paragraph.style.name if paragraph.style else ""
        if style and style.startswith("Heading"):
            try:
                return int(style.split()[-1])
            except ValueError:
                return 1
        return None

    @staticmethod
    def _table_chunks(table: Table) -> list[str]:
        """Row-group chunks; the header row is repeated in every chunk so no
        chunk is header-less."""
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        rows = [r for r in rows if any(r)]
        if not rows:
            return []
        header = " | ".join(rows[0])
        data_rows = [" | ".join(r) for r in rows[1:]]
        if not data_rows:
            return [header]
        # Rows per chunk adapt to row width (token-aware, header excluded).
        rows_per_chunk = dynamic_rows_per_chunk(sum(len(r) for r in data_rows), len(data_rows))
        chunks = []
        for start in range(0, len(data_rows), rows_per_chunk):
            body = "\n".join(data_rows[start:start + rows_per_chunk])
            chunks.append(f"{header}\n{body}")
        return chunks

    def extract_and_chunk(self, file_path: str) -> list[Document]:
        """Heading-path chunking: split on heading boundaries, prepend the
        full hierarchy ("Doc > H1 > H2") to every chunk before embedding."""
        if not self.validate_file(file_path):
            return []

        self.logger.info(f"Extracting and chunking: {file_path}")
        source = os.path.basename(file_path)
        stem = os.path.splitext(source)[0]
        ext = os.path.splitext(file_path)[-1][1:].lower()

        docx = DocxDocument(file_path)
        all_nodes: list[Document] = []
        heading_stack: list[tuple] = []  # [(level, heading_text)]
        buffer: list[str] = []

        def current_path() -> str:
            return " > ".join([stem] + [text for _, text in heading_stack])

        def emit(text: str, content_type: str, split: bool):
            path = current_path()
            pieces = self.chunk_text(text) if split else [text]
            for piece in pieces:
                doc = self.create_document(
                    f"{path}\n\n{piece}",  # heading path travels with every chunk
                    metadata=generate_metadata(
                        source=source,
                        index=0,
                        max_index=1,
                        file_format=ext,
                        content_type=content_type,
                        section_title=path,
                    )
                )
                if doc:
                    all_nodes.append(doc)

        def flush_buffer():
            text = "\n".join(buffer).strip()
            buffer.clear()
            if text:
                emit(text, content_type="text", split=True)

        for block in self._iter_block_items(docx):
            if isinstance(block, Paragraph):
                text = block.text.strip()
                if not text:
                    continue
                level = self._heading_level(block)
                if level is not None:
                    # Heading boundary: close the current section, then update
                    # the stack — pop anything at the same or deeper level.
                    flush_buffer()
                    while heading_stack and heading_stack[-1][0] >= level:
                        heading_stack.pop()
                    heading_stack.append((level, text))
                else:
                    buffer.append(text)
            else:  # Table, emitted in-position under the current heading path
                flush_buffer()
                for chunk in self._table_chunks(block):
                    emit(chunk, content_type="table", split=False)
        flush_buffer()

        # Document-order chunk numbering (chunk_seq/etag are set by the
        # ingestion pipeline).
        for i, node in enumerate(all_nodes):
            node.metadata.update({"chunk_index": i, "total_chunks": len(all_nodes)})

        self.logger.info(f"Extracted {len(all_nodes)} chunks from {file_path}")
        return all_nodes
