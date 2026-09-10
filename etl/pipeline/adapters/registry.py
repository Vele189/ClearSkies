"""The list of sources the pipeline knows about.

Registration is what "adding a sixth source is a contained change" means in
practice: a new module, one decorator, and the nightly job picks it up. Nothing
else in the pipeline enumerates sources.
"""

import re
from typing import Any

from pipeline.adapters.base import SourceAdapter
from pipeline.metadata import SourceSpec

REGISTRY: dict[str, type[SourceAdapter[Any]]] = {}

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def register[AdapterType: type[SourceAdapter[Any]]](cls: AdapterType) -> AdapterType:
    """Class decorator. Adds an adapter to the registry under `spec.name`."""
    spec = getattr(cls, "spec", None)
    if not isinstance(spec, SourceSpec):
        raise TypeError(f"{cls.__name__} must declare a SourceSpec as `spec`")
    if not _NAME.match(spec.name):
        raise ValueError(f"{spec.name!r} must be lowercase with underscores")
    existing = REGISTRY.get(spec.name)
    if existing is not None and existing is not cls:
        raise ValueError(f"{spec.name!r} is already registered to {existing.__name__}")
    REGISTRY[spec.name] = cls
    return cls


def get(name: str) -> type[SourceAdapter[Any]]:
    try:
        return REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(REGISTRY)) or "none"
        raise KeyError(f"unknown source {name!r}; registered: {known}") from None


def names() -> tuple[str, ...]:
    return tuple(sorted(REGISTRY))


def specs() -> tuple[SourceSpec, ...]:
    return tuple(REGISTRY[name].spec for name in names())
