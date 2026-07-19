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

    def __init__(self) -> None:
        """Materialize monitor-derived defaults.

        Monitors only run from ``__setattr__``, so a field whose value comes
        from another field's default used to stay unresolved until that other
        field was explicitly assigned. A config file that simply omitted a
        field equal to its default therefore lost whatever the monitor would
        have built — most visibly, a nested Conf swapped in by an OptionArg
        stayed a bare ``Conf`` and every key parsed against it was discarded.

        Firing each monitor once here, in dependency order, means a freshly
        constructed Conf is already in the state the declared defaults imply.
        Monitors are expected to be idempotent (they are re-run on every
        assignment to the field they watch).
        """
        super().__init__()
        fired: Set[str] = set()
        for name in nx.topological_sort(self._dep_graph):
            for monitor in self._monitors.get(name, ()):  # type: ignore[arg-type]
                if monitor in fired:
                    continue
                method = getattr(self, monitor, None)
                if callable(method):
                    fired.add(monitor)
                    try:
                        method()
                    except Exception as e:
                        # a monitor that cannot run against the declared
                        # defaults is the author's bug, but it must not make
                        # the class unconstructible — it will run again as
                        # soon as the field it watches is assigned
                        logger.warning(
                            f"monitor '{monitor}' failed while materializing "
                            f"defaults for {type(self).__name__}: {e}"
                        )

    @staticmethod
    def check_conf_type(value: Any) -> bool:
        if isinstance(value, Arg):
            return True
        if isinstance(value, (list, tuple)):    # the parse path accepts both
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
        # Assigning a raw value over a declared field (forgetting `.parse()`)
        # used to succeed and only fail much later, inside to_dict() — often
        # after the job had already started. Reject it where it happens.
        if not name.startswith('_') and name in self._dep_graph:
            if not self.check_conf_type(value):
                raise TypeError(
                    f"field '{name}' must hold an Arg, Conf, or list of them, "
                    f"got {value!r} ({type(value).__name__}) — did you mean "
                    f"self.{name} = self.{name}.parse(...)?"
                )
        super().__setattr__(name, value)
        if name in self._monitors:
            for monitor in self._monitors[name]:
                if hasattr(self, monitor):
                    method = getattr(self, monitor)
                    if callable(method):
                        method()

        # NOTE: deliberately does NOT register new nodes on the class-level
        # dependency graph. Doing so let every attribute ever set on any
        # instance (including private bookkeeping) leak into the graph shared
        # by the class and its future subclasses, and a node with no matching
        # class attribute made the next from_dict raise AttributeError.

    @classmethod
    def from_dict(cls: Type[C], data: Dict[str, JSON], strict: bool = False) -> C:
        """Create a configuration instance from a dictionary."""
        return cls().parse_dict(data, strict=strict)

    def parse_dict(self, data: Dict[str, JSON], strict: bool = False) -> Self:
        """Parse a dictionary into this instance.

        Fields are parsed in dependency order, and then anything a monitor
        INVALIDATED along the way is parsed again.

        A monitor firing while a later field is parsed can replace an
        attribute that has already been parsed. Two different things look like
        that, and they want opposite outcomes:

          * the monitor swapped the field for a different TYPE — an OptionArg
            selecting which Conf subclass a nested block is. The file's values
            went into an object that no longer exists, so they have to be
            parsed again into the new one. This is what a dependency declared
            in the wrong direction produces.
          * the monitor RECOMPUTED a value of the same type — a field derived
            from another one. Here the monitor is the authority; re-applying
            the file would resurrect a stale value, and since ``to_dict``
            writes derived fields back out, every saved-then-edited config
            carries one.

        Type identity (plus length, for lists) separates the two.
        """
        data_ = copy.deepcopy(data)
        raw = {name: copy.deepcopy(v) for name, v in data_.items()}
        sigs: Dict[str, tuple] = {}

        for name in nx.topological_sort(self._dep_graph):
            if name in data_:
                # The INSTANCE attribute, not the class one: a monitor may
                # already have swapped this attribute for another type, and
                # the class default no longer describes what we parse into.
                # Not strict yet — a field a monitor is about to rebuild is
                # parsed here against a placeholder, and validating that
                # intermediate state reports the real subclass's own fields as
                # unexpected.
                attr = getattr(self, name)
                setattr(self, name, _parse_attr(data_[name], attr, strict=False, field=name))
                sigs[name] = _shape_of(getattr(self, name))
                data_.pop(name)

        stale: List[str] = []
        for _ in range(_MAX_REPAIR_ROUNDS):
            stale = [n for n, s in sigs.items()
                     if _shape_changed(s, _shape_of(getattr(self, n)))]
            if not stale:
                break
            for name in stale:
                _warn_rebuilt_once(type(self), name)
                setattr(self, name,
                        _parse_attr(copy.deepcopy(raw[name]), getattr(self, name),
                                    strict=False, field=name))
                sigs[name] = _shape_of(getattr(self, name))
        else:
            # never leave silently: fields still being rebuilt after this many
            # rounds are holding values parsed against an object that no
            # longer exists
            unsettled = [n for n, s in sigs.items()
                         if _shape_changed(s, _shape_of(getattr(self, n)))]
            if unsettled:
                raise RuntimeError(
                    f"{type(self).__name__}: fields {sorted(unsettled)} are "
                    f"still being rebuilt by monitors after "
                    f"{_MAX_REPAIR_ROUNDS} passes; the declared dependencies "
                    f"do not describe the real ones"
                )

        if strict:
            # Strict mode is about unknown FIELDS, not about values — values
            # were already validated as they were parsed. Re-parsing them here
            # would reject input that is legal for the object the monitors
            # eventually built but not for the one it was first parsed into
            # (a monitor that tightens a bound), so strict=True would refuse a
            # config that strict=False accepts and gets right. It would also
            # re-fire nested monitors for a result we throw away.
            for name in sigs:
                _check_unknown_keys(raw[name], getattr(self, name), name)

        if strict and data_:
            raise ValueError(f"Unexpected fields in data: {list(data_.keys())}")
        elif data_:
            logger.warning(f"Ignored unexpected fields in data: {list(data_.keys())}")

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

def _check_list_len(value: Union[list, tuple], attr: Union[list, tuple],
                    field: str = '') -> None:
    """Report a config list whose length disagrees with the declared field.

    The two directions are not symmetric. A list LONGER than declared loses
    what the user wrote — ``zip`` dropped the surplus silently, so adding a
    data source without bumping its count field quietly changed the training
    mixture — so it raises. A SHORTER list is padded with the declared
    defaults, which is recoverable but still worth saying out loud: with a
    weights list whose default is 1.0, supplying 7 weights for 8 sources
    leaves the eighth at 1.0 and hands it roughly half the mixture.
    """
    where = f"field '{field}': " if field else ''
    if len(value) > len(attr):
        raise ValueError(
            f"{where}got {len(value)} items for a field declared with "
            f"{len(attr)}; the surplus would be silently dropped — fix the "
            f"count field or the list"
        )
    if len(value) < len(attr):
        padded = [_summarize(a) for a in attr[len(value):]]
        logger.warning(
            f"{where}got {len(value)} items for a field declared with "
            f"{len(attr)}; the remaining {len(attr) - len(value)} keep their "
            f"defaults ({', '.join(padded)})"
        )


def _summarize(attr: Any) -> str:
    try:
        return repr(attr.value())
    except Exception:
        return type(attr).__name__


_MAX_REPAIR_ROUNDS = 3
_rebuild_warned: Set[tuple] = set()


def _shape_of(value: Any) -> tuple:
    """A signature that changes exactly when already-parsed file values stop
    being meaningful.

    For an ``Arg`` that is its type: an Arg of the same type holding a new
    number is a monitor RECOMPUTING a derived value, and the monitor is the
    authority there.

    For a ``Conf`` it is the object ITSELF, not just its class and not its
    id(). A monitor that hands back a fresh instance — swapping a subclass, or
    resetting the block — put the user's parsed values in an object nobody
    holds any more, and that is true whether or not the class changed. (A
    monitor that edits the nested block in place keeps the same object, so its
    edits and the file's values merge as they should.)

    The object is kept rather than its address because CPython recycles
    addresses: a monitor that assigns the field twice frees the original on
    the first assignment, and the second allocation lands on the freed
    address — an id() signature then compares equal to the one taken before
    the monitor ran, and the repair is skipped. Holding the reference makes
    that impossible.

    For a list, its length and the signatures of its elements: a monitor that
    swaps every element for a different source type keeps type and length
    identical while making every parsed element meaningless.
    """
    if isinstance(value, (list, tuple)):
        return (type(value), len(value), tuple(_shape_of(v) for v in value))
    if isinstance(value, Conf):
        return (type(value), value)
    return (type(value),)


def _shape_changed(old: tuple, new: tuple) -> bool:
    """Compare two signatures. Conf slots compare by identity explicitly, so a
    subclass that defines __eq__ cannot make a replaced object look unchanged.
    """
    if len(old) != len(new):
        return True
    for a, b in zip(old, new):
        if isinstance(a, Conf) or isinstance(b, Conf):
            if a is not b:
                return True
        elif isinstance(a, tuple) and isinstance(b, tuple):
            if _shape_changed(a, b):
                return True
        elif a is not b and a != b:
            return True
    return False


def _warn_rebuilt_once(cls: type, name: str) -> None:
    key = (cls, name)
    if key in _rebuild_warned:
        return          # once per class+field, not once per parse
    _rebuild_warned.add(key)
    logger.warning(
        f"field '{name}' of {cls.__name__} is rebuilt by a monitor after it "
        f"has been parsed, so it has to be parsed twice. Declare '{name}' as "
        f"the CHILD of the field whose monitor rebuilds it to avoid this."
    )


def _check_unknown_keys(value: JSON, attr: Any, path: str) -> None:
    """Recursively report keys the settled objects have no field for."""
    if isinstance(attr, Conf) and isinstance(value, dict):
        known = set(attr.field_names())
        unknown = [k for k in value if k not in known]
        if unknown:
            raise ValueError(f"Unexpected fields in data at '{path}': {unknown}")
        for k, v in value.items():
            _check_unknown_keys(v, getattr(attr, k), f'{path}.{k}')
    elif isinstance(attr, (list, tuple)) and isinstance(value, (list, tuple)):
        for i, (v, a) in enumerate(zip(value, attr)):
            _check_unknown_keys(v, a, f'{path}[{i}]')


def _parse_attr(value: JSON, attr: Union[Arg, Conf, list], strict: bool = False,
                field: str = '') -> Union[Arg, Conf, list]:
    if isinstance(attr, Arg):
        return attr.parse(value)
    elif isinstance(attr, Conf):
        assert isinstance(value, dict), f"Expected dict for Conf attribute, got {type(value)}"
        # Parse into a COPY of what is already there, never a fresh instance:
        # a monitor may have configured this nested block, and from_dict (a
        # classmethod) would discard all of it the moment the file mentioned
        # the block. The copy is what keeps parse_dict's in-place mutation
        # from rewriting a class default for every later instance.
        return copy.deepcopy(attr).parse_dict(value, strict=strict)
    elif isinstance(attr, (list, tuple)):
        assert isinstance(value, (list, tuple)), f"Expected list/tuple for attribute, got {type(value)}"
        _check_list_len(value, attr, field)
        result = [_parse_attr(v, a, strict=strict, field=field) for v, a in zip(value, attr)]
        if len(attr) > len(value):
            result.extend([copy.deepcopy(a) for a in attr[len(value):]])
        return result
    else:
        raise TypeError(f"Unsupported attribute type: {type(attr)}")


# The two parsers converged once nested Confs started parsing into a copy of
# the existing attribute; kept as an alias for callers outside this module.
_update_parse_attr = _parse_attr

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
