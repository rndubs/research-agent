"""Semantic Scholar enrichment: citations, tldr, and reference edges.

:class:`SemanticScholarEnricher` looks a paper up by its arXiv id on the S2 Graph
API and folds citation counts, the tldr, fields of study, external ids, and a
capped list of reference ids into the :class:`Paper`. Coverage is imperfect and
brand-new preprints 404, so every failure mode returns the paper unchanged and
logs — an enricher must never crash a run.

:meth:`recommendations` is a best-effort call to the S2 recommendations API used
by later stages to expand the seed set; it returns minimal stubs and ``[]`` on
any failure.
"""

from __future__ import annotations

import logging
from typing import Any

from ..http import HttpClient
from ..models import Paper, PaperStatus
from .base import Enricher

logger = logging.getLogger(__name__)

GRAPH_PAPER_URL = "https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}"
RECOMMENDATIONS_URL = "https://api.semanticscholar.org/recommendations/v1/papers/"

_FIELDS = (
    "citationCount,influentialCitationCount,tldr,fieldsOfStudy,"
    "externalIds,references.externalIds"
)
_MAX_REFERENCES = 50


class SemanticScholarEnricher(Enricher):
    """Enrich a paper with Semantic Scholar graph metadata."""

    name = "semantic_scholar"

    def __init__(self, http: HttpClient, api_key: str | None = None) -> None:
        self._http = http
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key} if self.api_key else {}

    # -- enrichment ------------------------------------------------------- #
    def enrich(self, paper: Paper) -> Paper:
        url = GRAPH_PAPER_URL.format(arxiv_id=paper.id)
        try:
            data = self._http.get_json(
                url, params={"fields": _FIELDS}, headers=self._headers()
            )
        except Exception as exc:  # 404 for new ids, 429, timeouts, transport
            logger.info("S2 enrich miss for %s: %s", paper.id, exc)
            return paper

        if not isinstance(data, dict):
            return paper

        cc = data.get("citationCount")
        if isinstance(cc, int):
            paper.citation_count = cc
        icc = data.get("influentialCitationCount")
        if isinstance(icc, int):
            paper.influential_citation_count = icc

        tldr = data.get("tldr")
        if isinstance(tldr, dict) and tldr.get("text"):
            paper.tldr = tldr["text"]

        fos = data.get("fieldsOfStudy")
        if isinstance(fos, list):
            for field in fos:
                if field and field not in paper.fields_of_study:
                    paper.fields_of_study.append(field)

        external = data.get("externalIds")
        if isinstance(external, dict):
            corpus_id = external.get("CorpusId")
            if corpus_id is not None:
                paper.corpus_id = str(corpus_id)
            if not paper.doi and external.get("DOI"):
                paper.doi = external["DOI"]

        references = data.get("references")
        if isinstance(references, list):
            paper.reference_ids = self._reference_ids(references)

        return paper

    @staticmethod
    def _reference_ids(references: list[Any]) -> list[str]:
        """Collect up to ``_MAX_REFERENCES`` ArXiv/CorpusId ids from references."""
        ids: list[str] = []
        for ref in references:
            if not isinstance(ref, dict):
                continue
            ext = ref.get("externalIds")
            if not isinstance(ext, dict):
                continue
            if ext.get("ArXiv"):
                ref_id = str(ext["ArXiv"])
            elif ext.get("CorpusId") is not None:
                ref_id = f"CorpusId:{ext['CorpusId']}"
            else:
                continue
            if ref_id not in ids:
                ids.append(ref_id)
            if len(ids) >= _MAX_REFERENCES:
                break
        return ids

    # -- recommendations (best-effort) ----------------------------------- #
    def recommendations(self, seed_ids: list[str], limit: int = 40) -> list[Paper]:
        """Return minimal Paper stubs recommended from ``seed_ids`` (or ``[]``)."""
        if not seed_ids:
            return []
        positive = [self._as_recommendation_id(s) for s in seed_ids]
        try:
            resp = self._http.post(
                RECOMMENDATIONS_URL,
                params={"fields": "title,externalIds", "limit": limit},
                json={"positivePaperIds": positive},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.info("S2 recommendations failed: %s", exc)
            return []

        if not isinstance(data, dict):
            return []
        recommended = data.get("recommendedPapers") or []
        out: list[Paper] = []
        for rec in recommended:
            if not isinstance(rec, dict):
                continue
            ext = rec.get("externalIds") or {}
            arxiv_id = ext.get("ArXiv") if isinstance(ext, dict) else None
            if not arxiv_id:
                continue
            out.append(
                Paper(
                    arxiv_id=str(arxiv_id),
                    title=rec.get("title") or "",
                    status=PaperStatus.SEEN,
                    source="semantic_scholar",
                )
            )
        return out

    @staticmethod
    def _as_recommendation_id(seed: str) -> str:
        """Format a seed id for the recommendations API (arXiv ids get a prefix)."""
        seed = seed.strip()
        if ":" in seed:  # already namespaced (ArXiv:..., CorpusId:...)
            return seed
        return f"ArXiv:{seed}"
