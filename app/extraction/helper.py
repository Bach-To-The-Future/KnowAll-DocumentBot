import re
from typing import Dict, Union, List

def get_key(file: str, i: Union[int, str]) -> str:
    """Generate a unique key from filename and index."""
    file = re.sub(r"[^a-zA-Z0-9]", "", file)
    return f"{file}_{i}"

def generate_metadata(
    source: str,
    index: Union[int, str],
    max_index: Union[int, str],
    file_format: str,
    page_num: int = None,
    content_type: str = "text",
    table_id: str = None,
    figure_id: str = None,
    headers: List[str] = None,
    row_range: str = None,
    sheet_name: str = None,
    section_title: str = None,
    **kwargs
) -> Dict:
    """Generate standardized metadata for all document types."""
    metadata = {
        "source": source,
        "key": get_key(source, int(index)),
        "chunk_index": int(index),
        "total_chunks": int(max_index),
        "file_format": file_format.lower(),
        "content_type": content_type,
    }
    if page_num is not None:
        metadata["page_number"] = page_num
    if table_id:
        metadata["table_id"] = table_id
    if figure_id:
        metadata["figure_id"] = figure_id
    if headers:
        metadata["headers"] = headers
    if row_range:
        metadata["row_range"] = row_range
    if sheet_name:
        metadata["sheet_name"] = sheet_name
    if section_title:
        metadata["section_title"] = section_title
    metadata.update(kwargs)
    return metadata