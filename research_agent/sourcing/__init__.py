"""Stage 1 (Sourcing): harvest, dedup, prefilter, enrich, persist.

:func:`stage1_source` is the stage entry point the orchestrator calls. It pulls
new arXiv papers since the last harvest cursor via :class:`ArxivSource`, drops
ones already stored (idempotency) and — when enabled — obvious off-domain ones
via the shared keyword prefilter, then best-effort enriches the survivors with
Semantic Scholar and OpenAlex before upserting them as ``status=SEEN``. Every
external call degrades gracefully so a dead provider never fails a run.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from ..config import Config
from ..db import Database
from ..filters import keyword_prefilter
from ..http import HttpClient
from ..models import Paper, PaperStatus, utcnow
from .arxiv_source import ArxivSource
from .base import Enricher, PaperSource
from .openalex import OpenAlexEnricher
from .semantic_scholar import SemanticScholarEnricher

logger = logging.getLogger(__name__)

__all__ = [
    "PaperSource",
    "Enricher",
    "ArxivSource",
    "SemanticScholarEnricher",
    "OpenAlexEnricher",
    "stage1_source",
]


def _build_enrichers(config: Config, http: HttpClient) -> list[Enricher]:
    """Assemble the configured enrichers (S2 then OpenAlex)."""
    enrichers: list[Enricher] = []
    if config.sourcing.use_semantic_scholar:
        api_key = os.environ.get(config.sourcing.semantic_scholar_key_env)
        enrichers.append(SemanticScholarEnricher(http, api_key=api_key))
    if config.sourcing.use_openalex:
        enrichers.append(OpenAlexEnricher(http))
    return enrichers


def stage1_source(
    config: Config,
    db: Database,
    http: HttpClient,
    *,
    since: datetime | None = None,
) -> list[Paper]:
    """Harvest, filter, enrich, and persist new papers; return the new ones."""
    since = since or db.get_last_harvest()

    source = ArxivSource(http, config.sourcing.arxiv_categories, config.sourcing.oai_set)

    new_papers: list[Paper] = []
    harvested = 0
    skipped_existing = 0
    prefiltered = 0
    max_published: datetime | None = None

    for paper in source.harvest(since=since, max_results=config.sourcing.max_results_per_run):
        harvested += 1
        if paper.published is not None and (
            max_published is None or paper.published > max_published
        ):
            max_published = paper.published

        if db.has_paper(paper.id):
            skipped_existing += 1
            continue

        if config.sourcing.harvest_prefilter:
            passed, _score, _matched = keyword_prefilter(paper, config)
            if not passed:
                prefiltered += 1
                continue

        new_papers.append(paper)

    # Best-effort enrichment of the survivors only.
    enrichers = _build_enrichers(config, http)
    for i, paper in enumerate(new_papers):
        for enricher in enrichers:
            try:
                paper = enricher.enrich(paper)
            except Exception as exc:  # enrichers self-guard, but never crash a run
                logger.warning("enricher %s failed for %s: %s", enricher.name, paper.id, exc)
        paper.status = PaperStatus.SEEN
        paper.updated_at = utcnow()
        db.upsert_paper(paper)
        new_papers[i] = paper

    db.set_last_harvest(max_published or utcnow())
    db.log(
        "stage1_source",
        {
            "harvested": harvested,
            "new": len(new_papers),
            "skipped_existing": skipped_existing,
            "prefiltered_out": prefiltered,
        },
    )
    return new_papers
