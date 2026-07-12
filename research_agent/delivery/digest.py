"""Stage-5 windowed digest rendering.

The digest is the human-facing pulse of the monitor: "here is what landed in the
backlog this week, and here is where the backlog stands overall." It is rendered
with jinja2 from inline templates (markdown always; a standalone, asset-free HTML
page when ``config.delivery.render_html`` is set) so the same data drives both
surfaces.

"New" is defined by ``created_at`` falling inside a rolling window
(``digest_window_days``) measured against :func:`research_agent.models.utcnow`.
"""

from __future__ import annotations

from datetime import timedelta

from jinja2 import Template

from ..config import Config
from ..db import Database
from ..models import BacklogItem, BacklogStatus, Digest, utcnow
from .backlog import select_top

_MARKDOWN_TEMPLATE = Template(
    """# {{ title }} — {{ date }}

**{{ new_count }}** new backlog item(s) in the last {{ window }} day(s).

## New this window

{% if new_items %}
{% for it in new_items %}
- **{{ it.title }}** · score {{ '%.3f'|format(it.score) }}{{ ' · _foundational_' if it.foundational else '' }}
  — {{ it.why }}
  [{{ it.paper_id }}](https://arxiv.org/abs/{{ it.paper_id }})
{% endfor %}
{% else %}
_No new items in this window._
{% endif %}

## Current top {{ top_items|length }} backlog

{% for it in top_items %}
{{ loop.index }}. **{{ it.title }}** · score {{ '%.3f'|format(it.score) }}{{ ' · foundational' if it.foundational else '' }} · [{{ it.paper_id }}](https://arxiv.org/abs/{{ it.paper_id }})
{% endfor %}
""",
    trim_blocks=True,
    lstrip_blocks=True,
)

_HTML_TEMPLATE = Template(
    """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} — {{ date }}</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         max-width: 820px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5;
         color: #1a1a1a; background: #fff; }
  h1 { font-size: 1.5rem; margin-bottom: .25rem; }
  h2 { font-size: 1.15rem; margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: .25rem; }
  .meta { color: #666; margin-top: 0; }
  .item { margin: .75rem 0; padding: .5rem .75rem; border-left: 3px solid #4a6fa5; background: #f6f8fb; }
  .item.foundational { border-left-color: #b5651d; }
  .score { font-variant-numeric: tabular-nums; color: #333; font-weight: 600; }
  .why { color: #444; margin: .2rem 0; }
  .tag { font-size: .75rem; text-transform: uppercase; letter-spacing: .04em; color: #b5651d; }
  ol { padding-left: 1.25rem; }
  a { color: #2a5db0; text-decoration: none; }
  a:hover { text-decoration: underline; }
  @media (prefers-color-scheme: dark) {
    body { color: #e6e6e6; background: #16181c; }
    h2 { border-color: #333; }
    .meta { color: #9aa0a6; }
    .item { background: #1e2127; }
    .why { color: #c2c6cc; }
    a { color: #7aa2e3; }
  }
</style>
</head>
<body>
<h1>{{ title }}</h1>
<p class="meta">{{ date }} · {{ new_count }} new item(s) in the last {{ window }} day(s)</p>

<h2>New this window</h2>
{% if new_items %}
{% for it in new_items %}
<div class="item{% if it.foundational %} foundational{% endif %}">
  <div><span class="score">{{ '%.3f'|format(it.score) }}</span> —
    <a href="https://arxiv.org/abs/{{ it.paper_id }}">{{ it.title }}</a>
    {% if it.foundational %}<span class="tag">foundational</span>{% endif %}
  </div>
  <div class="why">{{ it.why }}</div>
</div>
{% endfor %}
{% else %}
<p><em>No new items in this window.</em></p>
{% endif %}

<h2>Current top {{ top_items|length }} backlog</h2>
<ol>
{% for it in top_items %}
  <li>
    <a href="https://arxiv.org/abs/{{ it.paper_id }}">{{ it.title }}</a>
    <span class="score">{{ '%.3f'|format(it.score) }}</span>{% if it.foundational %} <span class="tag">foundational</span>{% endif %}
  </li>
{% endfor %}
</ol>
</body>
</html>
""",
    trim_blocks=True,
    lstrip_blocks=True,
)


def _why(item: BacklogItem) -> str:
    """A one-line justification for the digest entry.

    Prefer the item's own rationale/description; fall back to a compact RICE
    readout so a row is never blank.
    """
    text = (item.rationale or item.description or "").strip()
    if not text:
        r = item.rice
        text = (
            f"RICE {item.score:.3f}: impact {r.expected_impact:.2f}, "
            f"applicability {r.applicability:.2f}, confidence {r.confidence:.2f}, "
            f"effort {r.effort:.1f}"
        )
    text = text.split("\n", 1)[0].strip()
    if len(text) > 180:
        text = text[:177].rstrip() + "..."
    return text


def _view(item: BacklogItem) -> dict:
    return {
        "title": item.title,
        "paper_id": item.paper_id,
        "score": item.score,
        "foundational": item.foundational,
        "why": _why(item),
    }


def render_digest(config: Config, db: Database, window_days: int | None = None) -> Digest:
    """Render the windowed digest artifact (markdown + optional HTML).

    New = non-archived backlog items whose ``created_at`` is within the window.
    ``top_items`` is the full reserved-lane-aware top view (:func:`select_top`);
    the digest body shows the first 10 of it as the "current top backlog".
    """
    window = window_days or config.delivery.digest_window_days
    now = utcnow()
    cutoff = now - timedelta(days=window)

    all_items = list(db.iter_backlog())
    live = [i for i in all_items if i.status != BacklogStatus.ARCHIVED]

    new_items = [i for i in live if i.created_at >= cutoff]
    new_items.sort(key=lambda i: i.score, reverse=True)

    top_items = select_top(all_items, config)
    digest_top = top_items[:10]

    context = {
        "title": config.name and f"{config.name} digest" or "research-agent digest",
        "date": now.strftime("%Y-%m-%d"),
        "window": window,
        "new_count": len(new_items),
        "new_items": [_view(i) for i in new_items],
        "top_items": [_view(i) for i in digest_top],
    }

    markdown = _MARKDOWN_TEMPLATE.render(**context)
    html = _HTML_TEMPLATE.render(**context) if config.delivery.render_html else None

    return Digest(
        title=context["title"],
        generated_at=now,
        new_item_count=len(new_items),
        markdown=markdown,
        html=html,
        top_items=top_items,
    )
