"""Stage 5 — dedup, delivery & digest.

Entry point :func:`stage5_deliver` runs the terminal stage of the pipeline:

1. Deduplicate the backlog (archive weaker duplicate papers' items).
2. Build the reserved-lane-aware ranked top view.
3. Render the ranked backlog markdown and the windowed digest (markdown + HTML).
4. Write the artifacts into ``config.delivery.output_dir`` and audit-log the run.
"""

from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..db import Database
from ..models import Digest
from .backlog import render_backlog_markdown, select_top
from .dedup import dedupe_backlog
from .digest import render_digest

__all__ = [
    "dedupe_backlog",
    "select_top",
    "render_backlog_markdown",
    "render_digest",
    "stage5_deliver",
]


def stage5_deliver(config: Config, db: Database) -> Digest:
    """Dedup, render, persist artifacts, and return the digest."""
    duplicates = dedupe_backlog(db, config)

    items = select_top(list(db.iter_backlog()), config)
    backlog_md = render_backlog_markdown(items, config, db)
    digest = render_digest(config, db)

    out_dir = Path(config.delivery.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "backlog.md").write_text(backlog_md, encoding="utf-8")
    (out_dir / "digest.md").write_text(digest.markdown, encoding="utf-8")
    if digest.html is not None:
        (out_dir / "digest.html").write_text(digest.html, encoding="utf-8")

    db.log(
        "stage5_deliver",
        {
            "duplicates_archived": len(duplicates),
            "top_items": len(items),
            "new_items": digest.new_item_count,
            "output_dir": str(out_dir),
            "html": digest.html is not None,
        },
    )
    return digest
