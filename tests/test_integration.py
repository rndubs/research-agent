"""End-to-end integration test — the whole five-stage pipeline, fully offline.

Drives ``Pipeline.run()`` with a mocked HTTP transport (a canned arXiv Atom feed;
404s for enrichment and full-text so the graceful fallbacks fire) and a
schema-aware ``MockLLM``. Proves the stages compose: an on-domain paper is
sourced, judged relevant, extracted with provenance, scored into the backlog, and
delivered into a digest + backlog files — while an off-domain paper is filtered
out cheaply.
"""

from __future__ import annotations

import httpx

from research_agent.config import Config
from research_agent.db import Database
from research_agent.embeddings.hashing import HashingEmbedder
from research_agent.http import HttpClient
from research_agent.llm import MockLLM
from research_agent.models import BacklogStatus, PaperStatus
from research_agent.pipeline import Pipeline

ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2405.11111v1</id>
    <title>Pointer Networks for B-rep to Hexahedral Mesh Program Synthesis</title>
    <summary>We generate hexahedral meshing programs from boundary representation (B-rep)
      graphs with a pointer-network graph transformer and execution-guided decoding,
      improving structural validity on real CAD parts.</summary>
    <author><name>A. Researcher</name></author>
    <author><name>B. Scientist</name></author>
    <category term="cs.LG"/>
    <category term="cs.GR"/>
    <published>2024-05-20T00:00:00Z</published>
    <updated>2024-05-20T00:00:00Z</updated>
    <link href="http://arxiv.org/abs/2405.11111v1" rel="alternate" type="text/html"/>
    <link href="http://arxiv.org/pdf/2405.11111v1" title="pdf" type="application/pdf"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2405.22222v1</id>
    <title>A Recommender System for Streaming Movie Ratings</title>
    <summary>Collaborative filtering with matrix factorization for a recommender system
      over movie ratings.</summary>
    <author><name>C. Author</name></author>
    <category term="cs.IR"/>
    <published>2024-05-19T00:00:00Z</published>
    <updated>2024-05-19T00:00:00Z</updated>
    <link href="http://arxiv.org/abs/2405.22222v1" rel="alternate" type="text/html"/>
  </entry>
</feed>
"""

_ON_DOMAIN_CUES = ("b-rep", "brep", "hex", "mesh", "pointer", "cad")


def _llm_handler(kind, prompt=None, schema=None, system=None):
    """Return schema-appropriate structured payloads keyed by schema name."""
    if kind != "structured" or schema is None:
        return None
    name = schema.__name__
    low = (prompt or "").lower()

    if name == "RelevanceJudgment":
        on = any(cue in low for cue in _ON_DOMAIN_CUES)
        return {"relevant": on, "score": 0.93 if on else 0.03, "rationale": "domain-aware mock"}

    if name == "ExtractionResult":
        return {
            "problem_addressed": "Generate valid hex-meshing programs from a B-rep.",
            "method_summary": "Pointer-network graph transformer with execution-guided decoding.",
            "key_architecture_choices": ["pointer/copy heads", "graph transformer encoder"],
            "datasets": ["DeepCAD"],
            "metrics": ["fidelity"],
            "headline_results": "67.9% held-out fidelity on DeepCAD-distribution parts.",
            "claimed_advantages": ["raises structural validity of generated programs"],
            "limitations": ["does not transfer to CNC-machined MAMBO parts"],
            "applicability_to_our_problem": "Directly attacks structural validity, our binding constraint.",
            "implementation_cost_estimate": "M",
            "dependencies_on_other_methods": ["pointer networks"],
            "code_link": "https://github.com/example/hexsynth",
            "provenance": {
                "method_summary": "a pointer-network graph transformer",
                "headline_results": "67.9% held-out fidelity",
            },
            "confidence": 0.85,
        }

    if name == "RiceEstimate":
        return {
            "expected_impact": 0.7,
            "applicability": 0.85,
            "effort": 4.0,
            "impact_rationale": "would move our fidelity metric",
            "effort_rationale": "a moderate reimplementation",
        }
    return None


def _http_handler(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    if host == "export.arxiv.org":
        return httpx.Response(200, text=ATOM_FEED)
    # Enrichment (S2/OpenAlex) and full-text fetch all 404 -> graceful fallbacks.
    return httpx.Response(404, text="not found")


def _config(tmp_path) -> Config:
    return Config.from_dict(
        {
            "name": "integration",
            "problem_statement": (
                "Generate hexproj programs from B-reps; care about structural validity, "
                "domain gap, pointer networks, graph transformers, mesh generation, CAD."
            ),
            "seed_papers": [],
            "include_keywords": ["b-rep", "cad", "pointer network", "mesh", "program synthesis", "hex"],
            "exclude_keywords": ["recommender system", "sentiment analysis"],
            "taxonomy_terms": ["graph transformer"],
            "llm": {"provider": "mock"},
            "embedding": {"provider": "hashing", "hashing_dim": 256},
            "relevance": {"embedding_threshold": 0.05, "embedding_shortlist": 10, "llm_threshold": 0.5},
            "scoring": {"llm_estimate_effort": True, "foundational_reserved_slots": 2},
            "delivery": {"output_dir": str(tmp_path / "out"), "render_html": True},
            "storage": {"db_path": ":memory:"},
        }
    )


def test_full_pipeline_end_to_end(tmp_path):
    config = _config(tmp_path)
    db = Database(":memory:")
    http = HttpClient(transport=httpx.MockTransport(_http_handler))
    llm = MockLLM(handler=_llm_handler)
    embedder = HashingEmbedder(dim=256)

    pipe = Pipeline(config, db=db, http=http, embedder=embedder, llm=llm)
    results = pipe.run()

    # Stage 1: two entries harvested, the recommender-system one prefiltered out.
    assert results["source"]["new_papers"] == 1
    assert db.has_paper("2405.11111")
    assert not db.has_paper("2405.22222")  # dropped by harvest keyword prefilter

    # Stage 2: the on-domain paper was judged relevant (its verdict is recorded on
    # the paper even though a full run then advances it further down the funnel).
    assert results["filter"]["relevant"] == 1
    p = db.get_paper("2405.11111")
    assert p.relevance_score is not None and p.relevance_score >= config.relevance.llm_threshold

    # Stage 3: extracted with provenance-carrying claims (abstract fallback path).
    assert results["extract"]["extracted"] == 1
    ex = db.get_extraction("2405.11111")
    assert ex is not None
    assert ex.method_summary
    assert ex.applicability_to_our_problem
    assert ex.provenance  # at least one grounded field

    # Stage 4: a scored backlog item exists with a positive RICE score; a full run
    # leaves the paper at the terminal SCORED state.
    assert results["score"]["backlog_items"] >= 1
    items = list(db.iter_backlog())
    assert items and items[0].score > 0
    assert db.get_paper("2405.11111").status is PaperStatus.SCORED

    # Stage 5: a digest was produced and files written.
    out = tmp_path / "out"
    assert (out / "backlog.md").exists()
    assert (out / "digest.md").exists()
    assert (out / "digest.html").exists()
    assert results["deliver"]["top_items"] >= 1

    pipe.close()


def test_pipeline_is_idempotent_on_rerun(tmp_path):
    config = _config(tmp_path)
    db = Database(":memory:")
    http = HttpClient(transport=httpx.MockTransport(_http_handler))
    llm = MockLLM(handler=_llm_handler)
    embedder = HashingEmbedder(dim=256)

    pipe = Pipeline(config, db=db, http=http, embedder=embedder, llm=llm)
    pipe.run()
    # A second full run must add no new papers and create no duplicate backlog items.
    n_items_before = sum(1 for _ in db.iter_backlog())
    results2 = pipe.run()
    assert results2["source"]["new_papers"] == 0
    assert results2["extract"]["extracted"] == 0
    assert results2["score"]["backlog_items"] == 0
    assert sum(1 for _ in db.iter_backlog()) == n_items_before

    # And no backlog item was left in a broken/duplicate state.
    active = [i for i in db.iter_backlog() if i.status is not BacklogStatus.ARCHIVED]
    assert len({i.id for i in active}) == len(active)
    pipe.close()
