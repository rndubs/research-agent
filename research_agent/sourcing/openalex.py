"""OpenAlex enrichment: a second, DOI/title-keyed citation source.

OpenAlex has no arXiv-id endpoint, so :class:`OpenAlexEnricher` resolves a work
by DOI when one is known and otherwise falls back to a title search. It adds the
OpenAlex work id, folds topic/concept labels into ``fields_of_study``, back-fills
a citation count only when Semantic Scholar left it empty, and records open-access
status in ``paper.extra``. Every lookup tolerates a miss and returns the paper
unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from ..http import HttpClient
from ..models import Paper
from .base import Enricher

logger = logging.getLogger(__name__)

WORKS_URL = "https://api.openalex.org/works"
DOI_WORK_URL = "https://api.openalex.org/works/https://doi.org/{doi}"


class OpenAlexEnricher(Enricher):
    """Enrich a paper with OpenAlex work metadata (DOI- or title-resolved)."""

    name = "openalex"

    def __init__(self, http: HttpClient, mailto: str | None = None) -> None:
        self._http = http
        self.mailto = mailto

    def _params(self, **extra: Any) -> dict[str, Any]:
        params: dict[str, Any] = dict(extra)
        if self.mailto:
            params["mailto"] = self.mailto
        return params

    def enrich(self, paper: Paper) -> Paper:
        work = self._lookup(paper)
        if not isinstance(work, dict) or not work:
            return paper

        work_id = work.get("id")
        if work_id:
            paper.openalex_id = str(work_id)

        for label in self._concept_labels(work):
            if label not in paper.fields_of_study:
                paper.fields_of_study.append(label)

        if paper.citation_count is None:
            cited = work.get("cited_by_count")
            if isinstance(cited, int):
                paper.citation_count = cited

        oa = work.get("open_access")
        if isinstance(oa, dict) and "is_oa" in oa:
            paper.extra["open_access"] = bool(oa["is_oa"])

        return paper

    # -- resolution ------------------------------------------------------- #
    def _lookup(self, paper: Paper) -> dict[str, Any] | None:
        try:
            if paper.doi:
                doi = paper.doi.strip()
                # Accept either a bare DOI or a full doi.org URL.
                doi = doi.split("doi.org/", 1)[-1]
                data = self._http.get_json(
                    DOI_WORK_URL.format(doi=doi), params=self._params()
                )
                if isinstance(data, dict) and data.get("id"):
                    return data
            if paper.title:
                data = self._http.get_json(
                    WORKS_URL,
                    params=self._params(
                        filter=f"title.search:{paper.title}", per_page=1
                    ),
                )
                results = data.get("results") if isinstance(data, dict) else None
                if isinstance(results, list) and results:
                    return results[0]
        except Exception as exc:  # 404, 429, timeout, transport
            logger.info("OpenAlex enrich miss for %s: %s", paper.id, exc)
        return None

    @staticmethod
    def _concept_labels(work: dict[str, Any]) -> list[str]:
        """Collect distinct topic/concept display names from a work."""
        labels: list[str] = []
        for key in ("topics", "concepts"):
            items = work.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = item.get("display_name")
                if name and name not in labels:
                    labels.append(name)
        return labels
