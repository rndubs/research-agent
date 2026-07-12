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
    if config.provider == "batch":
        # Batch/agent-as-LLM mode can't run inside a single `pipeline.run()` call
        # (a subprocess can't call back up into the agent mid-loop). It is driven
        # by the two-phase `research-agent batch-plan` / `batch-apply` flow.
        raise ValueError(
            "provider='batch' is driven by `research-agent batch-plan` / `batch-apply`, "
            "not `run`. See docs/NIGHTLY.md."
        )
    raise ValueError(f"Unknown LLM provider: {config.provider!r}")
