"""Stage 2 — relevance filtering as a cheap -> expensive cascade.

Three rungs, each strictly cheaper than the next, every verdict anchored to
``config.problem_statement`` + ``config.seed_papers`` (the guard against backlog
drift):

1. **Keyword** (`research_agent.filters.keyword_prefilter`): a paper that hits an
   *exclude* term is dropped immediately (IRRELEVANT / KEYWORD, score 0). A paper
   with no *include* hit is also dropped (IRRELEVANT / KEYWORD): Stage 1 already
   keyword-prefiltered the corpus, so a SEEN paper with zero include hits is off
   domain. (The `keyword_prefilter` contract collapses both into ``not passed``;
   we split the rationale by whether an exclude term matched.)
2. **Embedding**: cosine similarity to the seed centroid. Below
   ``embedding_threshold`` -> IRRELEVANT / EMBEDDING (score = sim). Survivors are
   ranked by similarity (optionally fused with a BM25 rank via RRF when
   ``use_bm25_rrf`` is set).
3. **LLM**: the top ``embedding_shortlist`` survivors get a schema-forced LLM
   verdict. ``score >= llm_threshold`` -> RELEVANT / LLM, else IRRELEVANT / LLM.

**Shortlist-survivor policy.** Survivors that clear the embedding threshold but
fall *beyond* the shortlist budget are not thrown away and are not sent to the
LLM (we simply chose not to spend the call). They are marked RELEVANT with
method EMBEDDING and score = sim, so the downstream stages still see them; the
method field records that they were dense-accepted rather than LLM-verified.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from ..config import Config
from ..db import Database
from ..embeddings import Embedder
from ..filters import keyword_prefilter
from ..llm import LLMClient
from ..models import Paper, PaperStatus, RelevanceMethod
from .embedding_filter import EmbeddingScorer, build_seed_centroid
from .llm_classifier import LLMRelevanceClassifier, RelevanceJudgment

__all__ = [
    "build_seed_centroid",
    "EmbeddingScorer",
    "RelevanceJudgment",
    "LLMRelevanceClassifier",
    "stage2_relevance",
]

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _bm25_rank(query: str, docs: list[tuple[str, str]], k1: float = 1.5, b: float = 0.75) -> list[str]:
    """Rank ``docs`` (``(paper_id, text)``) against ``query`` by Okapi BM25.

    Pure-python, operating only over the small survivor set, so it stays cheap
    and dependency-free. Returns paper ids ordered best-first.
    """
    q_terms = set(_tokens(query))
    tokenized = {pid: _tokens(text) for pid, text in docs}
    n = len(tokenized) or 1
    avgdl = (sum(len(t) for t in tokenized.values()) / n) or 1.0

    df: Counter[str] = Counter()
    for toks in tokenized.values():
        for term in set(toks):
            if term in q_terms:
                df[term] += 1

    scores: dict[str, float] = {}
    for pid, toks in tokenized.items():
        tf = Counter(toks)
        dl = len(toks) or 1
        score = 0.0
        for term in q_terms:
            if term not in tf:
                continue
            idf = math.log(1.0 + (n - df[term] + 0.5) / (df[term] + 0.5))
            freq = tf[term]
            denom = freq + k1 * (1.0 - b + b * dl / avgdl)
            score += idf * (freq * (k1 + 1.0)) / denom
        scores[pid] = score
    return sorted(scores, key=lambda pid: scores[pid], reverse=True)


def _rrf_fuse(dense_ids: list[str], bm25_ids: list[str], alpha: float, k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion of two rankings, weighting dense by ``alpha``."""
    fused: dict[str, float] = {pid: 0.0 for pid in dense_ids}
    for rank, pid in enumerate(dense_ids):
        fused[pid] = fused.get(pid, 0.0) + alpha * (1.0 / (k + rank + 1))
    for rank, pid in enumerate(bm25_ids):
        fused[pid] = fused.get(pid, 0.0) + (1.0 - alpha) * (1.0 / (k + rank + 1))
    return sorted(fused, key=lambda pid: fused[pid], reverse=True)


def _order_survivors(
    survivors: list[tuple[Paper, float]], config: Config
) -> list[tuple[Paper, float]]:
    """Order embedding survivors best-first before shortlisting.

    Default: dense similarity descending. When ``use_bm25_rrf`` is enabled, fuse
    the dense order with a BM25-over-abstracts order (query = the problem
    statement) via Reciprocal Rank Fusion.
    """
    dense_sorted = sorted(survivors, key=lambda ps: ps[1], reverse=True)
    if not config.relevance.use_bm25_rrf or len(dense_sorted) < 2:
        return dense_sorted

    by_id = {p.id: (p, sim) for p, sim in dense_sorted}
    dense_ids = [p.id for p, _ in dense_sorted]
    docs = [(p.id, Embedder.paper_text(p.title, p.abstract)) for p, _ in dense_sorted]
    bm25_ids = _bm25_rank(config.problem_statement, docs)
    fused_ids = _rrf_fuse(dense_ids, bm25_ids, config.relevance.rrf_alpha)
    return [by_id[pid] for pid in fused_ids]


def _effective_threshold(config: Config, embedder: Embedder) -> float:
    """The embedding cutoff to actually use, correcting for a silent fallback.

    ``config.relevance.embedding_threshold`` is calibrated for the *configured*
    embedder (SPECTER2 in production). If ``get_embedder`` had to fall back to a
    different embedder (e.g. torch/transformers missing, so the hashing embedder
    is active even though ``embedding.provider`` says ``specter2``), that dense-
    tuned cutoff would silently reject everything and starve the LLM rung. In that
    case only, defer to the active embedder's own calibrated threshold.
    """
    configured = config.relevance.embedding_threshold
    fell_back = getattr(embedder, "name", "") != config.embedding.provider
    if fell_back:
        return min(configured, float(getattr(embedder, "suggested_relevance_threshold", configured)))
    return configured


def _mark(
    paper: Paper,
    *,
    score: float,
    rationale: str,
    method: RelevanceMethod,
    status: PaperStatus,
) -> None:
    paper.relevance_score = float(score)
    paper.relevance_rationale = rationale
    paper.relevance_method = method
    paper.status = status


def stage2_relevance(
    config: Config, db: Database, embedder: Embedder, llm: LLMClient
) -> list[Paper]:
    """Run the relevance cascade over every SEEN paper.

    Sets ``relevance_score`` / ``relevance_rationale`` / ``relevance_method`` /
    ``status`` on each paper and persists it. Stores an embedding for every paper
    that reaches the embedding rung. Returns the papers marked RELEVANT this run.

    See the module docstring for the shortlist-survivor policy: survivors beyond
    the LLM shortlist budget are accepted (RELEVANT / EMBEDDING) rather than
    dropped or force-classified.
    """
    rc = config.relevance
    threshold = _effective_threshold(config, embedder)
    centroid = build_seed_centroid(config, db, embedder)
    scorer = EmbeddingScorer(embedder, centroid)
    classifier = LLMRelevanceClassifier(llm, config)

    counts = {
        "seen": 0,
        "keyword_excluded": 0,
        "keyword_no_include": 0,
        "embedding_filtered": 0,
        "llm_relevant": 0,
        "llm_irrelevant": 0,
        "embedding_relevant": 0,
    }
    relevant: list[Paper] = []
    survivors: list[tuple[Paper, float]] = []

    # ---- rungs 1 (keyword) and 2 (embedding gate) --------------------------
    for paper in db.papers_by_status(PaperStatus.SEEN):
        counts["seen"] += 1
        passed, _kw_score, matched = keyword_prefilter(paper, config)
        if not passed:
            if matched:  # exclude-term hit (keyword_prefilter returns the exclude terms)
                _mark(
                    paper,
                    score=0.0,
                    rationale=f"Excluded by keyword(s): {', '.join(matched)}",
                    method=RelevanceMethod.KEYWORD,
                    status=PaperStatus.IRRELEVANT,
                )
                counts["keyword_excluded"] += 1
            else:  # no include/taxonomy hit at all
                _mark(
                    paper,
                    score=0.0,
                    rationale="No include-keyword match",
                    method=RelevanceMethod.KEYWORD,
                    status=PaperStatus.IRRELEVANT,
                )
                counts["keyword_no_include"] += 1
            db.upsert_paper(paper)
            continue

        sim, vec = scorer.score(paper)
        db.save_embedding(paper.id, vec, embedder.name)
        if sim < threshold:
            _mark(
                paper,
                score=sim,
                rationale=f"Below embedding threshold ({sim:.3f} < {threshold:.3f})",
                method=RelevanceMethod.EMBEDDING,
                status=PaperStatus.IRRELEVANT,
            )
            db.upsert_paper(paper)
            counts["embedding_filtered"] += 1
            continue

        survivors.append((paper, sim))

    # ---- rung 3 (LLM on the shortlist) + accept the tail -------------------
    ordered = _order_survivors(survivors, config)
    shortlist = ordered[: rc.embedding_shortlist]
    tail = ordered[rc.embedding_shortlist :]

    for paper, _sim in shortlist:
        result = classifier.classify(paper)
        if result.score >= rc.llm_threshold:
            _mark(
                paper,
                score=result.score,
                rationale=result.rationale,
                method=RelevanceMethod.LLM,
                status=PaperStatus.RELEVANT,
            )
            relevant.append(paper)
            counts["llm_relevant"] += 1
        else:
            _mark(
                paper,
                score=result.score,
                rationale=result.rationale,
                method=RelevanceMethod.LLM,
                status=PaperStatus.IRRELEVANT,
            )
            counts["llm_irrelevant"] += 1
        db.upsert_paper(paper)

    for paper, sim in tail:
        _mark(
            paper,
            score=sim,
            rationale=(
                "Passed embedding threshold; accepted without LLM verification "
                "(shortlist budget exhausted)"
            ),
            method=RelevanceMethod.EMBEDDING,
            status=PaperStatus.RELEVANT,
        )
        relevant.append(paper)
        counts["embedding_relevant"] += 1
        db.upsert_paper(paper)

    counts["relevant_total"] = len(relevant)
    db.log("stage2_relevance", counts)
    return relevant
