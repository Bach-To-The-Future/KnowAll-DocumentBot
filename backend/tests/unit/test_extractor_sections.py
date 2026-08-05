"""Finding #29: chunks from csv, xlsx and pptx carried no section metadata.

Measured on tier B: 13 of 22 rank-1 chunks had no `section_title` at all, and
they were exactly the extractors that build no heading stack. Two consequences,
both real:

  * `_expand_with_sections` fell through to a plain +/-1 window, so row-groups
    of the same table were never treated as related;
  * the cross-encoder was handed a bare row-group whose leading line was a CSV
    header, with nothing saying which table or sheet it came from.

These tests run the real extractors over fixtures written in the test, so they
fail if any of the three stops emitting the field.

PDF is deliberately excluded. Its chunks are pages, and giving each page its own
section title would make every section a singleton — strictly worse than the
+/-1 window it uses today. A pdf still has no document-level title in its
reranker input; that is proposal P-2 candidate C1 and is not fixed here.
"""
from __future__ import annotations

import csv as csvmod
from pathlib import Path

import pytest

from extraction.csv import ExtractCSV
from extraction.excel import ExtractXLSX
from extraction.pptx import ExtractPPTX


@pytest.fixture
def sales_csv(tmp_path: Path) -> str:
    path = tmp_path / "b03-sales.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csvmod.writer(fh)
        writer.writerow(["region", "quarter", "units_sold", "revenue_cad"])
        for i in range(40):
            writer.writerow([f"R{i % 4}", f"Q{i % 4 + 1}", 100 + i, 1200 + i * 12])
    return str(path)


@pytest.fixture
def inventory_xlsx(tmp_path: Path) -> str:
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "b05-inventory.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Inventory"
    sheet.append(["sku", "warehouse", "on_hand"])
    for i in range(12):
        sheet.append([f"SKU-{i:03d}", "Regina" if i % 2 else "Halifax", 40 + i])
    thresholds = book.create_sheet("Thresholds")
    thresholds.append(["metric", "value"])
    thresholds.append(["reorder_point", 25])
    book.save(path)
    return str(path)


@pytest.fixture
def review_pptx(tmp_path: Path) -> str:
    pptx = pytest.importorskip("pptx")
    path = tmp_path / "b07-review.pptx"
    prs = pptx.Presentation()
    for title, body in [("Quarterly Review", "Customer churn fell to 3.1 percent."),
                        ("Next Steps", "Migrate the reporting pipeline before the freeze.")]:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = body
    prs.save(path)
    return str(path)


def sections(nodes) -> list[str | None]:
    return [n.metadata.get("section_title") for n in nodes]


def test_csv_row_groups_all_declare_the_same_table(sales_csv: str) -> None:
    nodes = ExtractCSV().extract_and_chunk(sales_csv)
    assert nodes
    # One title for the whole file: row-groups of one table ARE one section.
    assert set(sections(nodes)) == {"Table: b03-sales"}


def test_xlsx_chunks_declare_their_sheet(inventory_xlsx: str) -> None:
    nodes = ExtractXLSX().extract_and_chunk(inventory_xlsx)
    assert nodes
    titles = set(sections(nodes))
    assert titles == {"Sheet: Inventory", "Sheet: Thresholds"}
    # Two sheets must not collapse into one section, or expansion would drag
    # unrelated rows into the answer.
    assert len(titles) == 2


def test_xlsx_section_title_matches_the_prefix_the_text_already_carries(
    inventory_xlsx: str,
) -> None:
    """_expand_with_sections strips f"{section}\\n\\n" from neighbours. The excel
    text starts with "Sheet: <name>", so the two must agree or the repeat
    survives into every expanded passage."""
    nodes = ExtractXLSX().extract_and_chunk(inventory_xlsx)
    for node in nodes:
        assert node.text.startswith(node.metadata["section_title"])


def test_pptx_chunks_declare_their_slide(review_pptx: str) -> None:
    nodes = ExtractPPTX().extract_and_chunk(review_pptx)
    assert nodes
    titles = sections(nodes)
    assert all(t and t.startswith("Slide ") for t in titles), titles
    assert any("Quarterly Review" in t for t in titles if t)


def test_every_chunk_from_these_three_formats_has_a_section(
    sales_csv: str, inventory_xlsx: str, review_pptx: str
) -> None:
    """The regression guard. Finding #29 was 13 of 22 rank-1 chunks with the
    field simply absent; absence must never be reintroduced silently."""
    for extractor, path in ((ExtractCSV(), sales_csv),
                            (ExtractXLSX(), inventory_xlsx),
                            (ExtractPPTX(), review_pptx)):
        nodes = extractor.extract_and_chunk(path)
        missing = [n for n in nodes if not n.metadata.get("section_title")]
        assert not missing, f"{type(extractor).__name__}: {len(missing)} chunks without a section"
