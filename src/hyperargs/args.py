# -*- coding: utf-8 -*-
# File: src/hyperargs/args.py
'''
This module defines various argument types for hyperparameter management.
'''

from typing import Any, Optional, TypeVar, Set, Generic
import os

T = TypeVar("T")


class Arg(Generic[T]):
    ''' Base class for all argument types. '''
    _value: Optional[T]
    _allow_none: bool
    _env_bind: Optional[str]

    def value(self) -> Optional[T]:
        raise NotImplementedError(f'Please implement value method for {self.__class__.__name__}')

    def parse(self, value: Any) -> Optional[T]:
        raise NotImplementedError(f'Please implement parse method for {self.__class__.__name__}')

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(value={self._value}, allow_none={self._allow_none})"

    def __str__(self) -> str:
        return str(self._value)


class IntArg(Arg[int]):
    ''' An argument that takes an integer value. '''
    def __init__(
        self, 
        default: Optional[int], 
        min_value: Optional[int] = None, 
        max_value: Optional[int] = None,
        allow_none: bool = False,
        env_bind: Optional[str] = None
    ):
        self._value = default
        self._min_value = min_value
        self._max_value = max_value
        self._allow_none = allow_none
        self._env_bind = env_bind

        if not allow_none:
            assert self._value is not None, "Default value cannot be None if allow_none is False"
        assert (self._min_value is None or self._max_value is None or self._min_value <= self._max_value), \
            "min_value cannot be greater than max_value"
        assert (self._value is None or self._min_value is None or self._value >= self._min_value), \
            "Value cannot be less than min_value"
        assert (self._value is None or self._max_value is None or self._value <= self._max_value), \
            "Value cannot be greater than max_value"

        if self._env_bind is not None:
            env_value = os.getenv(self._env_bind)
            if env_value is not None:
                self.parse(env_value)

    def value(self) -> Optional[int]:
        return self._value

    def parse(self, value: Any) -> Optional[int]:
        if isinstance(value, str):
            if value.lower().strip() in ('none', 'null'):
                value = None
        if value is None:
            if self._allow_none:
                raise ValueError("Value cannot be None")
            else:
                self._value = value
                return self._value

        try:
            value = int(value)
        except ValueError:
            raise ValueError(f"Cannot convert {value} to int")

        if self._min_value is not None and value < self._min_value:
            raise ValueError(f"Value {value} is less than minimum {self._min_value}")
        if self._max_value is not None and value > self._max_value:
            raise ValueError(f"Value {value} is greater than maximum {self._max_value}")

        self._value = value
        return value

    def __repr__(self) -> str:
        return f"IntArg(value={self._value}, min_value={self._min_value}, max_value={self._max_value}, allow_none={self._allow_none})"


class FloatArg(Arg[float]):
    ''' An argument that takes a float value. '''
    def __init__(
        self, 
        default: Optional[float], 
        min_value: Optional[float] = None, 
        max_value: Optional[float] = None,
        allow_none: bool = False,
        env_bind: Optional[str] = None
    ):
        self._value = default
        self._min_value = min_value
        self._max_value = max_value
        self._allow_none = allow_none
        self._env_bind = env_bind

        if not allow_none:
            assert self._value is not None, "Default value cannot be None if allow_none is False"
        assert (self._min_value is None or self._max_value is None or self._min_value <= self._max_value), \
            "min_value cannot be greater than max_value"
        assert (self._value is None or self._min_value is None or self._value >= self._min_value), \
            "Value cannot be less than min_value"
        assert (self._value is None or self._max_value is None or self._value <= self._max_value), \
            "Value cannot be greater than max_value"

        if self._env_bind is not None:
            env_value = os.getenv(self._env_bind)
            if env_value is not None:
                self.parse(env_value)

    def value(self) -> Optional[float]:
        return self._value

    def parse(self, value: Any) -> Optional[float]:
        if isinstance(value, str):
            if value.lower().strip() in ('none', 'null'):
                value = None
        if value is None:
            if self._allow_none:
                raise ValueError("Value cannot be None")
            else:
                self._value = value
                return self._value

        try:
            value = float(value)
        except ValueError:
            raise ValueError(f"Cannot convert {value} to float")

        if self._min_value is not None and value < self._min_value:
            raise ValueError(f"Value {value} is less than minimum {self._min_value}")
        if self._max_value is not None and value > self._max_value:
            raise ValueError(f"Value {value} is greater than maximum {self._max_value}")

        self._value = value
        return value

    def __repr__(self) -> str:
        return f"FloatArg(value={self._value}, min_value={self._min_value}, max_value={self._max_value}, allow_none={self._allow_none})"


class StrArg(Arg[str]):
    ''' An argument that takes a string value. '''
    def __init__(self, default: Optional[str], allow_none: bool = False, env_bind: Optional[str] = None):
        self._value = default
        self._allow_none = allow_none
        self._env_bind = env_bind
        if not allow_none:
            assert self._value is not None, "Default value cannot be None if allow_none is False"

        if self._env_bind is not None:
            env_value = os.getenv(self._env_bind)
            if env_value is not None:
                self.parse(env_value)

    def value(self) -> Optional[str]:
        return self._value

    def parse(self, value: Any) -> Optional[str]:
        if isinstance(value, str):
            if value.lower().strip() in ('none', 'null'):
                value = None
        if value is None:
            if self._allow_none:
                raise ValueError("Value cannot be None")
            else:
                self._value = value
                return self._value

        try:
            value = str(value)
        except ValueError:
            raise ValueError(f"Cannot convert {value} to str")
        self._value = value
        return value


class BoolArg(Arg[bool]):
    ''' An argument that can take boolean values. '''
    def __init__(self, default: Optional[bool], allow_none: bool = False, env_bind: Optional[str] = None):
        self._value = default
        self._allow_none = allow_none
        self._env_bind = env_bind
        if not allow_none:
            assert self._value is not None, "Default value cannot be None if allow_none is False"

        if self._env_bind is not None:
            env_value = os.getenv(self._env_bind)
            if env_value is not None:
                self.parse(env_value)

    def value(self) -> Optional[bool]:
        return self._value

    def parse(self, value: Any) -> Optional[bool]:
        if isinstance(value, str):
            if value.lower().strip() in ('none', 'null'):
                value = None
        if value is None:
            if self._allow_none:
                raise ValueError("Value cannot be None")
            else:
                self._value = value
                return self._value

        if isinstance(value, str):
            if value.lower() in ('true', '1', 'yes'):
                value = True
            elif value.lower() in ('false', '0', 'no'):
                value = False
            else:
                raise ValueError(f"Cannot convert {value} to bool")

        try:
            value = bool(value)
        except ValueError:
            raise ValueError(f"Cannot convert {value} to bool")
        self._value = value
        return value


class OptionArg(Arg[str]):
    ''' An argument that can take one of a predefined set of string options. '''
    def __init__(
        self, 
        default: Optional[str], 
        options: Set[str], 
        allow_none: bool = False, 
        env_bind: Optional[str] = None
    ):
        self._value = default
        self._options = options
        self._allow_none = allow_none
        self._env_bind = env_bind
        if not allow_none:
            assert self._value is not None, "Default value cannot be None if allow_none is False"
        if self._value is not None:
            assert self._value in self._options, f"Default value {self._value} must be in options {self._options}"
        assert len(self._options) > 0, "Options set cannot be empty"

        if self._env_bind is not None:
            env_value = os.getenv(self._env_bind)
            if env_value is not None:
                self.parse(env_value)

    def value(self) -> Optional[str]:
        return self._value

    def parse(self, value: Any) -> Optional[str]:
        if isinstance(value, str):
            if value.lower().strip() in ('none', 'null'):
                value = None
        if value is None:
            if self._allow_none:
                raise ValueError("Value cannot be None")
            else:
                self._value = value
                return self._value

        try:
            value = str(value)
        except ValueError:
            raise ValueError(f"Cannot convert {value} to str")

        if value not in self._options:
            raise ValueError(f"Value {value} is not in options {self._options}")

        self._value = value
        return value

    def __repr__(self) -> str:
        return f"OptionArg(value={self._value}, options={self._options}, allow_none={self._allow_none})"
