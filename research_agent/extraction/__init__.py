"""Stage 3: full-text parsing + schema-constrained claim extraction.

Runs on RELEVANT papers (the expensive, Stage-2-gated step): fetch full text
(GROBID / HTML / abstract fallback), chunk it, run provenance-carrying LLM
extraction, and persist the resulting :class:`~research_agent.models.Extraction`.
Idempotent — a paper is re-extracted only when its parsed section text materially
changes (tracked via ``Paper.section_hash``).
"""

from __future__ import annotations

import hashlib

from ..config import Config
from ..db import Database
from ..http import HttpClient
from ..llm import LLMClient
from ..models import Extraction, PaperStatus
from ..parsing import fetch_fulltext
from .extractor import ClaimExtractor
from .schema import ExtractionResult

__all__ = ["ClaimExtractor", "ExtractionResult", "stage3_extract"]


def _section_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def stage3_extract(
    config: Config, db: Database, llm: LLMClient, http: HttpClient
) -> list[Extraction]:
    """Extract claims for all RELEVANT papers; return extractions produced now.

    Already-EXTRACTED papers are revisited only to detect a materially changed
    version: if the parsed section text still hashes the same and an extraction
    exists, they are skipped (no LLM call).
    """
    extractor = ClaimExtractor(llm, config)
    produced: list[Extraction] = []

    # RELEVANT papers are the primary workload; EXTRACTED papers are revisited so
    # re-extraction fires on material change (both cases guarded by section_hash).
    papers = db.papers_by_status(PaperStatus.RELEVANT) + db.papers_by_status(
        PaperStatus.EXTRACTED
    )

    for paper in papers:
        fulltext = fetch_fulltext(paper, http, config)
        section_hash = _section_hash(fulltext.concatenated())

        # Idempotency: skip unchanged, already-extracted papers.
        if (
            paper.status == PaperStatus.EXTRACTED
            and paper.section_hash == section_hash
            and db.get_extraction(paper.id) is not None
        ):
            db.log(
                "stage3_extract.skip",
                {"paper_id": paper.id, "reason": "unchanged", "source": fulltext.source},
            )
            continue

        extraction = extractor.extract(paper, fulltext)
        db.save_extraction(extraction)

        paper.section_hash = section_hash
        paper.status = PaperStatus.EXTRACTED
        db.upsert_paper(paper)

        db.log(
            "stage3_extract",
            {
                "paper_id": paper.id,
                "source": fulltext.source,
                "sections": len(fulltext.sections),
                "provenance_fields": len(extraction.provenance),
                "confidence": extraction.extraction_confidence,
            },
        )
        produced.append(extraction)

    return produced
