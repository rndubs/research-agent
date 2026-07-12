"""LLM client abstraction.

The pipeline confines LLM behavior to three bounded sub-tasks — relevance
judging, claim extraction, and effort/impact estimation — each of which asks for
a schema-constrained structured object. A :class:`~research_agent.llm.base.LLMClient`
exposes exactly two operations: free-text ``complete`` and schema-forced
``structured``.
"""

from __future__ import annotations

from ..config import LLMConfig
from .base import LLMClient, build_stub
from .mock import MockLLM

__all__ = ["LLMClient", "MockLLM", "build_stub", "get_llm"]


def get_llm(config: LLMConfig) -> LLMClient:
    """Factory: build the configured LLM client.

    ``provider='mock'`` (or a missing API key with ``anthropic``) yields a
    deterministic :class:`MockLLM` so the pipeline always runs offline.
    """
    import os

    if config.provider == "mock":
        return MockLLM()
    if config.provider == "anthropic":
        if not os.environ.get(config.api_key_env):
            # No key available — degrade gracefully rather than crash a run.
            return MockLLM()
        from .anthropic_client import AnthropicLLM

        return AnthropicLLM(config)
    raise ValueError(f"Unknown LLM provider: {config.provider!r}")
