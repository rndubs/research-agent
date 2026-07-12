"""Batch / agent-as-LLM mode: the plan -> answer -> apply loop, fully offline.

Simulates the agent's answering step with a domain-aware function so the whole
converging loop can be tested without a network or a real model.
"""

from __future__ import annotations

import pytest

from research_agent.config import Config
from research_agent.db import Database
from research_agent.llm.batch import BatchLLM, MissingBatchAnswer, read_requests
from research_agent.models import BacklogStatus, PaperStatus
from research_agent.nightly import batch_apply, batch_plan
from tests.conftest import make_paper

_ON_DOMAIN = ("b-rep", "brep", "hex", "mesh", "pointer", "cad")


def _answer_request(rec: dict) -> dict:
    """Produce a schema-valid payload for one request (this stands in for the agent)."""
    schema = rec["schema"]
    low = rec["prompt"].lower()
    if schema == "RelevanceJudgment":
        on = any(c in low for c in _ON_DOMAIN)
        return {"relevant": on, "score": 0.9 if on else 0.05, "rationale": "sim-agent"}
    if schema == "ExtractionResult":
        return {
            "problem_addressed": "hex meshing from a B-rep",
            "method_summary": "pointer-network graph transformer",
            "key_architecture_choices": ["pointer heads"],
            "datasets": ["DeepCAD"],
            "metrics": ["fidelity"],
            "headline_results": "67.9% fidelity",
            "claimed_advantages": ["structural validity"],
            "limitations": ["no MAMBO transfer"],
            "applicability_to_our_problem": "targets structural validity",
            "implementation_cost_estimate": "M",
            "dependencies_on_other_methods": [],
            "code_link": "https://github.com/example/x",
            "provenance": {"method_summary": "pointer-network graph transformer"},
            "confidence": 0.8,
        }
    if schema == "RiceEstimate":
        return {
            "expected_impact": 0.7,
            "applicability": 0.8,
            "effort": 4.0,
            "impact_rationale": "sim",
            "effort_rationale": "sim",
        }
    raise AssertionError(f"unexpected schema {schema}")


def _answer_all(batch_dir: str) -> int:
    """Read the pending requests and append answers — the simulated agent turn."""
    from research_agent.llm.batch import append_answer

    reqs = read_requests(batch_dir)
    for rec in reqs:
        append_answer(batch_dir, rec["key"], _answer_request(rec))
    return len(reqs)


def _config(tmp_path) -> Config:
    return Config.from_dict(
        {
            "name": "batch-test",
            "problem_statement": "Generate hexproj programs from B-reps; structural validity, "
            "pointer networks, mesh, cad.",
            "seed_papers": [],
            "include_keywords": ["b-rep", "cad", "pointer", "mesh"],
            "exclude_keywords": ["recommender system"],
            "llm": {"provider": "batch", "batch_dir": str(tmp_path / "batch")},
            "embedding": {"provider": "hashing", "hashing_dim": 256},
            "relevance": {"embedding_threshold": 0.02, "embedding_shortlist": 20},
            "extraction": {"use_grobid": False, "prefer_html": False},  # abstract-only, no network
            "delivery": {"output_dir": str(tmp_path / "out"), "render_html": True},
            "storage": {"db_path": str(tmp_path / "state.db")},
        }
    )


def _seed(config: Config) -> None:
    db = Database(config.storage.db_path)
    db.upsert_paper(
        make_paper(
            "2405.30001",
            "Pointer Networks for B-rep Hex Mesh Program Synthesis",
            "graph transformer over boundary representation faces generating hexahedral meshing programs",
        )
    )
    db.upsert_paper(
        make_paper(
            "2405.30002",
            "A Recommender System for Movies",
            "collaborative filtering recommender system",
            categories=["cs.IR"],
        )
    )
    db.close()


def test_batch_loop_converges_and_applies(tmp_path):
    config = _config(tmp_path)
    _seed(config)

    # Drive the plan -> answer loop to convergence (relevance, extraction, scoring rounds).
    rounds = 0
    for _ in range(8):
        res = batch_plan(config)
        rounds += 1
        if res["status"] == "ready":
            break
        assert res["count"] >= 1
        answered = _answer_all(config.llm.batch_dir)
        assert answered == res["count"]
    else:
        pytest.fail("batch loop did not converge")

    assert res["status"] == "ready"
    assert rounds >= 3  # at least relevance, extraction, scoring rounds

    # The plan phase must not have mutated the real DB (snapshots are discarded).
    db = Database(config.storage.db_path)
    assert db.get_paper("2405.30001").status is PaperStatus.SEEN
    db.close()

    # Apply for real.
    digest = batch_apply(config)
    db = Database(config.storage.db_path)
    p1 = db.get_paper("2405.30001")
    assert p1.status is PaperStatus.SCORED
    items = [i for i in db.iter_backlog() if i.status is not BacklogStatus.ARCHIVED]
    assert items and items[0].score > 0
    db.close()
    assert (tmp_path / "out" / "backlog.md").exists()
    assert digest.new_item_count >= 1


def test_batch_apply_before_answering_raises(tmp_path):
    config = _config(tmp_path)
    _seed(config)
    # No plan/answers yet -> strict apply must refuse rather than commit stubs.
    with pytest.raises(MissingBatchAnswer):
        batch_apply(config)


def test_batch_key_is_stable_per_paper_and_schema():
    from research_agent.extraction.schema import ExtractionResult
    from research_agent.relevance.llm_classifier import RelevanceJudgment

    k1 = BatchLLM._key(RelevanceJudgment.__name__, "prompt A", "2405.30001")
    k2 = BatchLLM._key(RelevanceJudgment.__name__, "prompt B (different text)", "2405.30001")
    assert k1 == k2  # stable across prompt-text variation when cache_key is fixed
    k3 = BatchLLM._key(ExtractionResult.__name__, "prompt A", "2405.30001")
    assert k3 != k1  # schema is part of the key
