from typing import Any, Dict, Union, Optional, Type, Callable, TypeVar, ParamSpec, Set, List
from collections import defaultdict
import copy
import json
import logging
import sys

import networkx as nx
import tomli
import tomli_w
import yaml

from .args import Arg, JSON

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
        data = copy.deepcopy(data)

        for name in nx.topological_sort(instance._dep_graph):
            if name in data:
                value = data[name]
                attr = getattr(cls, name)

                parsed_value = _parse_attr(value, attr)
                setattr(instance, name, parsed_value)

                data.pop(name)

        if strict and data:
            raise ValueError(f"Unexpected fields in data: {list(data.keys())}")
        elif data:
            logger.warning(f"Ignored unexpected fields in data: {list(data.keys())}")

        return instance

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
                sys.exit(0)
            else:
                raise ValueError("No command line arguments provided. Use --help for usage information.")

        assert len(sys.argv) >= 3, "Insufficient command line arguments, please refer to --help for usage information"
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
        assert len(value) == len(attr), "Length of value and attribute list must match"
        return [_parse_attr(v, a) for v, a in zip(value, attr)]
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
