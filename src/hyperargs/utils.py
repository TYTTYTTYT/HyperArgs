from typing import Dict, Optional, List, Union, Tuple
import re

import streamlit as st

from .args import JSON, ST_TAG, JSON_VALUE

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

    for key in st.session_state.keys():
        if not isinstance(key, str):
            continue
        if key.startswith(f'{ST_TAG}'):
            value = st.session_state[key]
            key_seq = key.split('.')[1:]
            update_dict(key_seq, value, conf_dict)

    return conf_dict

def flatten_dict(
    d: Union[Dict[str, JSON], List[JSON]],
    parent_key: Optional[str] = None,
    sep: str = '.'
) -> Dict[str, JSON_VALUE]:
    """Flattens a nested dictionary or list into a single-level dictionary.

    Args:
        d (Union[Dict[str, JSON], List[JSON]]): The dictionary or list to flatten.
        parent_key (str, optional): The prefix for the new keys. Defaults to None.
        sep (str, optional): The separator between keys. Defaults to '.'.

    Returns:
        Dict[str, JSON]: The flattened dictionary.
    """
    items = []
    # --- Handling dictionaries ---
    if isinstance(d, dict):
        for k, v in d.items():
            # Construct the new key
            new_key = f'{parent_key}{sep}{k}' if parent_key is not None else k
            # If the value is another structure, recurse
            if isinstance(v, (dict, list)):
                items.extend(flatten_dict(v, new_key, sep=sep).items())
            # Otherwise, it's a leaf node
            else:
                items.append((new_key, v))
    # --- Handling lists ---
    elif isinstance(d, list):
        for i, v in enumerate(d):
            # Construct the new key with consistent bracket notation
            new_key = f'{parent_key}{sep}[{i}]' if parent_key is not None else f'[{i}]'
            # If the value is another structure, recurse
            if isinstance(v, (dict, list)):
                items.extend(flatten_dict(v, new_key, sep=sep).items())
            # Otherwise, it's a leaf node
            else:
                items.append((new_key, v))
                
    return dict(items)

def is_dict_different(
    d1: Dict[str, JSON],
    d2: Dict[str, JSON],
) -> bool:
    """
    Check if two dictionaries are different.

    Args:
        d1 (Dict[str, JSON]): The first dictionary.
        d2 (Dict[str, JSON]): The second dictionary.
        sep (str, optional): The separator used in the flattened keys. Defaults to '.'.

    Returns:
        bool: True if the dictionaries are different, False otherwise.
    """
    d1_flat = flatten_dict(d1)
    d2_flat = flatten_dict(d2)

    for k, v in d1_flat.items():
        if k not in d2_flat:
            return True
        if d2_flat[k] != v:
            return True
    for k, v in d2_flat.items():
        if k not in d1_flat:
            return True

    return False

def find_chaned_values(
    d1: Dict[str, JSON],
    d2: Dict[str, JSON],
    sep: str = '.'
) -> Dict[str, JSON_VALUE]:
    """Find keys that are changed from d1 to d2.

    Args:
        d1 (Dict[str, JSON]): The first dictionary.
        d2 (Dict[str, JSON]): The second dictionary.
        sep (str, optional): The separator used in the flattened keys. Defaults to '.'.

    Returns:
        List[str]: A list of keys that are different between the two dictionaries.
    """
    d1_flat = flatten_dict(d1, sep=sep)
    d2_flat = flatten_dict(d2, sep=sep)

    changed_keys = {}
    for k, v in d1_flat.items():
        if k in d2_flat and d2_flat[k] != v:
            changed_keys[k] = d2_flat[k]

    return changed_keys
