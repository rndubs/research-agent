"""Anthropic Claude implementation of :class:`LLMClient`.

Schema-constrained ``structured`` output is done with *forced tool use*: the
pydantic schema is turned into a tool input schema and the model is required to
call it, so the returned object is always valid JSON matching the schema (with a
pydantic validation + one recovery pass as a backstop). The SDK import is lazy
so the base package installs without ``anthropic``.
"""

from __future__ import annotations

import json
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import LLMConfig
from .base import LLMClient, T, build_stub


class AnthropicLLM(LLMClient):
    def __init__(self, config: LLMConfig, api_key: str | None = None) -> None:
        import os

        import anthropic  # lazy

        key = api_key or os.environ.get(config.api_key_env)
        if not key:
            raise RuntimeError(
                f"No Anthropic API key in ${config.api_key_env}; use provider='mock' for offline runs."
            )
        self.config = config
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=key)

    # -- retry policy for transient overload/rate errors ------------------ #
    def _retryable(self) -> tuple[type[Exception], ...]:
        a = self._anthropic
        return tuple(
            e
            for e in (
                getattr(a, "APIConnectionError", None),
                getattr(a, "RateLimitError", None),
                getattr(a, "InternalServerError", None),
                getattr(a, "APITimeoutError", None),
            )
            if e is not None
        )

    def _create(self, **kwargs: Any) -> Any:
        @retry(
            reraise=True,
            stop=stop_after_attempt(4),
            wait=wait_exponential(multiplier=1, min=2, max=20),
            retry=retry_if_exception_type(self._retryable()),
        )
        def _call() -> Any:
            return self.client.messages.create(**kwargs)

        return _call()

    # -- LLMClient -------------------------------------------------------- #
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        cache_key: str | None = None,  # unused: direct API needs no request key
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": model or self.config.relevance_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        resp = self._create(**kwargs)
        return "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )

    def structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
        cache_key: str | None = None,  # unused: direct API needs no request key
    ) -> T:
        tool_name = _tool_name(schema)
        tool = {
            "name": tool_name,
            "description": (schema.__doc__ or f"Return a {schema.__name__}.").strip(),
            "input_schema": _json_schema(schema),
        }
        kwargs: dict[str, Any] = {
            "model": model or self.config.extraction_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": tool_name},
        }
        if system:
            kwargs["system"] = system
        resp = self._create(**kwargs)
        payload = _first_tool_input(resp)
        try:
            return schema.model_validate(payload)
        except Exception:
            # Recovery: ask the model to repair its own output into valid JSON.
            repaired = self._repair(payload, schema, model=model)
            if repaired is not None:
                return repaired
            return build_stub(schema)

    def _repair(self, payload: Any, schema: type[T], model: str | None) -> T | None:
        try:
            fix_prompt = (
                "The following JSON must conform to the tool schema exactly but failed "
                "validation. Return a corrected version.\n\n" + json.dumps(payload, default=str)
            )
            tool_name = _tool_name(schema)
            resp = self._create(
                model=model or self.config.extraction_model,
                max_tokens=2048,
                temperature=0.0,
                messages=[{"role": "user", "content": fix_prompt}],
                tools=[
                    {
                        "name": tool_name,
                        "description": (schema.__doc__ or schema.__name__).strip(),
                        "input_schema": _json_schema(schema),
                    }
                ],
                tool_choice={"type": "tool", "name": tool_name},
            )
            return schema.model_validate(_first_tool_input(resp))
        except Exception:
            return None


def _tool_name(schema: type[Any]) -> str:
    # Tool names must match ^[a-zA-Z0-9_-]+$.
    return f"emit_{schema.__name__}"


def _json_schema(schema: type[Any]) -> dict[str, Any]:
    js = schema.model_json_schema()
    js.pop("title", None)
    return js


def _first_tool_input(resp: Any) -> Any:
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            return block.input
    raise ValueError("Model returned no tool_use block")
