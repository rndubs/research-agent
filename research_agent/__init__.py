"""research-agent: an ongoing arXiv research monitor.

Turns a broad, incrementally-harvested paper corpus into a prioritized,
deduplicated backlog for a *narrow* ML research problem, using a scheduled
five-stage funnel (source -> filter -> extract -> score -> deliver) with LLM
behavior confined to bounded sub-tasks (relevance judging, claim extraction,
effort/impact estimation).

See ``docs/ARCHITECTURE.md`` for the design and ``docs/CONTRACTS.md`` for the
module boundaries every component is built against.
"""

__version__ = "0.1.0"
