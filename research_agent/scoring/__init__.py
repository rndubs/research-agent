"""Stage 4 — backlog scoring & ranking.

Turns each ``EXTRACTED`` paper's ``Extraction`` into one (or, conservatively, a
couple of) ranked ``BacklogItem``s using a RICE-derived score, builds the
technique dependency graph (citation + extracted edges), and reserves a
foundational lane to fight recency bias. Idempotent: a paper that already has a
``#1`` backlog item, or is no longer ``EXTRACTED``, is skipped.
"""

from __future__ import annotations

from ..config import Config
from ..db import Database
from ..llm import LLMClient
from ..models import BacklogItem, PaperStatus
from .dependency import build_dependency_edges, is_foundational, topological_order
from .rice import (
    RiceEstimate,
    compute_confidence,
    estimate_rice,
    make_backlog_items,
)

__all__ = [
    "RiceEstimate",
    "compute_confidence",
    "estimate_rice",
    "make_backlog_items",
    "build_dependency_edges",
    "topological_order",
    "is_foundational",
    "stage4_score",
]


def stage4_score(config: Config, db: Database, llm: LLMClient) -> list[BacklogItem]:
    """Score every un-scored ``EXTRACTED`` paper into ranked backlog items.

    For each such paper: build its backlog item(s), mark the primary with the
    foundational-lane flag, persist items + dependency edges, and advance the
    paper to ``SCORED``. Returns only the items created this run.
    """
    created: list[BacklogItem] = []

    for paper in db.papers_by_status(PaperStatus.EXTRACTED):
        primary_id = f"{paper.id}#1"
        # Idempotency: never re-score a paper that already has a primary item.
        if db.get_backlog_item(primary_id) is not None:
            continue

        extraction = db.get_extraction(paper.id)
        if extraction is None:
            db.log("stage4_skip_no_extraction", {"paper_id": paper.id})
            continue

        items = make_backlog_items(paper, extraction, config, llm)
        if not items:
            db.log("stage4_no_items", {"paper_id": paper.id})
            continue

        # Only the primary carries the foundational-lane reservation.
        items[0].foundational = is_foundational(paper, config)
        for item in items:
            db.save_backlog_item(item)
            created.append(item)

        for edge in build_dependency_edges(paper, extraction):
            db.add_dependency_edge(edge)

        paper.status = PaperStatus.SCORED
        db.upsert_paper(paper)

    # Best-effort: expose a dependency-respecting order over the whole backlog for
    # delivery to consume. Edges that reference paper ids / method names outside
    # the current backlog-id set are ignored (they simply don't reorder anything).
    all_items = list(db.iter_backlog())
    all_ids = [item.id for item in all_items]
    all_edges = list(db.iter_dependency_edges())
    order = topological_order(all_ids, all_edges)

    db.log(
        "stage4_score",
        {
            "created": len(created),
            "backlog_size": len(all_ids),
            "ordered": len(order),
            "foundational": sum(1 for i in created if i.foundational),
        },
    )
    return created
