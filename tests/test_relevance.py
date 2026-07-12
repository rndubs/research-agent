"""Stage 2 (relevance cascade) tests — hermetic: MockLLM + HashingEmbedder only."""

from __future__ import annotations

import numpy as np

from research_agent.llm import MockLLM
from research_agent.models import PaperStatus, RelevanceMethod
from research_agent.relevance import (
    RelevanceJudgment,
    build_seed_centroid,
    stage2_relevance,
)
from tests.conftest import make_paper

# Cues the on-domain-aware mock keys off; they appear in the paper title/abstract
# that the classifier prompt embeds verbatim.
_ON_DOMAIN_CUES = ("b-rep", "hex", "cad", "pointer", "equivariant")


def _domain_aware_handler(kind, prompt=None, schema=None, system=None):
    """High score when the prompt carries on-domain cues, low otherwise."""
    if kind != "structured":
        return None
    low = (prompt or "").lower()
    if any(cue in low for cue in _ON_DOMAIN_CUES):
        return RelevanceJudgment(relevant=True, score=0.92, rationale="on-domain method")
    return RelevanceJudgment(relevant=False, score=0.04, rationale="unrelated application")


def _seed_papers(db, sample_papers):
    for p in sample_papers:
        db.upsert_paper(p)
    return {p.id: p.id for p in sample_papers}


def test_cascade_marks_on_domain_relevant_and_excludes_via_keyword(config, db, hashing_embedder, sample_papers):
    _seed_papers(db, sample_papers)
    # Lower the dense gate to the hashing-embedder's operating range so the two
    # on-domain papers survive to the LLM rung (calibrated: paper1~0.42, paper3~0.30).
    config.relevance.embedding_threshold = 0.2
    llm = MockLLM(handler=_domain_aware_handler)

    relevant = stage2_relevance(config, db, hashing_embedder, llm)

    p1 = db.get_paper("2401.00001")  # pointer/B-rep/hex -> on-domain
    p2 = db.get_paper("2401.00002")  # recommender system -> exclude keyword
    p3 = db.get_paper("2401.00003")  # rotation-equivariant CAD -> on-domain

    assert p1.status is PaperStatus.RELEVANT
    assert p3.status is PaperStatus.RELEVANT
    assert p2.status is PaperStatus.IRRELEVANT

    # paper2 filtered at the cheapest rung by the exclude term.
    assert p2.relevance_method is RelevanceMethod.KEYWORD
    assert p2.relevance_score == 0.0
    assert "recommender system" in p2.relevance_rationale.lower()

    # on-domain papers reached and cleared the LLM rung.
    assert p1.relevance_method is RelevanceMethod.LLM
    assert p3.relevance_method is RelevanceMethod.LLM
    assert p1.relevance_score >= config.relevance.llm_threshold
    assert p3.relevance_score >= config.relevance.llm_threshold
    for p in (p1, p3):
        assert p.relevance_rationale  # rationale carried through from the LLM

    # Returned list is exactly the papers marked RELEVANT this run.
    assert {p.id for p in relevant} == {"2401.00001", "2401.00003"}

    # Embeddings stored for every paper that reached the embedding rung; the
    # keyword-dropped paper never got one.
    assert db.get_embedding("2401.00001") is not None
    assert db.get_embedding("2401.00003") is not None
    assert db.get_embedding("2401.00002") is None

    # The LLM was consulted only for the two survivors.
    structured = [c for c in llm.calls if c["kind"] == "structured"]
    assert len(structured) == 2


def test_build_seed_centroid_normalized_and_nonempty_without_seeds(config, db, hashing_embedder):
    # DB is empty: none of the seed ids resolve, so the centroid is built from
    # the problem statement alone and must still be a valid unit vector.
    assert config.seed_papers  # config declares seeds...
    assert all(db.get_paper(sid) is None for sid in config.seed_papers)  # ...none in DB

    centroid = build_seed_centroid(config, db, hashing_embedder)

    assert centroid.shape == (hashing_embedder.dim,)
    assert centroid.dtype == np.float32
    norm = float(np.linalg.norm(centroid))
    assert norm > 0.0
    assert abs(norm - 1.0) < 1e-4  # L2-normalized


def test_embedding_gate_filters_before_llm(config, db, hashing_embedder):
    # A paper that PASSES the keyword rung (hits the 'mesh' include term) but is
    # far below a strict dense threshold must be filtered at the embedding rung
    # and never reach the (permissive) LLM.
    paper = make_paper(
        "2401.09999",
        "Mesh generation for numerical weather prediction",
        "A structured grid mesh solver for atmospheric fluid dynamics and weather forecasting.",
        categories=["physics.ao-ph"],
    )
    db.upsert_paper(paper)

    config.relevance.embedding_threshold = 0.9  # strict: nothing clears it here

    def permissive(kind, prompt=None, schema=None, system=None):
        if kind != "structured":
            return None
        return RelevanceJudgment(relevant=True, score=1.0, rationale="permissive")

    llm = MockLLM(handler=permissive)
    relevant = stage2_relevance(config, db, hashing_embedder, llm)

    stored = db.get_paper("2401.09999")
    assert stored.status is PaperStatus.IRRELEVANT
    assert stored.relevance_method is RelevanceMethod.EMBEDDING
    assert stored.relevance_score < config.relevance.embedding_threshold
    assert relevant == []
    # Gate short-circuits before any LLM spend, despite the permissive mock.
    assert [c for c in llm.calls if c["kind"] == "structured"] == []
    # It still got embedded (it reached the embedding rung).
    assert db.get_embedding("2401.09999") is not None


def test_shortlist_tail_accepted_via_embedding(config, db, hashing_embedder, sample_papers):
    # With a shortlist budget of 1, only the top-ranked survivor gets an LLM call;
    # the other survivor is accepted RELEVANT with method EMBEDDING (not dropped,
    # not force-classified) per the documented shortlist-survivor policy.
    _seed_papers(db, sample_papers)
    config.relevance.embedding_threshold = 0.2
    config.relevance.embedding_shortlist = 1
    llm = MockLLM(handler=_domain_aware_handler)

    relevant = stage2_relevance(config, db, hashing_embedder, llm)

    p1 = db.get_paper("2401.00001")  # highest dense sim -> shortlist -> LLM
    p3 = db.get_paper("2401.00003")  # tail -> accepted via EMBEDDING

    assert p1.status is PaperStatus.RELEVANT and p1.relevance_method is RelevanceMethod.LLM
    assert p3.status is PaperStatus.RELEVANT and p3.relevance_method is RelevanceMethod.EMBEDDING
    assert {p.id for p in relevant} == {"2401.00001", "2401.00003"}

    # Exactly one LLM call (the single shortlist slot).
    assert len([c for c in llm.calls if c["kind"] == "structured"]) == 1


def test_bm25_rrf_path_still_works(config, db, hashing_embedder, sample_papers):
    # The optional fusion path must not break the default outcome.
    _seed_papers(db, sample_papers)
    config.relevance.embedding_threshold = 0.2
    config.relevance.use_bm25_rrf = True
    llm = MockLLM(handler=_domain_aware_handler)

    relevant = stage2_relevance(config, db, hashing_embedder, llm)

    assert {p.id for p in relevant} == {"2401.00001", "2401.00003"}
    assert db.get_paper("2401.00002").status is PaperStatus.IRRELEVANT
