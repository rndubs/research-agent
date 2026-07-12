"""Stage-5 backlog ranking + markdown rendering.

The backlog is ordered by RICE ``score`` descending, with one twist: a reserved
"foundational lane". Pure recency/score ranking has a documented failure mode —
newer papers crowd out the high-citation canon they are built on, so the reading
list never points you at the technique you actually need to learn first. The lane
guarantees a floor of foundational items in the top view regardless of their raw
score (see :func:`select_top`).
"""

from __future__ import annotations

from ..config import Config
from ..db import Database
from ..models import BacklogItem, BacklogStatus


def _live(items: list[BacklogItem]) -> list[BacklogItem]:
    return [i for i in items if i.status != BacklogStatus.ARCHIVED]


def select_top(items: list[BacklogItem], config: Config) -> list[BacklogItem]:
    """Rank non-archived items by score, guaranteeing the foundational lane.

    ``config.scoring.foundational_reserved_slots`` of the returned (≤``top_n``)
    items are the highest-scoring foundational items, even when their score would
    otherwise fall outside the top ``top_n``. The remaining slots are filled by
    score. If fewer foundational items exist than reserved slots, only what exists
    is force-included. The returned list is ordered by score descending for
    presentation.
    """
    top_n = config.delivery.top_n
    reserved = config.scoring.foundational_reserved_slots

    active = _live(items)
    active.sort(key=lambda i: i.score, reverse=True)

    selected: list[BacklogItem] = []
    seen: set[str] = set()

    # Fill the reserved lane first with the best foundational items.
    foundational = [i for i in active if i.foundational]
    for f in foundational[: max(0, min(reserved, top_n))]:
        selected.append(f)
        seen.add(f.id)

    # Fill the remaining capacity strictly by score.
    for i in active:
        if len(selected) >= top_n:
            break
        if i.id in seen:
            continue
        selected.append(i)
        seen.add(i.id)

    selected.sort(key=lambda i: i.score, reverse=True)
    return selected[:top_n]


def _cell(value: object) -> str:
    """Sanitize a value for a single markdown table cell."""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _arxiv_link(paper_id: str) -> str:
    return f"[{paper_id}](https://arxiv.org/abs/{paper_id})"


def render_backlog_markdown(
    items: list[BacklogItem], config: Config, db: Database | None = None
) -> str:
    """Render a ranked backlog as a readable markdown document.

    ``db`` is accepted for optional enrichment (paper lookups); the backlog item
    already carries everything the table needs, so rendering works without it.
    """
    ranked = sorted(items, key=lambda i: i.score, reverse=True)
    reserved = config.scoring.foundational_reserved_slots

    lines: list[str] = []
    lines.append(f"# Research backlog — {config.name}")
    lines.append("")
    lines.append(
        f"_{len(ranked)} item(s) shown · top_n = {config.delivery.top_n} · "
        f"{reserved} foundational slots reserved._"
    )
    lines.append("")

    header = [
        "Rank",
        "Score",
        "Title",
        "Impact",
        "Applic",
        "Conf",
        "Effort",
        "Foundational",
        "Paper",
        "Dependencies",
    ]
    align = ["---:", "---:", "---", "---:", "---:", "---:", "---:", ":--:", "---", "---"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(align) + " |")

    for rank, item in enumerate(ranked, start=1):
        r = item.rice
        deps = ", ".join(item.dependencies) if item.dependencies else "—"
        row = [
            str(rank),
            f"{item.score:.3f}",
            _cell(item.title),
            f"{r.expected_impact:.2f}",
            f"{r.applicability:.2f}",
            f"{r.confidence:.2f}",
            f"{r.effort:.1f}",
            "✓" if item.foundational else "—",
            _arxiv_link(item.paper_id),
            _cell(deps),
        ]
        lines.append("| " + " | ".join(row) + " |")

    # Foundational lane subsection.
    lane = [i for i in ranked if i.foundational]
    lines.append("")
    lines.append("## Foundational lane")
    lines.append("")
    lines.append(
        f"Reserved anti-recency-bias slots: {min(len(lane), reserved)} of {reserved} filled."
    )
    lines.append("")
    if lane:
        for item in lane:
            lines.append(
                f"- **{_cell(item.title)}** (score {item.score:.3f}) — "
                f"{_arxiv_link(item.paper_id)}"
            )
    else:
        lines.append("- _No foundational items in the current backlog._")
    lines.append("")

    return "\n".join(lines)
