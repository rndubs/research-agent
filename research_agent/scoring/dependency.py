"""Technique dependency graph + the anti-recency-bias foundational lane.

Two jobs:

1. Turn each paper into directed ``DependencyEdge``s (``src`` builds on ``dst``):
   citation edges from ``paper.reference_ids`` and extracted edges from the
   LLM-named ``dependencies_on_other_methods``. Delivery layers these so a
   foundational technique surfaces before the papers that build on it.
2. Decide whether a paper belongs in the reserved *foundational lane* — the
   high-citation canon that predates the recency window. This deliberately
   counteracts recency bias (the Matthew-effect failure mode where only the
   newest, not-yet-cited preprints float to the top).
"""

from __future__ import annotations

import heapq
from datetime import timezone

from ..config import Config
from ..models import DependencyEdge, Extraction, Paper, utcnow

# Cap citation fan-out so a single heavily-referenced survey can't swamp the
# edge table; the extracted (LLM-named) dependencies are the higher-signal edges.
_MAX_CITATION_EDGES = 50


def build_dependency_edges(
    paper: Paper, extraction: Extraction | None
) -> list[DependencyEdge]:
    """Citation + extracted dependency edges for one paper (``src`` builds on ``dst``)."""
    edges: list[DependencyEdge] = []
    seen: set[tuple[str, str, str]] = set()

    for ref in paper.reference_ids[:_MAX_CITATION_EDGES]:
        ref = (ref or "").strip()
        if not ref or ref == paper.id:
            continue
        key = (paper.id, ref, "citation")
        if key in seen:
            continue
        seen.add(key)
        edges.append(
            DependencyEdge(src=paper.id, dst=ref, source="citation", paper_id=paper.id)
        )

    if extraction is not None:
        for dep in extraction.dependencies_on_other_methods:
            dep = (dep or "").strip()
            if not dep or dep == paper.id:
                continue
            key = (paper.id, dep, "extracted")
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                DependencyEdge(src=paper.id, dst=dep, source="extracted", paper_id=paper.id)
            )

    return edges


def topological_order(item_ids: list[str], edges: list[DependencyEdge]) -> list[str]:
    """Order ``item_ids`` so each node follows the nodes it depends on.

    An edge (``src`` builds on ``dst``) means ``dst`` (the foundational one) must
    come before ``src``. Only edges whose *both* endpoints are in ``item_ids``
    matter; edges to unknown nodes are ignored. Ties break by the original order
    of ``item_ids`` for determinism. Cycles are broken deterministically
    (remaining nodes appended in original order) — never an infinite loop.
    """
    ids = list(dict.fromkeys(item_ids))  # de-dupe, preserve first-seen order
    idset = set(ids)
    order_index = {node: i for i, node in enumerate(ids)}

    deps: dict[str, set[str]] = {node: set() for node in ids}
    dependents: dict[str, set[str]] = {node: set() for node in ids}
    for e in edges:
        if e.src in idset and e.dst in idset and e.src != e.dst:
            if e.dst not in deps[e.src]:
                deps[e.src].add(e.dst)
                dependents[e.dst].add(e.src)

    indegree = {node: len(deps[node]) for node in ids}
    ready = [order_index[n] for n in ids if indegree[n] == 0]
    heapq.heapify(ready)

    result: list[str] = []
    visited: set[str] = set()
    while ready:
        node = ids[heapq.heappop(ready)]
        if node in visited:
            continue
        visited.add(node)
        result.append(node)
        for dependent in sorted(dependents[node], key=lambda x: order_index[x]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, order_index[dependent])

    # Cycle fallback: append anything left over in stable original order.
    if len(result) < len(ids):
        for node in ids:
            if node not in visited:
                visited.add(node)
                result.append(node)
    return result


def _age_days(paper: Paper, now=None) -> int | None:
    published = paper.published
    if published is None:
        return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return (( now or utcnow()) - published).days


def is_foundational(paper: Paper, config: Config, *, now=None) -> bool:
    """Whether a paper belongs in the reserved anti-recency-bias foundational lane.

    True when the paper clears the citation bar
    (``scoring.foundational_min_citations``) AND is *canon*: either it predates
    the recency window (older than ``recent_paper_grace_days``) or it carries a
    high influential-citation count (durable, not just popular). Recent papers
    that merely happen to be highly cited are excluded — the lane exists to
    surface established foundations, not to double-reward the current hype.
    """
    citations = paper.citation_count
    if citations is None or citations < config.scoring.foundational_min_citations:
        return False

    age = _age_days(paper, now)
    predates_window = age is not None and age > config.scoring.recent_paper_grace_days

    influential = paper.influential_citation_count
    high_influential = (
        influential is not None
        and influential >= max(10, config.scoring.foundational_min_citations // 5)
    )

    return predates_window or high_influential
