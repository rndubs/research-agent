"""RICE-derived scoring for backlog items.

The score is the frozen ``RiceComponents.score()``::

    Score = (ExpectedImpact * Applicability * Confidence) / Effort

* ``ExpectedImpact`` — how much the paper's reported result would move our metric.
* ``Applicability`` — how directly the method transfers to our B-rep->program
  setup.
* ``Confidence`` — evidence / extraction quality. Computed DETERMINISTICALLY here
  (no LLM) from code availability, provenance completeness, the extractor's own
  self-reported confidence, and a citation signal with a recency grace period.
* ``Effort`` — implementation cost (1..10, larger is costlier).

Impact / Applicability / Effort are estimated by the LLM (a bounded sub-task) or,
when ``scoring.llm_estimate_effort`` is off, by transparent heuristics over the
extraction. Only Confidence is fully deterministic — it is the trust axis and we
never want an LLM to talk itself into trusting a thin extraction.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..config import Config
from ..models import BacklogItem, Extraction, Paper, RiceComponents

# --------------------------------------------------------------------------- #
# Confidence weighting (documented, sums to 1.0)
# --------------------------------------------------------------------------- #
# Confidence is a convex combination of four bounded [0,1] evidence signals.
# The weights encode our trust priorities: grounded provenance matters most
# (it is the anti-hallucination signal), then the extractor's self-confidence,
# then reproducibility (code) and community uptake (citations) tie for last.
_W_CODE = 0.20  # a released implementation is directly reproducible
_W_PROVENANCE = 0.35  # fraction of populated claim fields grounded in the text
_W_EXTRACTION_CONF = 0.25  # the extractor's own self-reported confidence
_W_CITATION = 0.20  # community uptake — a *lagging* signal (recency grace applies)
assert abs((_W_CODE + _W_PROVENANCE + _W_EXTRACTION_CONF + _W_CITATION) - 1.0) < 1e-9

# Recent papers get at least this on the citation axis so a lack of (still
# accruing) citations cannot drag a fresh, otherwise-strong paper toward zero.
_RECENCY_CITATION_FLOOR = 0.5
# Neutral value used when the extractor did not report its own confidence.
_NEUTRAL_EXTRACTION_CONF = 0.5
# Citation count that saturates the citation signal to ~1.0 (log-scaled).
_CITATION_SATURATION = 1000

# Substantive claim fields we expect to be grounded by a ``FieldProvenance``.
_SUBSTANTIVE_FIELDS = (
    "problem_addressed",
    "method_summary",
    "key_architecture_choices",
    "datasets",
    "metrics",
    "headline_results",
    "claimed_advantages",
    "limitations",
    "applicability_to_our_problem",
    "implementation_cost_estimate",
    "dependencies_on_other_methods",
)


class RiceEstimate(BaseModel):
    """Flat LLM schema for the model-estimated RICE inputs.

    Confidence is deliberately absent — it is computed deterministically from
    evidence, not asked of the model.
    """

    expected_impact: float = Field(default=0.4, ge=0.0, le=1.0)
    applicability: float = Field(default=0.4, ge=0.0, le=1.0)
    effort: float = Field(default=5.0, ge=1.0, le=10.0, description="Implementation cost, 1..10")
    impact_rationale: str = ""
    effort_rationale: str = ""


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


def _clamp_effort(x: float) -> float:
    """Keep effort in [1, 10] and strictly > 0 (RiceComponents requires > 0)."""
    if x != x:  # NaN guard
        return 5.0
    return 1.0 if x < 1.0 else 10.0 if x > 10.0 else float(x)


def _is_populated(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _has_code(paper: Paper, extraction: Extraction) -> bool:
    return bool(extraction.code_link) or bool(paper.code_links)


def _is_recent(paper: Paper, config: Config) -> bool:
    """True when the paper is newer than the recency grace window (or undated)."""
    from ..models import utcnow

    published = paper.published
    if published is None:
        # Undated papers are treated as recent so citations don't penalize them.
        return True
    if published.tzinfo is None:
        from datetime import timezone

        published = published.replace(tzinfo=timezone.utc)
    age_days = (utcnow() - published).days
    return age_days <= config.scoring.recent_paper_grace_days


def _citation_from_count(citation_count: int | None) -> float:
    """Log-scaled citation count in [0, 1]; None/0 -> 0."""
    import math

    if not citation_count or citation_count <= 0:
        return 0.0
    return min(1.0, math.log10(1 + citation_count) / math.log10(1 + _CITATION_SATURATION))


def _confidence_parts(paper: Paper, extraction: Extraction, config: Config) -> dict[str, float]:
    """Return the four bounded confidence signals plus a `recent` flag (0/1)."""
    code_signal = 1.0 if _has_code(paper, extraction) else 0.0

    populated = [f for f in _SUBSTANTIVE_FIELDS if _is_populated(getattr(extraction, f, None))]
    if populated:
        grounded = sum(1 for f in populated if f in extraction.provenance)
        provenance_signal = grounded / len(populated)
    else:
        provenance_signal = 0.0

    if extraction.extraction_confidence is not None:
        extraction_conf_signal = _clamp01(extraction.extraction_confidence)
    else:
        extraction_conf_signal = _NEUTRAL_EXTRACTION_CONF

    recent = _is_recent(paper, config)
    citation_signal = _citation_from_count(paper.citation_count)
    if recent:
        # Recency grace: never penalize a fresh paper for still-accruing citations.
        citation_signal = max(citation_signal, _RECENCY_CITATION_FLOOR)

    return {
        "code": code_signal,
        "provenance": provenance_signal,
        "extraction_confidence": extraction_conf_signal,
        "citation": citation_signal,
        "recent": 1.0 if recent else 0.0,
    }


def compute_confidence(paper: Paper, extraction: Extraction, config: Config) -> float:
    """Deterministic evidence-quality confidence in [0, 1] (no LLM).

    Weighted blend of: code availability (0.20), provenance completeness (0.35 —
    the fraction of *populated* substantive claim fields that carry a
    ``FieldProvenance``), the extractor's self-reported confidence (0.25), and a
    citation signal (0.20). Citations are lagging, so papers newer than
    ``scoring.recent_paper_grace_days`` are floored on the citation axis rather
    than penalized for a low count.
    """
    p = _confidence_parts(paper, extraction, config)
    confidence = (
        _W_CODE * p["code"]
        + _W_PROVENANCE * p["provenance"]
        + _W_EXTRACTION_CONF * p["extraction_confidence"]
        + _W_CITATION * p["citation"]
    )
    return _clamp01(confidence)


# --------------------------------------------------------------------------- #
# Impact / applicability / effort estimation
# --------------------------------------------------------------------------- #
def _map_cost_to_effort(cost: str) -> float:
    """Map an S/M/L (or free-text) implementation-cost estimate to effort 2/5/8."""
    c = (cost or "").strip().lower()
    if not c:
        return 5.0
    if c.startswith("s") or "small" in c or "low" in c or "trivial" in c:
        return 2.0
    if c.startswith("l") or "large" in c or "high" in c or "hard" in c:
        return 8.0
    if c.startswith("m") or "medium" in c or "moderate" in c:
        return 5.0
    return 5.0


def _heuristic_rice(extraction: Extraction) -> tuple[float, float, float, str, str]:
    """LLM-free fallback: derive impact/applicability/effort from the extraction."""
    effort = _map_cost_to_effort(extraction.implementation_cost_estimate)

    applicability = 0.6 if _is_populated(extraction.applicability_to_our_problem) else 0.2

    impact = 0.3
    if _is_populated(extraction.headline_results):
        impact += 0.2
    if _is_populated(extraction.claimed_advantages):
        impact += 0.1
    impact = _clamp01(impact)

    impact_rationale = (
        "Heuristic: headline results "
        f"{'present' if _is_populated(extraction.headline_results) else 'absent'}, "
        f"{len(extraction.claimed_advantages)} claimed advantage(s)."
    )
    effort_rationale = (
        f"Heuristic from implementation_cost_estimate={extraction.implementation_cost_estimate!r} "
        f"-> effort {effort:g}/10."
    )
    return impact, applicability, effort, impact_rationale, effort_rationale


def _rice_prompt(config: Config, paper: Paper, extraction: Extraction) -> str:
    """Bounded prompt asking the model only for impact/applicability/effort."""
    return (
        "You are triaging a research paper for a narrow ML research backlog.\n\n"
        f"OUR PROBLEM:\n{config.problem_statement}\n\n"
        f"PAPER: {paper.title}\n"
        f"METHOD SUMMARY: {extraction.method_summary}\n"
        f"HEADLINE RESULTS: {extraction.headline_results}\n"
        f"APPLICABILITY (extractor's note): {extraction.applicability_to_our_problem}\n"
        f"IMPLEMENTATION COST (extractor's note): {extraction.implementation_cost_estimate}\n"
        f"CLAIMED ADVANTAGES: {'; '.join(extraction.claimed_advantages)}\n\n"
        "Estimate, grounded ONLY in the above:\n"
        "- expected_impact (0..1): how much this result would move OUR metric.\n"
        "- applicability (0..1): how directly the method transfers to our "
        "B-rep -> program setting.\n"
        "- effort (1..10): implementation cost for us (1 trivial, 10 a project).\n"
        "Give a one-line impact_rationale and effort_rationale."
    )


def estimate_rice(
    paper: Paper, extraction: Extraction, config: Config, llm
) -> tuple[RiceComponents, str]:
    """Produce weighted, clamped ``RiceComponents`` plus a human rationale string."""
    if config.scoring.llm_estimate_effort:
        est = llm.structured(
            _rice_prompt(config, paper, extraction),
            RiceEstimate,
            model=config.llm.scoring_model,
            cache_key=paper.id,  # stable key for batch/agent-as-LLM mode
        )
        impact = est.expected_impact
        applicability = est.applicability
        effort = est.effort
        impact_rationale = est.impact_rationale
        effort_rationale = est.effort_rationale
    else:
        impact, applicability, effort, impact_rationale, effort_rationale = _heuristic_rice(
            extraction
        )

    confidence = compute_confidence(paper, extraction, config)
    parts = _confidence_parts(paper, extraction, config)

    # Domain tilt: apply configured weights as multipliers, then clamp to [0, 1].
    impact = _clamp01(impact * config.scoring.weight_impact)
    applicability = _clamp01(applicability * config.scoring.weight_applicability)
    confidence = _clamp01(confidence * config.scoring.weight_confidence)
    effort = _clamp_effort(effort)

    rice = RiceComponents(
        expected_impact=impact,
        applicability=applicability,
        confidence=confidence,
        effort=effort,
    )
    rationale = (
        f"Impact {impact:.2f} ({impact_rationale or 'n/a'}); "
        f"Applicability {applicability:.2f}; "
        f"Confidence {confidence:.2f} "
        f"[code={bool(parts['code'])}, provenance={parts['provenance']:.2f}, "
        f"extraction_conf={parts['extraction_confidence']:.2f}, "
        f"citation={parts['citation']:.2f}, recent={bool(parts['recent'])}]; "
        f"Effort {effort:.1f}/10 ({effort_rationale or 'n/a'}). "
        f"Score={rice.score():.4f}."
    )
    return rice, rationale


# --------------------------------------------------------------------------- #
# Backlog item construction
# --------------------------------------------------------------------------- #
def _concise_title(paper: Paper, extraction: Extraction) -> str:
    base = (
        extraction.method_summary
        or extraction.problem_addressed
        or paper.title
        or f"Paper {paper.id}"
    )
    base = " ".join(base.split())
    if len(base) > 90:
        base = base[:87].rstrip() + "..."
    return base


def _contributions(extraction: Extraction) -> str:
    """Human-facing summary of the paper's claimed contributions.

    Prefer the dedicated ``contributions_summary``; fall back to the method
    summary (optionally enriched with headline results) so the field is never
    blank for a substantive paper.
    """
    text = (extraction.contributions_summary or "").strip()
    if text:
        return text
    parts: list[str] = []
    if _is_populated(extraction.method_summary):
        parts.append(extraction.method_summary.strip())
    if _is_populated(extraction.headline_results):
        parts.append(f"Headline results: {extraction.headline_results.strip()}")
    return " ".join(parts)


def _description(extraction: Extraction) -> str:
    parts: list[str] = []
    if _is_populated(extraction.headline_results):
        parts.append(f"Headline results: {extraction.headline_results.strip()}")
    if _is_populated(extraction.applicability_to_our_problem):
        parts.append(f"Applicability to our problem: {extraction.applicability_to_our_problem.strip()}")
    return "\n\n".join(parts)


def _maybe_extra_item(
    paper: Paper, extraction: Extraction, primary_rice: RiceComponents, primary_rationale: str
) -> BacklogItem | None:
    """Emit at most ONE secondary item for a distinct high-value advantage.

    Conservative by design: only fires when a claimed advantage is substantive
    and not already captured by the method summary. The secondary item reuses
    the primary RICE estimate with a modest applicability discount (a single
    advantage transfers less directly than the whole method) — no extra LLM call.
    """
    method = (extraction.method_summary or "").lower()
    for advantage in extraction.claimed_advantages:
        adv = (advantage or "").strip()
        if len(adv) < 30:
            continue
        if adv.lower() in method:
            continue
        rice = RiceComponents(
            expected_impact=primary_rice.expected_impact,
            applicability=_clamp01(primary_rice.applicability * 0.8),
            confidence=primary_rice.confidence,
            effort=primary_rice.effort,
        )
        title = " ".join(adv.split())
        if len(title) > 90:
            title = title[:87].rstrip() + "..."
        return BacklogItem(
            id=f"{paper.id}#2",
            paper_id=paper.id,
            title=title,
            description=f"Isolated advantage to try: {adv}",
            contributions=f"Isolated advantage claimed by the paper: {adv}",
            applicability=extraction.applicability_to_our_problem.strip(),
            reviewer_notes=extraction.reviewer_notes.strip(),
            rice=rice,
            score=rice.score(),
            dependencies=list(extraction.dependencies_on_other_methods),
            rationale=f"Secondary advantage of {paper.id}. {primary_rationale}",
        )
    return None


def make_backlog_items(
    paper: Paper, extraction: Extraction, config: Config, llm
) -> list[BacklogItem]:
    """Build the primary backlog item (and optionally one secondary) for a paper."""
    rice, rationale = estimate_rice(paper, extraction, config, llm)
    primary = BacklogItem(
        id=f"{paper.id}#1",
        paper_id=paper.id,
        title=_concise_title(paper, extraction),
        description=_description(extraction),
        contributions=_contributions(extraction),
        applicability=extraction.applicability_to_our_problem.strip(),
        reviewer_notes=extraction.reviewer_notes.strip(),
        rice=rice,
        score=rice.score(),
        dependencies=list(extraction.dependencies_on_other_methods),
        rationale=rationale,
    )
    items = [primary]
    # Secondary "isolated advantage" items are opt-in — one item per paper keeps
    # the backlog clean by default (see ScoringConfig.emit_secondary_items).
    if config.scoring.emit_secondary_items:
        extra = _maybe_extra_item(paper, extraction, rice, rationale)
        if extra is not None:
            items.append(extra)
    return items
