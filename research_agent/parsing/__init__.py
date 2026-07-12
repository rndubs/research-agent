"""Full-text parsing: acquisition, HTML/TEI section extraction, chunking.

Stage 3 uses this package to turn a :class:`~research_agent.models.Paper` into a
:class:`~research_agent.models.FullText` (via ``fetch_fulltext``) and then into
extraction-sized :class:`~research_agent.models.Chunk`s (via ``chunk_sections``).
Everything degrades to an abstract-only path so the pipeline runs offline.
"""

from __future__ import annotations

from .chunk import chunk_sections
from .fulltext import fetch_fulltext, parse_html_sections
from .grobid import GrobidClient

__all__ = ["fetch_fulltext", "parse_html_sections", "GrobidClient", "chunk_sections"]
