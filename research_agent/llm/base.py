"""LLM client interface and a schema-stub helper.

``structured`` is the load-bearing method: it forces the model to return an
instance of a flat pydantic schema (via provider tool-use / JSON mode) and
validates it, so downstream code never parses free-form text. Implementations
must validate against ``schema`` and should run a recovery pass on malformed
output before giving up.
"""

from __future__ import annotations

import enum
import types
import typing
from abc import ABC, abstractmethod
from typing import Any, Optional, TypeVar, get_args, get_origin

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClient(ABC):
    """Abstract LLM client. Two operations, both synchronous."""

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        """Return the model's free-text completion for ``prompt``."""

    @abstractmethod
    def structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> T:
        """Return a validated instance of ``schema`` produced by the model."""


def _default_for_annotation(ann: Any) -> Any:
    """Best-effort zero-value for a type annotation, for building valid stubs."""
    origin = get_origin(ann)

    # Optional[X] / Union -> None if allowed, else first arm.
    if origin in (typing.Union, getattr(types, "UnionType", None)):
        args = [a for a in get_args(ann) if a is not type(None)]
        if len(args) < len(get_args(ann)):
            return None
        return _default_for_annotation(args[0]) if args else None

    if origin in (list, typing.List):
        return []
    if origin in (dict, typing.Dict):
        return {}
    if origin in (tuple, typing.Tuple):
        return ()
    if origin in (set, frozenset):
        return set()

    if ann in (str,):
        return ""
    if ann in (int,):
        return 0
    if ann in (float,):
        return 0.0
    if ann in (bool,):
        return False

    if isinstance(ann, type):
        if issubclass(ann, enum.Enum):
            return list(ann)[0]
        if issubclass(ann, BaseModel):
            return build_stub(ann)
    return None


def build_stub(schema: type[T], **overrides: Any) -> T:
    """Construct a *valid* instance of ``schema`` with zero-ish defaults.

    Fields with model defaults keep them; required fields get a type-appropriate
    zero value. Handy for tests and for LLM output recovery. ``overrides`` set
    specific fields.
    """
    values: dict[str, Any] = {}
    for name, field in schema.model_fields.items():
        if name in overrides:
            values[name] = overrides[name]
            continue
        if field.is_required():
            values[name] = _default_for_annotation(field.annotation)
    values.update(overrides)
    return schema.model_validate(values)
