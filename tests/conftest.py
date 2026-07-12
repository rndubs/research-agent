"""Shared pytest fixtures — everything here keeps tests hermetic and offline.

Use ``mock_llm`` + ``hashing_embedder`` + ``mock_http`` so no test ever touches
the network, a real model, or an API key.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from research_agent.config import Config
from research_agent.db import Database
from research_agent.embeddings.hashing import HashingEmbedder
from research_agent.http import HttpClient
from research_agent.llm import MockLLM
from research_agent.models import Paper, PaperStatus


@pytest.fixture
def config() -> Config:
    """A small in-memory config aimed at the hexgen domain (no file I/O)."""
    return Config.from_dict(
        {
            "name": "test",
            "problem_statement": "Generate hexproj programs from B-reps; care about "
            "structural validity, domain gap, pointer networks, rotation robustness.",
            "seed_papers": ["1506.03134", "2105.09492"],
            "include_keywords": ["b-rep", "cad", "pointer network", "mesh", "program synthesis"],
            "exclude_keywords": ["recommender system", "sentiment analysis"],
            "taxonomy_terms": ["graph transformer", "equivariant"],
            "llm": {"provider": "mock"},
            "embedding": {"provider": "hashing", "hashing_dim": 256},
            "storage": {"db_path": ":memory:"},
        }
    )


@pytest.fixture
def db() -> Database:
    d = Database(":memory:")
    yield d
    d.close()


@pytest.fixture
def hashing_embedder() -> HashingEmbedder:
    return HashingEmbedder(dim=256)


@pytest.fixture
def mock_llm() -> MockLLM:
    return MockLLM()


def make_paper(
    arxiv_id: str,
    title: str,
    abstract: str = "",
    *,
    categories: list[str] | None = None,
    status: PaperStatus = PaperStatus.SEEN,
    citation_count: int | None = None,
    published: datetime | None = None,
) -> Paper:
    """Convenience builder for test papers."""
    return Paper(
        arxiv_id=arxiv_id,
        title=title,
        abstract=abstract,
        categories=categories or ["cs.LG"],
        status=status,
        citation_count=citation_count,
        published=published or datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_papers() -> list[Paper]:
    return [
        make_paper(
            "2401.00001",
            "Pointer Networks for B-rep to Hex Mesh Program Synthesis",
            "We generate hexahedral meshing programs from boundary representation graphs "
            "using a pointer-network graph transformer and execution-guided decoding.",
            categories=["cs.LG", "cs.GR"],
            citation_count=12,
        ),
        make_paper(
            "2401.00002",
            "A Recommender System for Movie Ratings",
            "Collaborative filtering with matrix factorization for a recommender system.",
            categories=["cs.IR"],
            citation_count=3,
        ),
        make_paper(
            "2401.00003",
            "Rotation-Equivariant Encoders for CAD Solid Models",
            "An SO(3)-equivariant graph neural network over B-rep faces for CAD, improving "
            "pose robustness and domain generalization to real parts.",
            categories=["cs.CV", "cs.LG"],
            citation_count=150,
            published=datetime(2022, 6, 1, tzinfo=timezone.utc),
        ),
    ]


@pytest.fixture
def mock_http_factory():
    """Return a factory that builds an ``HttpClient`` backed by a handler.

    Usage::

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={...})
        http = mock_http_factory(handler)
    """

    def _factory(handler) -> HttpClient:
        transport = httpx.MockTransport(handler)
        return HttpClient(transport=transport)

    return _factory
