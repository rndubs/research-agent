"""Keyword / taxonomy prefilter — the cheapest stage of the relevance cascade.

Shared by Stage 1 (bound the harvested corpus) and Stage 2 (first cascade rung)
so those modules stay decoupled. Pure string matching, no models: kill obvious
off-domain papers cheaply and keep obvious on-domain ones, leaving the graded
judgment to the embedding and LLM rungs.
"""

from __future__ import annotations

import re

from .config import Config
from .models import Paper


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())


def _contains(haystack: str, needle: str) -> bool:
    """Whole-token-ish containment: 'cad' won't match 'cascade'."""
    needle = needle.lower().strip()
    if not needle:
        return False
    if " " in needle or "-" in needle:
        return _norm(needle).strip() in haystack
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


def keyword_hits(
    text: str,
    include: list[str],
    exclude: list[str],
    taxonomy: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Return ``(matched_include_terms, matched_exclude_terms)`` for ``text``."""
    hay = _norm(text)
    inc_terms = list(include) + list(taxonomy or [])
    matched_inc = [t for t in inc_terms if _contains(hay, t)]
    matched_exc = [t for t in exclude if _contains(hay, t)]
    return matched_inc, matched_exc


def keyword_prefilter(paper: Paper, config: Config) -> tuple[bool, float, list[str]]:
    """Cheap prefilter verdict for a paper.

    Returns ``(passed, score, matched_terms)``. A paper passes if it hits at
    least one include/taxonomy term and no exclude term. ``score`` is a soft
    signal in [0, 1] based on the number of distinct include hits (saturating),
    used only for ordering, never as a headline.
    """
    text = f"{paper.title}\n{paper.abstract}"
    matched_inc, matched_exc = keyword_hits(
        text, config.include_keywords, config.exclude_keywords, config.taxonomy_terms
    )
    if matched_exc:
        return False, 0.0, matched_exc
    passed = len(matched_inc) > 0
    # Saturating score: 1 hit -> 0.34, 3 -> ~0.66, 6+ -> ~0.86.
    score = 1.0 - (1.0 / (1.0 + len(matched_inc))) if matched_inc else 0.0
    return passed, round(score, 4), matched_inc
