from typing import Dict, Any, List

import streamlit as st

from .args import JSON

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

def update_dict(key: List[str], value: Any, conf_dict: JSON) -> None:
    """Update a nested dictionary with a value at the specified key path.

    Args:
        key (List[str]): The key path as a list of strings.
        value (Any): The value to set at the specified key path.
        conf_dict (JSON): The nested dictionary to update.
    """
    if len(key) == 1:
        conf_dict[key[0]] = value
    else:
        update_dict(key[1:], value, conf_dict[key[0]])


def get_conf_dict_from_session() -> Dict[str, JSON]:
    """Get the configuration dictionary from the Streamlit session state.

    Returns:
        JSON: The configuration dictionary.
    """
    conf_dict: JSON = dict()

    for key, value in st.session_state.items():
        if not isinstance(key, str):
            continue
        if key.startswith("$$这是filed✅$$"):
            key_seq = key.split('.')[1:]
            update_dict(key_seq, value, conf_dict)

    return conf_dict
