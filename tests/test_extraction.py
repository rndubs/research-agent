"""Tests for Stage-3 claim extraction: provenance, persistence, idempotency."""

from __future__ import annotations

import httpx

from research_agent.extraction import ExtractionResult, stage3_extract
from research_agent.models import PaperStatus
from tests.conftest import make_paper

ABSTRACT = (
    "We generate hexahedral meshing programs from boundary representation graphs "
    "using a pointer-network graph transformer and execution-guided decoding."
)


def _populated_result() -> ExtractionResult:
    """A fully-populated extraction with quotes that are substrings of ABSTRACT."""
    return ExtractionResult(
        problem_addressed="Generating hex-meshing DSL programs from B-reps.",
        method_summary="A pointer-network graph transformer with execution-guided decoding.",
        key_architecture_choices=["pointer network", "graph transformer"],
        datasets=["ABC dataset"],
        metrics=["mesh validity"],
        headline_results="Produces valid hex meshes on most parts.",
        claimed_advantages=["execution-guided decoding"],
        limitations=["struggles with rotated parts"],
        applicability_to_our_problem="Directly targets B-rep to hex-meshing DSL generation.",
        implementation_cost_estimate="M",
        dependencies_on_other_methods=["pointer networks"],
        code_link="https://github.com/example/hexgen",
        provenance={
            "problem_addressed": "generate hexahedral meshing programs from boundary representation graphs",
            "method_summary": "execution-guided decoding",
            "applicability_to_our_problem": "pointer-network graph transformer",
        },
        confidence=0.86,
    )


def _extraction_llm():
    from research_agent.llm import MockLLM

    result = _populated_result()

    def handler(kind, prompt=None, schema=None, system=None):
        if kind == "structured" and schema is not None and schema.__name__ == "ExtractionResult":
            return result
        return None

    return MockLLM(handler=handler)


def _abstract_only_http(mock_http_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("offline: force abstract fallback")

    return mock_http_factory(handler)


def _structured_calls(llm):
    return [c for c in llm.calls if c["kind"] == "structured"]


def test_stage3_extract_saves_grounded_extraction(config, db, mock_http_factory):
    llm = _extraction_llm()
    http = _abstract_only_http(mock_http_factory)

    paper = make_paper(
        "2401.00001",
        "Pointer Networks for B-rep to Hex Mesh Program Synthesis",
        abstract=ABSTRACT,
        status=PaperStatus.RELEVANT,
    )
    db.upsert_paper(paper)

    produced = stage3_extract(config, db, llm, http)

    # One extraction produced and persisted.
    assert len(produced) == 1
    saved = db.get_extraction(paper.id)
    assert saved is not None

    # Applicability judged and populated.
    assert saved.applicability_to_our_problem == (
        "Directly targets B-rep to hex-meshing DSL generation."
    )

    # Provenance entries exist and are grounded in the (abstract) full text.
    assert "problem_addressed" in saved.provenance
    prov = saved.provenance["problem_addressed"]
    assert prov.quote and prov.quote in ABSTRACT
    assert prov.section == "Abstract"
    assert prov.chunk_index == 0
    assert "applicability_to_our_problem" in saved.provenance

    # Extraction bookkeeping.
    assert saved.extraction_confidence == 0.86
    assert saved.extraction_model == config.llm.extraction_model

    # Status advanced and a section hash was recorded.
    refreshed = db.get_paper(paper.id)
    assert refreshed.status == PaperStatus.EXTRACTED
    assert refreshed.section_hash

    # Exactly one LLM structured call for the extraction.
    assert len(_structured_calls(llm)) == 1


def test_stage3_extract_is_idempotent_on_unchanged_text(config, db, mock_http_factory):
    llm = _extraction_llm()
    http = _abstract_only_http(mock_http_factory)

    paper = make_paper(
        "2401.00001",
        "Pointer Networks for B-rep to Hex Mesh Program Synthesis",
        abstract=ABSTRACT,
        status=PaperStatus.RELEVANT,
    )
    db.upsert_paper(paper)

    first = stage3_extract(config, db, llm, http)
    assert len(first) == 1
    calls_after_first = len(_structured_calls(llm))
    assert calls_after_first == 1

    # Rerun with unchanged text must skip re-extraction (no new LLM call).
    second = stage3_extract(config, db, llm, http)
    assert second == []
    assert len(_structured_calls(llm)) == calls_after_first
