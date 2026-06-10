from __future__ import annotations

import importlib
import inspect
import pkgutil

import ztb.strategies
from ztb.strategies.base import Strategy

_registry: dict[str, type[Strategy]] = {}
_REGISTRY = _registry


def register(cls: type[Strategy]) -> type[Strategy]:
    name = cls.name
    if name in _registry and _registry[name] is not cls:
        raise ValueError(f"Strategy '{name}' is already registered")
    _registry[name] = cls
    return cls


def _discover() -> None:
    from inspect import isabstract, isclass

    base = Strategy
    prefix = ztb.strategies.__name__ + "."
    for _finder, name, _ispkg in pkgutil.iter_modules(ztb.strategies.__path__, prefix):
        _module = importlib.import_module(name)
        for obj_name, obj_type in inspect.getmembers(_module, isclass):
            if obj_name == "Strategy" or not issubclass(obj_type, base) or isabstract(obj_type):
                continue
            s_name: str = getattr(obj_type, "name", obj_name)
            dup = _registry.get(s_name)
            if dup is not None and dup is not obj_type:
                raise ValueError(
                    f"Duplicate strategy name '{s_name}' from "
                    f"{dup.__module__} and {obj_type.__module__}"
                )
            _registry[s_name] = obj_type


def get(name: str) -> type[Strategy]:
    if not _registry:
        _discover()
    if name not in _registry:
        available = ", ".join(sorted(_registry))
        raise KeyError(f"Unknown strategy '{name}'. Available: {available}")
    return _registry[name]


def all() -> list[type[Strategy]]:
    if not _registry:
        _discover()
    return list(_registry.values())


def list_names() -> list[str]:
    if not _registry:
        _discover()
    return sorted(_registry)
