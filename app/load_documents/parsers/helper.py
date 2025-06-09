import re
from typing import Dict, Union

def get_key(file:str, i:Union[int, str]) -> str:
    '''
        Remove non alphanumeric characters from file name to ensure consistency
        File accept only lower case, upper case, number, underscore
    '''
    file = re.sub(r"[^a-zA-Z0-9]", "", file)
    return file + str(i)

def generate_metadata(
        source:str,
        index:Union[int, str],
        max_index:Union[int, str],
        file_format:str,
        sheet_name:str=None,
        **kwargs
) -> Dict:
    '''
        Base generate metadata function for each file type
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