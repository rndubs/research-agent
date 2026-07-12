"""Canonical data models — the shared vocabulary for the whole pipeline.

Every stage consumes and produces these models. They are deliberately flat and
JSON-serializable (pydantic v2) so they can round-trip through SQLite and so the
LLM claim-extraction schema stays simple (nested/complex schemas are a documented
extraction failure mode).

Provenance is a first-class citizen: any LLM-asserted claim carries a
``FieldProvenance`` so a reader can trace it back to the paper section it came
from. This is the line between a trustworthy claim store and a hallucination
generator.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def utcnow() -> datetime:
    """Timezone-aware UTC now (all timestamps in the system are UTC-aware)."""
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Processing state machines
# --------------------------------------------------------------------------- #
class PaperStatus(str, Enum):
    """Idempotency state for a paper as it moves through the funnel.

    Reruns key off this so nothing is ever re-processed: a paper only advances,
    never regresses (except an explicit re-extract on a materially changed
    version). ``SEEN`` -> (``RELEVANT`` | ``IRRELEVANT``) -> ``PARSED`` ->
    ``EXTRACTED`` -> ``SCORED``; ``ARCHIVED`` is terminal for stale low-score
    items pruned from the backlog.
    """

    SEEN = "seen"
    RELEVANT = "relevant"
    IRRELEVANT = "irrelevant"
    PARSED = "parsed"
    EXTRACTED = "extracted"
    SCORED = "scored"
    ARCHIVED = "archived"


class BacklogStatus(str, Enum):
    NEW = "new"
    ACTIVE = "active"
    ARCHIVED = "archived"


class RelevanceMethod(str, Enum):
    """Which cascade stage produced a relevance verdict (cheap -> expensive)."""

    KEYWORD = "keyword"
    EMBEDDING = "embedding"
    LLM = "llm"


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #
class FieldProvenance(BaseModel):
    """Where an extracted field came from, for traceability.

    Attached per extracted claim field. ``section`` is the human-readable
    section title (e.g. "Limitations"); ``chunk_index`` and ``page`` locate the
    supporting text. ``quote`` is a short verbatim snippet the LLM was required
    to ground its claim in.
    """

    section: str | None = None
    chunk_index: int | None = None
    page: int | None = None
    quote: str | None = None


# --------------------------------------------------------------------------- #
# Papers
# --------------------------------------------------------------------------- #
class Paper(BaseModel):
    """A canonical paper record, enriched incrementally across stages.

    ``arxiv_id`` is the primary key for arXiv-sourced papers and excludes the
    version suffix; the version is tracked separately so v1/v2 preprints can be
    deduplicated and re-extraction can be gated on material change.
    """

    # Identity ------------------------------------------------------------- #
    arxiv_id: str = Field(..., description="arXiv id without version, e.g. '2409.13740'")
    version: int = Field(default=1, ge=1, description="arXiv version number (v1, v2, ...)")
    doi: str | None = None
    corpus_id: str | None = Field(default=None, description="Semantic Scholar corpus id")
    openalex_id: str | None = None

    # Bibliographic ------------------------------------------------------- #
    title: str = ""
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list, description="arXiv categories")
    published: datetime | None = Field(default=None, description="'created'/submission date")
    updated: datetime | None = None

    # Links / artifacts --------------------------------------------------- #
    pdf_url: str | None = None
    html_url: str | None = None
    code_links: list[str] = Field(default_factory=list)

    # Enrichment (Semantic Scholar / OpenAlex) --------------------------- #
    citation_count: int | None = None
    influential_citation_count: int | None = None
    tldr: str | None = None
    fields_of_study: list[str] = Field(default_factory=list)
    reference_ids: list[str] = Field(
        default_factory=list, description="Corpus/arXiv ids of references, for the dependency graph"
    )

    # Processing state ---------------------------------------------------- #
    status: PaperStatus = PaperStatus.SEEN
    relevance_score: float | None = None
    relevance_rationale: str | None = None
    relevance_method: RelevanceMethod | None = None

    # Bookkeeping --------------------------------------------------------- #
    section_hash: str | None = Field(
        default=None, description="Hash of parsed section text; gates re-extraction on new versions"
    )
    source: str | None = Field(default="arxiv", description="Origin provider name")
    extra: dict[str, Any] = Field(default_factory=dict, description="Provider-specific overflow")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @field_validator("arxiv_id")
    @classmethod
    def _strip_version(cls, v: str) -> str:
        """Normalize away a trailing version so ids are stable dedup keys."""
        v = v.strip()
        if "v" in v:
            head, _, tail = v.rpartition("v")
            if head and tail.isdigit():
                return head
        return v

    @property
    def id(self) -> str:
        """Stable primary key used across the DB."""
        return self.arxiv_id

    @property
    def versioned_id(self) -> str:
        return f"{self.arxiv_id}v{self.version}"


# --------------------------------------------------------------------------- #
# Relevance
# --------------------------------------------------------------------------- #
class RelevanceResult(BaseModel):
    """Outcome of one relevance-cascade stage for one paper."""

    paper_id: str
    relevant: bool
    score: float = Field(..., ge=0.0, le=1.0)
    rationale: str = ""
    method: RelevanceMethod


# --------------------------------------------------------------------------- #
# Full text + extraction
# --------------------------------------------------------------------------- #
class Section(BaseModel):
    """A parsed section of a paper's full text."""

    title: str = ""
    text: str = ""
    page: int | None = None


class Chunk(BaseModel):
    """A retrieval/extraction unit derived from one or more sections."""

    index: int
    text: str
    section: str | None = None
    page: int | None = None


class FullText(BaseModel):
    """Parsed full text of a paper (GROBID/HTML/abstract-only)."""

    paper_id: str
    sections: list[Section] = Field(default_factory=list)
    source: str = Field(default="abstract", description="'grobid' | 'html' | 'abstract'")

    def concatenated(self) -> str:
        parts = []
        for s in self.sections:
            if s.title:
                parts.append(f"## {s.title}\n{s.text}")
            else:
                parts.append(s.text)
        return "\n\n".join(parts)


class Extraction(BaseModel):
    """The flat, schema-constrained claim record extracted per paper.

    Field names mirror the compass-artifact extraction schema. Every substantive
    field has a matching entry in ``provenance`` keyed by field name. Keep this
    schema FLAT — LLMs degrade on nested/complex schemas.
    """

    paper_id: str

    problem_addressed: str = ""
    method_summary: str = ""
    key_architecture_choices: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    headline_results: str = ""
    claimed_advantages: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    applicability_to_our_problem: str = Field(
        default="",
        description="How the method applies to the configured problem; drop items where the LLM cannot say.",
    )
    implementation_cost_estimate: str = Field(
        default="", description="LLM estimate of implementation effort (S/M/L or free text)."
    )
    dependencies_on_other_methods: list[str] = Field(default_factory=list)
    code_link: str | None = None

    provenance: dict[str, FieldProvenance] = Field(default_factory=dict)
    extraction_model: str | None = None
    extraction_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- #
# Backlog / scoring
# --------------------------------------------------------------------------- #
class RiceComponents(BaseModel):
    """The four RICE-derived inputs, each normalized to [0, 1] except effort.

    Adapted from Intercom's RICE: Reach/Impact fold into
    ``expected_impact`` x ``applicability`` (expected impact *on the configured
    problem*); ``confidence`` becomes evidence/extraction quality; ``effort`` is
    implementation cost (>0). Score = impact * applicability * confidence / effort.
    """

    expected_impact: float = Field(..., ge=0.0, le=1.0)
    applicability: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    effort: float = Field(..., gt=0.0, description="Implementation cost, >0 (e.g. person-weeks or 1..10)")

    def score(self) -> float:
        return (self.expected_impact * self.applicability * self.confidence) / self.effort


class BacklogItem(BaseModel):
    """A ranked 'thing to try', derived from an extraction.

    One paper may yield one or more backlog items. ``foundational`` marks items
    reserved in the anti-recency-bias lane (high-citation canon that predates the
    recency window). ``dependencies`` are method names/ids this item builds on,
    used for topological ordering so foundational techniques surface first.
    """

    id: str = Field(..., description="Stable id, e.g. f'{paper_id}#{n}'")
    paper_id: str
    title: str
    description: str = ""

    rice: RiceComponents
    score: float = Field(default=0.0, description="Cached rice.score()")

    foundational: bool = False
    dependencies: list[str] = Field(default_factory=list)
    status: BacklogStatus = BacklogStatus.NEW
    rationale: str = ""
    created_at: datetime = Field(default_factory=utcnow)

    @field_validator("score")
    @classmethod
    def _default_score(cls, v: float, info: Any) -> float:
        return v


class DependencyEdge(BaseModel):
    """A directed edge in the technique dependency graph (from builds-on to base)."""

    src: str = Field(..., description="Method/paper that depends")
    dst: str = Field(..., description="Method/paper depended upon (foundational)")
    source: str = Field(default="extracted", description="'citation' | 'extracted'")
    paper_id: str | None = None


# --------------------------------------------------------------------------- #
# Delivery
# --------------------------------------------------------------------------- #
class Digest(BaseModel):
    """A rendered delivery artifact (daily/weekly)."""

    generated_at: datetime = Field(default_factory=utcnow)
    title: str = "research-agent digest"
    new_item_count: int = 0
    markdown: str = ""
    html: str | None = None
    top_items: list[BacklogItem] = Field(default_factory=list)
