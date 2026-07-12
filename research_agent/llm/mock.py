"""Deterministic mock LLM used everywhere in tests and for offline runs.

Configure it three ways (checked in order):

1. ``handler(kind, prompt, schema, system)`` — full control; return a str (for
   ``complete``) or a schema instance / dict (for ``structured``).
2. ``structured_responses[schema.__name__]`` — an instance, a dict, or a
   callable ``(prompt, schema) -> instance | dict``.
3. Fallback: a valid auto-built stub via :func:`build_stub`.

All calls are recorded on ``.calls`` for assertions.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from .base import LLMClient, T, build_stub


class MockLLM(LLMClient):
    def __init__(
        self,
        *,
        text_responses: dict[str, str] | Callable[[str], str] | None = None,
        structured_responses: dict[str, Any] | None = None,
        handler: Callable[..., Any] | None = None,
        default_text: str = "mock-response",
    ) -> None:
        self.text_responses = text_responses
        self.structured_responses = structured_responses or {}
        self.handler = handler
        self.default_text = default_text
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        self.calls.append({"kind": "complete", "prompt": prompt, "system": system})
        if self.handler is not None:
            out = self.handler("complete", prompt=prompt, schema=None, system=system)
            if out is not None:
                return str(out)
        if callable(self.text_responses):
            return self.text_responses(prompt)
        if isinstance(self.text_responses, dict):
            for key, val in self.text_responses.items():
                if key in prompt:
                    return val
        return self.default_text

    def structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> T:
        self.calls.append(
            {"kind": "structured", "prompt": prompt, "schema": schema.__name__, "system": system}
        )
        if self.handler is not None:
            out = self.handler("structured", prompt=prompt, schema=schema, system=system)
            if out is not None:
                return self._coerce(out, schema)

        resp = self.structured_responses.get(schema.__name__)
        if resp is not None:
            if callable(resp) and not isinstance(resp, BaseModel):
                resp = resp(prompt, schema)
            return self._coerce(resp, schema)

        return build_stub(schema)

    @staticmethod
    def _coerce(value: Any, schema: type[T]) -> T:
        if isinstance(value, schema):
            return value
        if isinstance(value, BaseModel):
            return schema.model_validate(value.model_dump())
        if isinstance(value, dict):
            return schema.model_validate(value)
        raise TypeError(f"Cannot coerce {type(value)} into {schema.__name__}")
