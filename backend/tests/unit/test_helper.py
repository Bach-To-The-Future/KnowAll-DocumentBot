from core.config import get_settings
from extraction.helper import dynamic_rows_per_chunk, generate_metadata

settings = get_settings()


def test_wide_rows_get_few_per_chunk():
    # avg row length 800 chars, budget 1600 -> 2 rows per chunk
    assert dynamic_rows_per_chunk(total_chars=80_000, num_rows=100) == 2


def test_narrow_rows_capped_at_max():
    # avg row length 10 chars -> budget allows 160, cap wins
    assert dynamic_rows_per_chunk(total_chars=1_000, num_rows=100) == settings.table_max_rows_per_chunk


def test_giant_single_row_never_zero():
    # one row wider than the whole budget still yields 1 (never 0)
    assert dynamic_rows_per_chunk(total_chars=50_000, num_rows=10) == 1


def test_empty_table_defaults_to_max():
    assert dynamic_rows_per_chunk(total_chars=0, num_rows=0) == settings.table_max_rows_per_chunk


def test_generate_metadata_page_number():
    meta = generate_metadata(source="a.pdf", index=1, max_index=2,
                             file_format="PDF", page_number=7)
    assert meta["page_number"] == 7
    assert meta["file_format"] == "pdf"


def test_generate_metadata_omits_absent_fields():
    meta = generate_metadata(source="a.txt", index=0, max_index=1, file_format="txt")
    assert "page_number" not in meta
    assert "sheet_name" not in meta
