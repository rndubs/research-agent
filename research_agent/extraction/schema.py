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
    key_architecture_choices: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    headline_results: str = ""
    claimed_advantages: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    applicability_to_our_problem: str = Field(
        default="",
        description="How the method applies to OUR problem; empty if it genuinely does not.",
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
