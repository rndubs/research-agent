"""Sourcing interfaces: incremental paper sources and metadata enrichers.

Stage 1 harvests new papers from a primary :class:`PaperSource` (arXiv) and then
enriches each through zero or more :class:`Enricher` s (Semantic Scholar,
OpenAlex). The sourcing layer is deliberately abstracted so a provider can be
swapped if it disappears (the Papers With Code shutdown is the cautionary tale).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterator, Optional

from ..models import Paper


class PaperSource(ABC):
    """A primary, incrementally-harvestable source of papers."""

    name: str = "source"

    @abstractmethod
    def harvest(
        self,
        *,
        since: Optional[datetime] = None,
        max_results: int = 200,
    ) -> Iterator[Paper]:
        """Yield papers created/updated since ``since`` (newest-first is fine).

        Implementations persist nothing; Stage 1 owns persistence and dedup.
        Papers are returned with ``status=SEEN`` and whatever bibliographic
        fields the source provides.
        """


class Enricher(ABC):
    """Augments a :class:`Paper` in place with extra metadata."""

    name: str = "enricher"

    @abstractmethod
    def enrich(self, paper: Paper) -> Paper:
        """Return ``paper`` with additional fields populated (citations, refs, ...).

        Must be tolerant of missing coverage (return the paper unchanged rather
        than raising when the provider has no record).
        """

    def enrich_batch(self, papers: list[Paper]) -> list[Paper]:
        return [self.enrich(p) for p in papers]
