"""The flat LLM output schema for claim extraction.

This mirrors the substantive fields of :class:`research_agent.models.Extraction`
but keeps everything *flat* — LLMs degrade badly on nested/complex schemas, so
provenance is a plain ``dict[str, str]`` (field name -> supporting quote) rather
than nested provenance objects. ``ClaimExtractor`` lifts those quotes into
``FieldProvenance`` when mapping back to the canonical ``Extraction`` model.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExtractionResult(BaseModel):
    """Schema the extraction LLM is forced to fill (flat, provenance-first)."""

    problem_addressed: str = ""
    method_summary: str = ""
    contributions_summary: str = Field(
        default="",
        description=(
            "A clear, self-contained 2-4 sentence summary of what the paper CLAIMS "
            "to contribute (its novel method/result), written in plain prose for a "
            "human reviewer. Do not include our-problem framing or scores here."
        ),
    )
    key_architecture_choices: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    headline_results: str = ""
    claimed_advantages: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    applicability_to_our_problem: str = Field(
        default="",
        description=(
            "Which aspects of the paper could be applicable to OUR problem. Be "
            "LIBERAL: this need not be the whole paper — a small subset, a single "
            "mechanism, or even a tangential/analogous idea worth borrowing is "
            "enough. Name the specific transferable aspect(s). Only leave empty if "
            "there is genuinely nothing worth borrowing."
        ),
    )
    reviewer_notes: str = Field(
        default="",
        description=(
            "Freeform additional context the reviewer should know: caveats, "
            "relevant limitations, connections to related work, risks, or anything "
            "important that the contributions/applicability fields above might miss. "
            "This is your own judgment, not restricted to a single quote."
        ),
    )
    implementation_cost_estimate: str = Field(
        default="", description="Effort estimate: S / M / L or a short phrase."
    )
    dependencies_on_other_methods: list[str] = Field(default_factory=list)
    code_link: str | None = None

    # field name -> a short verbatim supporting quote from the provided text.
    # REQUIRED for every non-empty substantive field.
    provenance: dict[str, str] = Field(default_factory=dict)
    # Model self-rated extraction confidence in [0, 1].
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
