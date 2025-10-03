from typing import Dict, Any, List, Union
import re

import streamlit as st

from .args import JSON, ST_TAG

def is_running_in_streamlit() -> bool:
    """Check if the code is running in a Streamlit app.

    Returns:
        bool: True if running in Streamlit, False otherwise.
    """
    try:
        # In recent Streamlit versions
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except (ImportError, ModuleNotFoundError):
        return False

def extract_number_in_brackets(s: str) -> int | None:
    """
    If a string is in the format '[n]', returns the integer n. 
    Otherwise, returns None.
    """
    match = re.match(r'\[(\d+)\]$', s)
    return int(match.group(1)) if match else None

def update_dict(key: List[str], value: JSON, conf_dict: Union[Dict[str, JSON], List[JSON]]) -> None:
    """
    Update a nested dictionary or list with a value at the specified key path.

    Args:
        key (List[str]): The key path, e.g., ['user', 'addresses', '[0]', 'city'].
        value (JSON): The value to set at the specified key path.
        conf_dict (Union[Dict, List]): The nested structure to update.
    """
    # Get the current key/index from the path
    current_key = key[0]
    remaining_key = key[1:]
    
    # Extract list index if present (e.g., '[0]' -> 0)
    list_index = extract_number_in_brackets(current_key)

    # Base case: This is the last key in the path, so we set the value.
    if not remaining_key:
        if list_index is not None:
            assert isinstance(conf_dict, list), "Path indicates a list, but found a dictionary."
            # Extend the list with Nones if it's not long enough
            while len(conf_dict) <= list_index:
                conf_dict.append(None)
            conf_dict[list_index] = value
        else:
            assert isinstance(conf_dict, dict), "Path indicates a dictionary, but found a list."
            conf_dict[current_key] = value
        return

    # --- Recursive step ---
    # We are not at the end of the path yet, so we need to go deeper.

    if list_index is not None:
        # We're working with a list
        assert isinstance(conf_dict, list), "Path indicates a list, but found a dictionary."
        
        # Extend the list if the required index is out of bounds
        while len(conf_dict) <= list_index:
            conf_dict.append(None)
        
        # If the element at the index is not a dict/list, create the correct type
        # by checking what the *next* key in the path requires.
        next_key_is_list = extract_number_in_brackets(remaining_key[0]) is not None
        if conf_dict[list_index] is None:
            conf_dict[list_index] = [] if next_key_is_list else {}
        else:
            if next_key_is_list:
                assert isinstance(conf_dict[list_index], list), "List element at path index is not a list."
            else:
                assert isinstance(conf_dict[list_index], dict), "List element at path index is not a dict."
            
        # Recurse into the list element
        next_conf = conf_dict[list_index]
        assert isinstance(next_conf, (dict, list)), "List element at path index is not a dict or list."
        update_dict(remaining_key, value, next_conf)

    else:
        # We're working with a dictionary
        assert isinstance(conf_dict, dict), "Path indicates a dictionary, but found a list."

        # If the key doesn't exist or is not a dict/list, create the correct type
        # by checking what the *next* key in the path requires.
        next_key_is_list = extract_number_in_brackets(remaining_key[0]) is not None
        if current_key not in conf_dict:
            conf_dict[current_key] = [] if next_key_is_list else {}
        else:
            if next_key_is_list:
                assert isinstance(conf_dict[current_key], list), "Dictionary element at path key is not a list."
            else:
                assert isinstance(conf_dict[current_key], dict), "Dictionary element at path key is not a dict."

        # Recurse into the sub-dictionary
        next_conf = conf_dict[current_key]
        assert isinstance(next_conf, (dict, list)), "Dictionary element at path key is not a dict or list."
        update_dict(remaining_key, value, next_conf)

def get_conf_dict_from_session() -> Dict[str, JSON]:
    """Get the configuration dictionary from the Streamlit session state.

    Returns:
        JSON: The configuration dictionary.
    """
    conf_dict: JSON = dict()

    for key, value in st.session_state.items():
        if not isinstance(key, str):
            continue
        if key.startswith(ST_TAG):
            key_seq = key.split('.')[1:]
            update_dict(key_seq, value, conf_dict)

    return conf_dict
