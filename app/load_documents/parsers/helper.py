import re
from typing import Dict, Union, List

def get_key(file:str, i:Union[int, str]) -> str:
    '''
        Remove non alphanumeric characters from file name to ensure consistency
        File accept only lower case, upper case, number, underscore
    '''
    file = re.sub(r"[^a-zA-Z0-9]", "", file)
    return file + str(i)

def generate_metadata_csv_excel(
        source:str,
        index:Union[int, str],
        max_index:Union[int, str],
        file_format:str,
        sheet_name:str=None,
        **kwargs
) -> Dict:
    '''
        Generate metadata function for CSV, Excel
    '''
    metadata = dict(
        source = source,
        key = get_key(source, int(index)),
        len = int(max_index),
        file_format = file_format,
        sheet_name = sheet_name
    )
    metadata.update(kwargs)
    return metadata

def generate_metadata_txt(
        source:str,
        index:Union[int, str],
        max_index:Union[int, str],
        file_format:str,
        page_num:int,
        **kwargs
) -> Dict:
    '''
        Generate metadata function for Text
    '''
    metadata = dict(
        source = source,
        key = get_key(source, int(index)),
        len = int(max_index),
        file_format = file_format,
        page_num=page_num
    )
    metadata.update(kwargs)
    return metadata

def generate_metadata_pdf(
        source: str,
        index: Union[int, str],
        max_index: Union[int, str],
        file_format: str,
        page_num: int,
        content_type: str = "text",
        table_id: str = None,
        figure_id: str = None,
        headers: List[str] = None,
        row_range: str = None,
        **kwargs
) -> Dict:
    '''
        Generate metadata function for Pdf
    '''
    metadata = dict(
        source=source,
        key=get_key(source, int(index)),
        len=int(max_index),
        file_format=file_format,
        page_num=page_num,
        content_type=content_type
    )
    if table_id:
        metadata["table_id"] = table_id
    if figure_id:
        metadata["figure_id"] = figure_id
    if headers:
        metadata["headers"] = headers
    if row_range:
        metadata["row_range"] = row_range

    metadata.update(kwargs)
    return metadata