"""Stage 4 (scoring & ranking) tests — all offline via MockLLM + in-memory DB."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from research_agent.llm import MockLLM
from research_agent.models import (
    Extraction,
    FieldProvenance,
    PaperStatus,
)
from research_agent.scoring import (
    RiceEstimate,
    compute_confidence,
    is_foundational,
    stage4_score,
    topological_order,
)
from research_agent.scoring.dependency import DependencyEdge  # noqa: F401  (re-export check)

from .conftest import make_paper


def _rich_extraction(paper_id: str, *, code_link: str | None = "https://github.com/x/hexgen") -> Extraction:
    """A well-grounded extraction: code link, provenance, deps, self-confidence."""
    return Extraction(
        paper_id=paper_id,
        problem_addressed="Decode a B-rep into a hex-meshing DSL program.",
        method_summary="Graph transformer over B-rep faces feeding a pointer-network decoder.",
        contributions_summary="Introduces an execution-guided graph-transformer decoder that emits valid hex-meshing programs.",
        headline_results="92% structurally valid programs, +8 pts over the prior baseline.",
        applicability_to_our_problem="Maps B-rep faces directly to DSL tokens; near drop-in.",
        reviewer_notes="Only evaluated on synthetic parts; real-CAD transfer untested.",
        implementation_cost_estimate="M",
        claimed_advantages=["execution-guided decoding substantially improves program validity"],
        dependencies_on_other_methods=["pointer networks", "graph transformer"],
        code_link=code_link,
        provenance={
            "method_summary": FieldProvenance(section="Method", quote="graph transformer"),
            "headline_results": FieldProvenance(section="Results", quote="92%"),
            "applicability_to_our_problem": FieldProvenance(section="Discussion"),
        },
        extraction_confidence=0.8,
    )


def test_stage4_creates_scored_backlog_item_and_is_idempotent(config, db):
    paper = make_paper(
        "2401.00001",
        "Pointer Networks for B-rep to Hex Mesh Program Synthesis",
        status=PaperStatus.EXTRACTED,
        citation_count=10,
        published=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    paper.reference_ids = ["2101.00001", "2101.00002"]
    db.upsert_paper(paper)
    extraction = _rich_extraction(paper.id)
    db.save_extraction(extraction)

    estimate = RiceEstimate(
        expected_impact=0.7,
        applicability=0.6,
        effort=4.0,
        impact_rationale="Large validity gain on the exact task.",
        effort_rationale="Standard components; a few weeks.",
    )
    llm = MockLLM(structured_responses={"RiceEstimate": estimate})

    created = stage4_score(config, db, llm)

    assert len(created) >= 1
    item = db.get_backlog_item(f"{paper.id}#1")
    assert item is not None
    # Positive score, cached == recomputed.
    assert item.score > 0
    assert item.score == pytest.approx(item.rice.score())
    # The three human-facing reviewer fields are threaded from the extraction.
    assert item.contributions == extraction.contributions_summary
    assert item.applicability == extraction.applicability_to_our_problem
    assert item.reviewer_notes == extraction.reviewer_notes
    # RICE inputs came from the LLM estimate (weights default to 1.0).
    assert item.rice.expected_impact == pytest.approx(0.7)
    assert item.rice.applicability == pytest.approx(0.6)
    assert item.rice.effort == pytest.approx(4.0)
    # Confidence is the deterministic evidence blend.
    assert item.rice.confidence == pytest.approx(compute_confidence(paper, extraction, config))
    # Confidence genuinely reflects code_link + provenance: strip them and it drops.
    bare = Extraction(paper_id=paper.id, method_summary="x", code_link=None)
    assert item.rice.confidence > compute_confidence(paper, bare, config)

    # Status advanced to SCORED.
    assert db.get_paper(paper.id).status == PaperStatus.SCORED

    # Dependency edges persisted (2 citation + 2 extracted).
    edges = list(db.iter_dependency_edges())
    extracted = {e.dst for e in edges if e.source == "extracted"}
    citation = {e.dst for e in edges if e.source == "citation"}
    assert {"pointer networks", "graph transformer"} <= extracted
    assert {"2101.00001", "2101.00002"} <= citation

    # Idempotent rerun: no new items, backlog size unchanged.
    backlog_before = len(list(db.iter_backlog()))
    created_again = stage4_score(config, db, llm)
    assert created_again == []
    assert len(list(db.iter_backlog())) == backlog_before


def test_stage4_skips_extracted_paper_without_extraction(config, db):
    paper = make_paper("2401.09999", "No extraction here", status=PaperStatus.EXTRACTED)
    db.upsert_paper(paper)

    created = stage4_score(config, db, MockLLM())

    assert created == []
    assert db.get_backlog_item(f"{paper.id}#1") is None
    # Paper is left EXTRACTED (not advanced) so a later extraction can be scored.
    assert db.get_paper(paper.id).status == PaperStatus.EXTRACTED


def test_compute_confidence_recency_grace(config):
    """Recent 0-citation paper keeps a healthy confidence; an old one is penalized."""
    recent = make_paper(
        "2406.00001",
        "Fresh preprint",
        citation_count=0,
        published=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    old = make_paper(
        "1801.00001",
        "Old preprint, never cited",
        citation_count=0,
        published=datetime(2018, 1, 1, tzinfo=timezone.utc),
    )
    ext_recent = _rich_extraction(recent.id)
    ext_old = _rich_extraction(old.id)

    c_recent = compute_confidence(recent, ext_recent, config)
    c_old = compute_confidence(old, ext_old, config)

    # Recency grace: the fresh paper is not driven toward zero by its 0 citations.
    assert c_recent > c_old
    assert c_recent > 0.3


def test_is_foundational_old_high_citation_true(config):
    old_canon = make_paper(
        "1801.02000",
        "Pointer Networks",
        citation_count=500,
        published=datetime(2018, 1, 1, tzinfo=timezone.utc),
    )
    recent_low = make_paper(
        "2406.02000",
        "Yet another fresh preprint",
        citation_count=3,
        published=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    assert is_foundational(old_canon, config) is True
    assert is_foundational(recent_low, config) is False


def test_is_foundational_recent_high_influential_true(config):
    """A recent paper can still be canon via a high influential-citation count."""
    paper = make_paper(
        "2406.03000",
        "Recent but already influential",
        citation_count=250,
        published=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    paper.influential_citation_count = 60  # >= foundational_min_citations // 5 (=20)
    assert is_foundational(paper, config) is True


def test_topological_order_dependency_first():
    # Edge A -> B means A builds on B, so B (foundational) must come first.
    edges = [DependencyEdge(src="A", dst="B", source="extracted")]
    order = topological_order(["A", "B"], edges)
    assert order.index("B") < order.index("A")


def test_topological_order_handles_cycles():
    edges = [
        DependencyEdge(src="A", dst="B", source="extracted"),
        DependencyEdge(src="B", dst="A", source="extracted"),
    ]
    order = topological_order(["A", "B"], edges)
    # No infinite loop; every node appears exactly once.
    assert sorted(order) == ["A", "B"]


def test_topological_order_ignores_unknown_edges():
    edges = [DependencyEdge(src="A", dst="Z", source="citation")]
    order = topological_order(["A", "B"], edges)
    assert sorted(order) == ["A", "B"]
