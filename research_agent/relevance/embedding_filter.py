"""Embedding rung of the relevance cascade: dense similarity to a seed centroid.

The seed centroid is the vector anchor against backlog drift. It is built from
the configured ``problem_statement`` *plus* every hand-picked seed paper that is
resolvable in the DB. The problem statement is **always** included so the
centroid is well-defined even when no seed ids resolve (fresh DB, offline run).

Each candidate paper is embedded once; its cosine similarity to the centroid is
clamped to ``[0, 1]`` (negative dense similarity is meaningless as a relevance
signal) and used to (a) gate against ``embedding_threshold`` and (b) rank the
survivors before the expensive LLM rung.
"""

from __future__ import annotations

import numpy as np

from ..config import Config
from ..db import Database
from ..embeddings import Embedder, cosine_similarity, l2_normalize
from ..models import Paper


def build_seed_centroid(config: Config, db: Database, embedder: Embedder) -> np.ndarray:
    """Mean-pooled, L2-normalized centroid of the problem statement + seed papers.

    Embeds ``config.problem_statement`` and, for each id in
    ``config.seed_papers`` that exists in the DB, the SPECTER-style
    ``Embedder.paper_text(title, abstract)``. The problem statement is always
    part of the pool, so the centroid is never empty even with zero resolvable
    seeds. Returns a ``(dim,)`` float32 vector.
    """
    texts: list[str] = [config.problem_statement or ""]
    for seed_id in config.seed_papers:
        seed = db.get_paper(seed_id)
        if seed is not None:
            texts.append(Embedder.paper_text(seed.title, seed.abstract))

    matrix = embedder.embed(texts)  # (n, dim) float32
    centroid = np.asarray(matrix, dtype=np.float32).mean(axis=0)
    centroid = l2_normalize(centroid)
    return np.asarray(centroid, dtype=np.float32).ravel()


class EmbeddingScorer:
    """Scores a paper's dense similarity to a fixed seed centroid."""

    def __init__(self, embedder: Embedder, centroid: np.ndarray) -> None:
        self.embedder = embedder
        self.centroid = np.asarray(centroid, dtype=np.float32).ravel()

    def score(self, paper: Paper) -> tuple[float, np.ndarray]:
        """Return ``(similarity, vector)`` for ``paper``.

        ``vector`` is the paper's embedding; ``similarity`` is
        ``max(0.0, cosine(vector, centroid))`` so a paper can never earn a
        negative relevance signal.
        """
        text = Embedder.paper_text(paper.title, paper.abstract)
        vector = np.asarray(self.embedder.embed_one(text), dtype=np.float32).ravel()
        sim = max(0.0, cosine_similarity(vector, self.centroid))
        return sim, vector
