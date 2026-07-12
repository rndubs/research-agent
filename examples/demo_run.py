"""Offline demo: run the full pipeline against seeded, hexgen-relevant papers.

No network, no API key, no model download. This seeds a handful of papers as if
Stage 1 had harvested them, then runs the relevance -> extraction -> scoring ->
delivery stages with a *domain-aware* mock LLM (so the ranking is meaningful) and
the hashing embedder. It writes a ranked ``backlog.md`` and a ``digest.html`` into
``examples/sample_output/``.

    python examples/demo_run.py

The point is to show the shape of the output for the hexgen problem — swap the
mock LLM for the real Anthropic client (set ANTHROPIC_API_KEY) and the real
arXiv source to run it for real.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from research_agent.config import Config
from research_agent.db import Database
from research_agent.embeddings.hashing import HashingEmbedder
from research_agent.llm import MockLLM
from research_agent.models import Paper, PaperStatus
from research_agent.pipeline import Pipeline

HERE = Path(__file__).resolve().parent
OUT = HERE / "sample_output"


def _dt(y: int, m: int = 1, d: int = 1) -> datetime:
    return datetime(y, m, d, tzinfo=timezone.utc)


# Each seed carries the mock LLM payloads it should elicit, keyed by a unique
# token that appears in the paper's title (and therefore in the LLM prompt).
SEEDS = [
    {
        "token": "Repair Distillation",
        "paper": Paper(
            arxiv_id="2506.10001",
            title="Execution-Guided Repair Distillation for Structured Program Decoders",
            abstract="We train a decoder to repair its own invalid program rollouts with a "
            "DAgger-style on-policy loop, guided by an execution verifier, raising the fraction "
            "of programs that compile and run on B-rep to mesh synthesis.",
            categories=["cs.LG", "cs.AI"],
            citation_count=8,
            published=_dt(2025, 6, 1),
            code_links=["https://github.com/example/repair-distill"],
        ),
        "relevance": 0.95,
        "rice": {"expected_impact": 0.85, "applicability": 0.9, "effort": 4.0},
        "advantage": "directly attacks structural invalidity, the binding constraint",
    },
    {
        "token": "Value-Guided",
        "paper": Paper(
            arxiv_id="2504.10002",
            title="Value-Guided Beam Search for Neural Program Synthesis",
            abstract="A learned critic scores partial programs to steer beam search toward "
            "executable completions, replacing blind best-of-N sampling.",
            categories=["cs.LG"],
            citation_count=15,
            published=_dt(2025, 4, 1),
            code_links=["https://github.com/example/value-search"],
        ),
        "relevance": 0.9,
        "rice": {"expected_impact": 0.8, "applicability": 0.75, "effort": 5.0},
        "advantage": "per-decision search rather than whole-program sampling",
    },
    {
        "token": "Construction-History",
        "paper": Paper(
            arxiv_id="2505.10003",
            title="Construction-History Conditioning for CAD Program Generation",
            abstract="Conditioning a sequence decoder on sketch/extrude construction history "
            "(rather than raw B-rep) improves generation of valid CAD programs.",
            categories=["cs.LG", "cs.GR"],
            citation_count=6,
            published=_dt(2025, 5, 1),
            code_links=[],
        ),
        "relevance": 0.82,
        "rice": {"expected_impact": 0.7, "applicability": 0.7, "effort": 6.0},
        "advantage": "history-as-conditioning is an untested lever for our decoder",
    },
    {
        "token": "ABC Dataset",
        "paper": Paper(
            arxiv_id="2503.10004",
            title="Scaling B-rep Pretraining with the ABC Dataset for Domain Transfer",
            abstract="Pretraining on the large, heterogeneous ABC CAD corpus improves transfer "
            "to out-of-distribution machined parts, addressing the synthetic-to-real domain gap.",
            categories=["cs.CV", "cs.LG"],
            citation_count=22,
            published=_dt(2025, 3, 1),
            code_links=["https://github.com/example/abc-pretrain"],
        ),
        "relevance": 0.8,
        "rice": {"expected_impact": 0.65, "applicability": 0.7, "effort": 5.0},
        "advantage": "diversity corpus targets the real-CAD domain gap",
    },
    {
        "token": "Rotation-Invariant Incidence",
        "paper": Paper(
            arxiv_id="2502.10005",
            title="Rotation-Invariant Incidence Encoders for Boundary-Representation Graphs",
            abstract="A typed, incidence-based encoder that is provably invariant to global "
            "rotation of the input part, evaluated on pose-perturbed CAD benchmarks.",
            categories=["cs.LG", "cs.CV"],
            citation_count=11,
            published=_dt(2025, 2, 1),
            code_links=[],
        ),
        "relevance": 0.7,
        "rice": {"expected_impact": 0.5, "applicability": 0.55, "effort": 7.0},
        "advantage": "a genuinely new rotation mechanism (our native line is closed)",
    },
    {
        "token": "Set Transformer",
        "paper": Paper(
            arxiv_id="1810.00825",
            title="Set Transformer: A Framework for Attention-based Permutation-Invariant Networks",
            abstract="An attention-based module for permutation-invariant set inputs, a "
            "foundational building block for encoders over unordered face sets.",
            categories=["cs.LG"],
            citation_count=1800,
            influential_citation_count=140,
            published=_dt(2018, 10, 1),
            code_links=["https://github.com/juho-lee/set_transformer"],
        ),
        "relevance": 0.72,
        "rice": {"expected_impact": 0.55, "applicability": 0.6, "effort": 3.0},
        "advantage": "foundational set-encoder machinery our encoder builds on",
    },
    {
        "token": "Recommender",
        "paper": Paper(
            arxiv_id="2506.99999",
            title="A Recommender System for E-commerce Product Ranking",
            abstract="Collaborative filtering with implicit feedback for product recommendation.",
            categories=["cs.IR"],
            citation_count=4,
            published=_dt(2025, 6, 1),
        ),
        "relevance": 0.02,  # off-domain: should be filtered out
        "rice": {"expected_impact": 0.1, "applicability": 0.05, "effort": 8.0},
        "advantage": "",
    },
]


def _find_seed(prompt: str) -> dict | None:
    low = prompt.lower()
    for s in SEEDS:
        if s["token"].lower() in low:
            return s
    return None


def _llm_handler(kind, prompt=None, schema=None, system=None):
    if kind != "structured" or schema is None:
        return None
    seed = _find_seed(prompt or "")
    name = schema.__name__
    if name == "RelevanceJudgment":
        score = seed["relevance"] if seed else 0.1
        return {"relevant": score >= 0.5, "score": score, "rationale": "domain-aware demo mock"}
    if name == "ExtractionResult":
        if not seed:
            return None
        p = seed["paper"]
        return {
            "problem_addressed": p.abstract[:120],
            "method_summary": p.title,
            "key_architecture_choices": ["see abstract"],
            "datasets": ["DeepCAD"] if "CAD" in p.abstract or "B-rep" in p.abstract else [],
            "metrics": ["fidelity", "structural validity"],
            "headline_results": "reports gains on program validity / transfer.",
            "claimed_advantages": [seed["advantage"]] if seed["advantage"] else [],
            "limitations": ["evaluated on a narrow benchmark"],
            "applicability_to_our_problem": seed["advantage"],
            "implementation_cost_estimate": "M",
            "dependencies_on_other_methods": [],
            "code_link": (p.code_links[0] if p.code_links else None),
            "provenance": {"method_summary": p.title[:40], "applicability_to_our_problem": p.abstract[:40]},
            "confidence": 0.8,
        }
    if name == "RiceEstimate":
        r = seed["rice"] if seed else {"expected_impact": 0.2, "applicability": 0.2, "effort": 6.0}
        return {
            "expected_impact": r["expected_impact"],
            "applicability": r["applicability"],
            "effort": r["effort"],
            "impact_rationale": "demo estimate",
            "effort_rationale": "demo estimate",
        }
    return None


def main() -> None:
    config = Config.from_dict(
        {
            "name": "hexgen-demo",
            "problem_statement": (
                "Generate hexproj programs from B-reps; prioritize structural validity of "
                "generated programs, real-CAD domain gap, pointer/graph transformers, "
                "verifier-in-the-loop training, and program synthesis search."
            ),
            "seed_papers": [],
            "include_keywords": [
                "b-rep", "cad", "program", "mesh", "pointer", "graph transformer",
                "rotation", "synthesis", "verifier", "repair", "search", "set",
            ],
            "exclude_keywords": ["recommender system", "e-commerce"],
            "llm": {"provider": "mock"},
            "embedding": {"provider": "hashing", "hashing_dim": 256},
            "relevance": {"embedding_threshold": 0.02, "embedding_shortlist": 20, "llm_threshold": 0.5},
            "extraction": {"use_grobid": False, "prefer_html": False},  # abstract-only, no network
            "scoring": {"llm_estimate_effort": True, "foundational_reserved_slots": 1,
                        "foundational_min_citations": 500, "recent_paper_grace_days": 365},
            "delivery": {"output_dir": str(OUT), "render_html": True, "top_n": 10},
            "storage": {"db_path": ":memory:"},
        }
    )

    db = Database(":memory:")
    # Seed papers as if Stage 1 had harvested them.
    for s in SEEDS:
        p = s["paper"]
        p.status = PaperStatus.SEEN
        db.upsert_paper(p)

    pipe = Pipeline(
        config, db=db, embedder=HashingEmbedder(dim=256), llm=MockLLM(handler=_llm_handler)
    )
    results = pipe.run(("filter", "extract", "score", "deliver"))

    print("Pipeline results:", results)
    print(f"\nRanked backlog ({OUT / 'backlog.md'}):\n")
    print((OUT / "backlog.md").read_text())
    pipe.close()


if __name__ == "__main__":
    main()
