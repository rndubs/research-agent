"""Stage-5 deduplication.

arXiv monitoring routinely surfaces the *same work twice*: a v1 preprint and its
later published/enriched version, or the same paper harvested via two providers
with different ids. Left alone these inflate the backlog and split a technique's
citation signal across two rows. :func:`dedupe_backlog` collapses each duplicate
cluster down to a single keeper and archives the backlog items of the losers.

Matching is deliberately conservative (precision over recall — we would rather
keep a false duplicate than silently drop a distinct paper):

* **Exact** ``doi`` or ``corpus_id`` equality — an unambiguous same-work signal.
* **Near-duplicate title** (``difflib.SequenceMatcher`` ratio over the configured
  ``title_fuzzy_threshold``) **combined with** author overlap (≥1 shared author).
  The author gate is what makes fuzzy title matching safe: two unrelated papers
  can share a boilerplate title ("Attention Is All You Need"-style) but almost
  never also share an author.

Within a cluster the keeper is the paper with the most citations (a proxy for the
canonical/published record), breaking ties toward the newer ``version`` and then
the newer ``published`` date.
"""

from __future__ import annotations

import difflib
import re

from ..config import Config
from ..db import Database
from ..models import BacklogItem, BacklogStatus, Paper

_WORD_RE = re.compile(r"[a-z0-9]+")


def _norm_title(title: str) -> str:
    """Lowercase and collapse whitespace so trivial formatting drift matches."""
    return " ".join(_WORD_RE.findall(title.lower()))


def _block_key(title: str) -> str:
    """Coarse blocking key: the first alphanumeric word of the title.

    Fuzzy comparison only runs within a block, which keeps the pairwise cost near
    linear for the few-hundred-item backlogs this system targets. Near-duplicate
    versions of a paper share their opening word essentially always.
    """
    words = _WORD_RE.findall(title.lower())
    return words[0] if words else ""


def _norm_author(name: str) -> str:
    return " ".join(name.lower().split())


def _authors_overlap(a: Paper, b: Paper) -> bool:
    sa = {_norm_author(x) for x in a.authors if x.strip()}
    sb = {_norm_author(x) for x in b.authors if x.strip()}
    return bool(sa & sb)


def _titles_similar(a: str, b: str, threshold: float) -> bool:
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return False
    return difflib.SequenceMatcher(None, na, nb).ratio() >= threshold


def _keeper_key(p: Paper) -> tuple[int, int, float]:
    """Sort key selecting the canonical paper: citations, then version, then date.

    ``None`` citations sort below any real count (an unknown count should never
    beat a known one), and a missing ``published`` sorts oldest.
    """
    citations = p.citation_count if p.citation_count is not None else -1
    published = p.published.timestamp() if p.published else float("-inf")
    return (citations, p.version, published)


class _UnionFind:
    def __init__(self, ids: list[str]) -> None:
        self.parent = {i: i for i in ids}

    def find(self, x: str) -> str:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:  # path compression
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def dedupe_backlog(db: Database, config: Config) -> list[tuple[str, str]]:
    """Collapse duplicate papers and archive the weaker one's backlog items.

    Returns one ``(kept_paper_id, archived_paper_id)`` tuple per paper that was
    archived (a 3-paper cluster yields two tuples). Only papers referenced by a
    non-archived backlog item are considered; papers without live items cannot be
    a keeper worth surfacing nor produce items worth archiving.
    """
    items: list[BacklogItem] = [
        i for i in db.iter_backlog() if i.status != BacklogStatus.ARCHIVED
    ]

    papers: dict[str, Paper] = {}
    for pid in {i.paper_id for i in items}:
        p = db.get_paper(pid)
        if p is not None:
            papers[pid] = p

    ids = list(papers)
    uf = _UnionFind(ids)

    # 1) Exact id equalities (doi / corpus_id) — global, no author gate needed.
    for attr in ("doi", "corpus_id"):
        groups: dict[str, list[str]] = {}
        for pid, p in papers.items():
            val = getattr(p, attr)
            if val:
                groups.setdefault(str(val).strip().lower(), []).append(pid)
        for group in groups.values():
            for other in group[1:]:
                uf.union(group[0], other)

    # 2) Fuzzy title + author overlap, restricted to a blocking key.
    threshold = config.delivery.title_fuzzy_threshold
    blocks: dict[str, list[str]] = {}
    for pid, p in papers.items():
        blocks.setdefault(_block_key(p.title), []).append(pid)
    for group in blocks.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                pa, pb = papers[group[i]], papers[group[j]]
                if _titles_similar(pa.title, pb.title, threshold) and _authors_overlap(pa, pb):
                    uf.union(group[i], group[j])

    # Materialize clusters.
    clusters: dict[str, list[str]] = {}
    for pid in ids:
        clusters.setdefault(uf.find(pid), []).append(pid)

    result: list[tuple[str, str]] = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        keeper = max((papers[m] for m in members), key=_keeper_key)
        for m in members:
            if m == keeper.id:
                continue
            for item in items:
                if item.paper_id == m and item.status != BacklogStatus.ARCHIVED:
                    item.status = BacklogStatus.ARCHIVED
                    db.save_backlog_item(item)
            result.append((keeper.id, m))
    return result
