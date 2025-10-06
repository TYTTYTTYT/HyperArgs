from typing import Any, Dict, Union, Optional, Type, Callable, TypeVar, ParamSpec, Set, List, overload
from typing_extensions import Self
from collections import defaultdict
import copy
import json
import logging
import sys
import __main__
import tempfile
import subprocess
import os
import time
import psutil

import networkx as nx
import tomli
import tomli_w
import yaml
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from .args import Arg, JSON, ST_TAG, JSON_VALUE
from .utils import is_running_in_streamlit, get_conf_dict_from_session, find_chaned_values, is_dict_different

logger = logging.getLogger(__name__)

C = TypeVar('C', bound='Conf')
P = ParamSpec('P')
R = TypeVar('R')

class Conf:
    """Base class for configuration objects."""

    _dep_graph: nx.DiGraph = nx.DiGraph()
    _monitors: Dict[str, Set[str]] = defaultdict(set)

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        # Add a node for the subclass in the dependency graph
        cls._dep_graph = copy.deepcopy(cls._dep_graph)
        cls._monitors = copy.deepcopy(cls._monitors)

        for name in dir(cls):
            if name.startswith('_'):
                continue
            value = getattr(cls, name)

            if callable(value):
                if hasattr(value, '_monitor_on'):
                    for field in getattr(value, '_monitor_on', []):
                        cls._monitors[field].add(name)
                continue

            if not cls.check_conf_type(value):
                raise TypeError((f"Unsupported type for field '{name}': {value}({type(value)}), only Arg, list, "
                                 "tuple, or Conf are allowed"))

            cls._dep_graph.add_node(name)
            setattr(cls, name, copy.deepcopy(value))

    @staticmethod
    def check_conf_type(value: Any) -> bool:
        if isinstance(value, Arg):
            return True
        if isinstance(value, list):
            return all(Conf.check_conf_type(v) for v in value)
        if isinstance(value, Conf):
            return True
        return False

    def to_dict(self) -> Dict[str, JSON]:
        """Convert the configuration to a dictionary."""
        values: Dict[str, JSON] = {}
        for name in dir(self):
            if name.startswith('_'):
                continue
            value = getattr(self, name)
            if callable(value):
                continue

            if not self.check_conf_type(value):
                raise TypeError((f"Unsupported type for field '{name}': {type(value)}, only Arg, list, tuple, or Conf "
                                 "are allowed"))

            values[name] = _to_json_dict(value)

        return values

    def field_names(self) -> List[str]:
        """Get the names of all fields in the configuration."""
        return list(self.to_dict().keys())

    def to_json(self, indent: Optional[Union[str, int]] = None) -> str:
        """Convert the configuration to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_toml(self) -> str:
        """Convert the configuration to a TOML string."""
        return tomli_w.dumps(self.to_dict())

    def to_yaml(self) -> str:
        """Convert the configuration to a YAML string."""
        return yaml.dump(self.to_dict(), sort_keys=False)

    @staticmethod
    def add_dependency(parent: str, child: str) -> Callable[[Type[C]], Type[C]]:
        """Add a dependency relationship from parent to child in the graph."""
        def decorator(cls: Type[C]) -> Type[C]:
            assert isinstance(cls._dep_graph, nx.DiGraph), "_dep_graph must be a networkx DiGraph"
            assert parent != child, "Parent and child cannot be the same"
            assert not nx.has_path(cls._dep_graph, child, parent), (f"Adding dependency from '{parent}' to '{child}' "
                                                                    "would create a conf dependency cycle")
            assert hasattr(cls, parent), f"Parent attribute '{parent}' does not exist in class '{cls.__name__}'"
            assert hasattr(cls, child), f"Child attribute '{child}' does not exist in class '{cls.__name__}'"
            assert not cls._dep_graph.has_edge(parent, child), f"Dependency from '{parent}' to '{child}' already exists"

            cls._dep_graph.add_edge(parent, child)
            return cls
        return decorator

    @staticmethod
    def monitor_on(depend_fields: Union[str, List[str]]) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Decorator to monitor changes on specified fields."""
        if isinstance(depend_fields, str):
            depend_fields = [depend_fields]

        def decorator(func: Callable[P, R]) -> Callable[P, R]:
            setattr(func, '_monitor_on', depend_fields)
            return func

        return decorator

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        if name in self._monitors:
            for monitor in self._monitors[name]:
                if hasattr(self, monitor):
                    method = getattr(self, monitor)
                    if callable(method):
                        method()

        if name not in self._dep_graph:
            self._dep_graph.add_node(name)

    @classmethod
    def from_dict(cls: Type[C], data: Dict[str, JSON], strict: bool = False) -> C:
        """Create a configuration instance from a dictionary. TODO"""
        instance = cls()
        data_ = copy.deepcopy(data)

        for name in nx.topological_sort(instance._dep_graph):
            if name in data_:
                value = data_[name]
                attr = getattr(cls, name)

                parsed_value = _parse_attr(value, attr)
                setattr(instance, name, parsed_value)

                data_.pop(name)

        if strict and data_:
            raise ValueError(f"Unexpected fields in data: {list(data_.keys())}")
        elif data_:
            logger.warning(f"Ignored unexpected fields in data: {list(data_.keys())}")

        return instance.parse_dict(data, strict=strict)

    def parse_dict(self, data: Dict[str, JSON], strict: bool = False) -> Self:
        """Create a configuration instance from a dictionary. TODO"""
        data = copy.deepcopy(data)

        for name in nx.topological_sort(self._dep_graph):
            if name in data:
                value = data[name]
                attr = getattr(self, name)

                parsed_value = _update_parse_attr(value, attr)
                setattr(self, name, parsed_value)

                data.pop(name)

        if strict and data:
            raise ValueError(f"Unexpected fields in data: {list(data.keys())}")
        elif data:
            logger.warning(f"Ignored unexpected fields in data: {list(data.keys())}")

        return self

    @classmethod
    def from_json(cls: Type[C], json_str: str, strict: bool = False) -> C:
        """Create a configuration instance from a JSON string."""
        data = json.loads(json_str)
        assert isinstance(data, dict), "JSON string must represent a dictionary"
        return cls.from_dict(data, strict=strict)

    @classmethod
    def from_toml(cls: Type[C], toml_str: str, strict: bool = False) -> C:
        """Create a configuration instance from a TOML string."""
        data = tomli.loads(toml_str)
        assert isinstance(data, dict), "TOML string must represent a dictionary"
        return cls.from_dict(data, strict=strict)

    @classmethod
    def from_yaml(cls: Type[C], yaml_str: str, strict: bool = False) -> C:
        """Create a configuration instance from a YAML string."""
        data = yaml.safe_load(yaml_str)
        assert isinstance(data, dict), "YAML string must represent a dictionary"
        return cls.from_dict(data, strict=strict)

    @classmethod
    def parse_command_line(cls: Type[C], strict: bool = False) -> C:
        """Parse configuration file according to command line arguments."""

        if len(sys.argv) <= 2:
            if len(sys.argv) == 1:
                raise ValueError("No command line arguments provided. Use --help for usage information.")
            if sys.argv[1] in ('--help', '-h'):
                print("Usage:")
                print("  --parse_json <json_string>    Parse configuration from JSON string")
                print("  --parse_toml <toml_string>    Parse configuration from TOML string")
                print("  --parse_yaml <yaml_string>    Parse configuration from YAML string")
                print("  --config_path <file_path>     Parse configuration from file (supports .json, .toml, .yaml, .yml)")
                print("  --from_web                    Run configuration in web mode")
                sys.exit(0)
            elif sys.argv[1] in ('--from_web', '--from-web'):
                print('Running configuration in web mode...')
            else:
                raise ValueError("No command line arguments provided. Use --help for usage information.")

        # assert len(sys.argv) >= 3, "Insufficient command line arguments, please refer to --help for usage information"
        config_type = sys.argv[1]

        if config_type == '--parse_json':
            assert len(sys.argv) == 3, "JSON string must be provided as a command line argument"
            return cls.from_json(sys.argv[2], strict=strict)
        elif config_type == '--parse_toml':
            assert len(sys.argv) == 3, "TOML string must be provided as a command line argument"
            return cls.from_toml(sys.argv[2], strict=strict)
        elif config_type == '--parse_yaml':
            assert len(sys.argv) == 3, "YAML string must be provided as a command line argument"
            return cls.from_yaml(sys.argv[2], strict=strict)
        elif config_type == '--config_path':
            assert len(sys.argv) == 3, "Configuration file path must be provided as a command line argument"
            file_path = sys.argv[2]
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if file_path.lower().endswith('.json'):
                return cls.from_json(content, strict=strict)
            elif file_path.lower().endswith('.toml'):
                return cls.from_toml(content, strict=strict)
            elif file_path.lower().endswith(('.yaml', '.yml')):
                return cls.from_yaml(content, strict=strict)
            else:
                raise ValueError("Unsupported configuration file format. Supported formats: .json, .toml, .yaml, .yml")
        elif config_type == '--from_web':
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                tmp_path = temp_file.name
            cmd = f'streamlit run {__main__.__file__} web_mode {tmp_path}'
            web_proc = subprocess.Popen(cmd, shell=True)
            web_proc.wait()

            with open(tmp_path, 'r') as f:
                content = f.read()
            try:
                instance = cls.from_json(content, strict=strict)
            except Exception as e:
                raise Exception(f"Config from web failed! Error: {e}")

            # delete the temp file
            os.remove(tmp_path)

            return instance

        elif config_type == 'web_mode':
            assert is_running_in_streamlit(), ("Web mode can only be used by the program it self. You should never "
                                               "run it manually.")
            st.set_page_config(layout="wide")
            st.sidebar.markdown("## HyperArgs - Web")
            st.markdown("# Program Arguments")

            st.markdown(f"Please set the parameters in the table, then click **'Finish & Run'** to run the "
                                "program.")
            assert len(sys.argv) == 3, "Web mode file path must be provided as a command line argument"
            file_path = sys.argv[2]

            if 'previous_instance' in st.session_state:
                instance = st.session_state['previous_instance']
            else:
                instance = cls()

            for k in list(st.session_state.keys()):
                if not isinstance(k, str):
                    continue
                if k.startswith(f'_{ST_TAG}.'):
                    key = f"{ST_TAG}.{k.split('.')[-1]}"
                    st.session_state[key] = st.session_state[k]
                    del st.session_state[k]

            instance.build_widgets()
            settings = get_conf_dict_from_session()
            instance = instance.parse_dict(settings)

            st.markdown("## Current settings")
            left, mid, right = st.columns(3)
            left.markdown("**JSON**")
            left.code(
                body=instance.to_json(indent=2),
                language='json',
                line_numbers=True,
            )
            mid.markdown("**TOML**")
            try:
                mid.code(
                    body=instance.to_toml(),
                    language='toml',
                    line_numbers=True,
                )
            except Exception as e:
                st.error(f"Failed to generate TOML: {e}")
            right.markdown("**YAML**")
            try:
                right.code(
                    body=instance.to_yaml(),
                    language='yaml',
                    line_numbers=True,
                )
            except Exception as e:
                st.error(f"Failed to generate YAML: {e}")

            with open(file_path, 'w') as f:
                f.write(instance.to_json(indent=2))

            default_path = os.getcwd()
            save_path = st.sidebar.text_input("Input folder to save config file:", default_path)
            st.sidebar.selectbox(label='File format:', options=['JSON', 'TOML', 'YAML'], index=0, key='file_format')
            if st.sidebar.button("Save config"):
                if os.path.isdir(save_path):
                    file_name = os.path.join(
                        save_path, 
                        f"{instance.__class__.__name__}.{st.session_state['file_format'].lower()}"
                    )
                    instance.save_to_file(file_name)
                    st.sidebar.success(f"Config file has been saved to: {file_name}")
                else:
                    st.sidebar.error("Invalid path. Please enter a valid directory.")

            exit_app = st.sidebar.button("Finish & Run", help="Click to run the program with the current parameters.", type='primary')
            if exit_app:
                @st.dialog(title='Continue running in 5 seconds...')
                def end_program():
                    st.write("### The connection breaks in 5 seconds, you can now close this tab.")
                end_program()

                time.sleep(5)
                pid = os.getpid()
                p = psutil.Process(pid)
                p.terminate()

            st.session_state['previous_instance'] = instance

            gui_states = get_conf_dict_from_session()
            if is_dict_different(instance.to_dict(), gui_states):
                changed_values = find_chaned_values(gui_states, instance.to_dict())
                for k, v in changed_values.items():
                    st.session_state[f'_{ST_TAG}.{k}'] = v
                st.rerun()

            st.stop()
        else:
            raise ValueError("Unsupported command line argument. Use --parse_json, --parse_toml, --parse_yaml, or --config_path")

    def save_to_file(self, file_path: str) -> None:
        """Save the configuration to a file in the appropriate format based on the file extension."""
        content = ""
        if file_path.lower().endswith('.json'):
            content = self.to_json(indent=2)
        elif file_path.lower().endswith('.toml'):
            content = self.to_toml()
        elif file_path.lower().endswith(('.yaml', '.yml')):
            content = self.to_yaml()
        else:
            raise ValueError("Unsupported file format. Supported formats: .json, .toml, .yaml, .yml")

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.to_dict()})"

    def build_widgets(self) -> None:
        build_widgets(self)

CONF_ITEM = Union[Conf, Arg, List['CONF_ITEM']]

def build_widgets(item: CONF_ITEM, prefix: Optional[str] = None, container: Optional[DeltaGenerator] = None) -> None:
    if isinstance(item, Arg):
        assert prefix is not None and container is not None, "prefix and container must be provided for Arg"
        item.build_widget(key=prefix, container=container)
    elif isinstance(item, Conf):
        if container is None:
            next_contaier = st.container(border=True)
            next_contaier.write(prefix.split('.')[-1] if prefix is not None else item.__class__.__name__)
        else:
            next_contaier = container.container(border=True)
            next_contaier.write(prefix.split('.')[-1] if prefix is not None else item.__class__.__name__)
        for name in item.field_names():
            value = getattr(item, name)

            build_widgets(value, prefix=f"{prefix}.{name}" if prefix else name, container=next_contaier)
    elif isinstance(item, list):
        assert prefix is not None and container is not None, "prefix and container must be provided for list"
        next_container = container.container(border=True)
        next_container.write(prefix.split('.')[-1])
        for i, sub_item in enumerate(item):
            build_widgets(sub_item, prefix=f"{prefix}.[{i}]", container=next_container)
    else:
        raise TypeError(f"Unsupported type: {type(item)}")

def update_widgets(settings: JSON, prefix: Optional[str] = None) -> None:
    """Update the widgets according to the settings."""
    if prefix is None:
        prefix = ST_TAG
    if isinstance(settings, dict):
        for name, value in settings.items():
            update_widgets(value, prefix=f"{prefix}.{name}")
    elif isinstance(settings, list):
        for i, item in enumerate(settings):
            update_widgets(item, prefix=f"{prefix}.[{i}]")
    else:
        if prefix in st.session_state and st.session_state[prefix] != settings:
            st.session_state[prefix] = settings

def _to_json_dict(value: Union[Arg, Conf, list]) -> JSON:
    if isinstance(value, Arg):
        return value.value()
    elif isinstance(value, Conf):
        return value.to_dict()
    elif isinstance(value, (list, tuple)):
        return [_to_json_dict(v) for v in value]
    else:
        raise TypeError(f"Unsupported type: {type(value)}")

def _parse_attr(value: JSON, attr: Union[Arg, Conf, list]) -> Union[Arg, Conf, list]:
    if isinstance(attr, Arg):
        return attr.parse(value)
    elif isinstance(attr, Conf):
        assert isinstance(value, dict), f"Expected dict for Conf attribute, got {type(value)}"
        return attr.from_dict(value)
    elif isinstance(attr, (list, tuple)):
        assert isinstance(value, (list, tuple)), f"Expected list/tuple for attribute, got {type(value)}"
        # assert len(value) <= len(attr), f"Length of value and attribute list must match, but got {len(value)} and {len(attr)}"
        result = [_parse_attr(v, a) for v, a in zip(value, attr)]
        if len(attr) > len(value):
            result.extend([copy.deepcopy(a) for a in attr[len(value):]])
        return result
    else:
        raise TypeError(f"Unsupported attribute type: {type(attr)}")

def _update_parse_attr(value: JSON, attr: Union[Arg, Conf, list]) -> Union[Arg, Conf, list]:
    if isinstance(attr, Arg):
        return attr.parse(value)
    elif isinstance(attr, Conf):
        assert isinstance(value, dict), f"Expected dict for Conf attribute, got {type(value)}"
        return attr.parse_dict(value)
    elif isinstance(attr, (list, tuple)):
        assert isinstance(value, (list, tuple)), f"Expected list/tuple for attribute, got {type(value)}"
        # assert len(value) <= len(attr), f"Length of value and attribute list must match, but got {len(value)} and {len(attr)}"
        result = [_update_parse_attr(v, a) for v, a in zip(value, attr)]
        if len(attr) > len(value):
            result.extend([copy.deepcopy(a) for a in attr[len(value):]])
        return result
    else:
        raise TypeError(f"Unsupported attribute type: {type(attr)}")

def add_dependency(parent: str, child: str) -> Callable[[Type[C]], Type[C]]:
    """Add a dependency relationship from parent to child in the graph."""
    def decorator(cls: Type[C]) -> Type[C]:
        assert isinstance(cls._dep_graph, nx.DiGraph), "_dep_graph must be a networkx DiGraph"
        assert parent != child, "Parent and child cannot be the same"
        assert not nx.has_path(cls._dep_graph, child, parent), (f"Adding dependency from '{parent}' to '{child}' "
                                                                "would create a conf dependency cycle")
        assert hasattr(cls, parent), f"Parent attribute '{parent}' does not exist in class '{cls.__name__}'"
        assert hasattr(cls, child), f"Child attribute '{child}' does not exist in class '{cls.__name__}'"
        assert not cls._dep_graph.has_edge(parent, child), f"Dependency from '{parent}' to '{child}' already exists"

        cls._dep_graph.add_edge(parent, child)
        return cls
    return decorator

def monitor_on(depend_fields: Union[str, List[str]]) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator to monitor changes on specified fields."""
    if isinstance(depend_fields, str):
        depend_fields = [depend_fields]

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        setattr(func, '_monitor_on', depend_fields)
        return func

    return decorator
