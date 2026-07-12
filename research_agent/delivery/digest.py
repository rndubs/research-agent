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
  - _Contributions:_ {{ it.contributions or '—' }}
  - _Applicable to our work:_ {{ it.applicability or '—' }}
  - _Additional context:_ {{ it.reviewer_notes or '—' }}
  - _Impact_ {{ '%.2f'|format(it.rice.impact) }} · _Applicability_ {{ '%.2f'|format(it.rice.applicability) }} · _Confidence_ {{ '%.2f'|format(it.rice.confidence) }} · _Effort_ {{ '%.1f'|format(it.rice.effort) }}/10
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
  :root {
    color-scheme: light dark;
    --bg: #ffffff;
    --fg: #1a1a1a;
    --muted: #667085;
    --line: #e3e8ef;
    --card-bg: #f7f9fc;
    --card-border: #e3e8ef;
    --card-hover-border: #b9c6da;
    --card-shadow: 0 1px 2px rgba(16,24,40,.06);
    --card-shadow-hover: 0 6px 18px rgba(16,24,40,.10);
    --accent: #2a5db0;
    --found: #b5651d;
    --badge-bg: #4a6fa5;
    --badge-fg: #ffffff;
    --chip-bg: #eef2f8;
    --chip-border: #dfe6f0;
    --chip-k: #667085;
    --chip-v: #1a2b45;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #16181c;
      --fg: #e6e6e6;
      --muted: #9aa0a6;
      --line: #2c313a;
      --card-bg: #1e2127;
      --card-border: #2c313a;
      --card-hover-border: #3d4759;
      --card-shadow: none;
      --card-shadow-hover: 0 6px 18px rgba(0,0,0,.35);
      --accent: #7aa2e3;
      --found: #d98b4a;
      --badge-bg: #3a5a8c;
      --badge-fg: #eaf1fb;
      --chip-bg: #262b33;
      --chip-border: #333a45;
      --chip-k: #9aa0a6;
      --chip-v: #d6e2f5;
    }
  }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         max-width: 860px; margin: 2rem auto; padding: 0 1rem; line-height: 1.55;
         color: var(--fg); background: var(--bg); -webkit-font-smoothing: antialiased; }
  h1 { font-size: 1.6rem; margin-bottom: .2rem; letter-spacing: -.01em; }
  h2 { font-size: 1.1rem; margin: 2.2rem 0 .9rem; padding-bottom: .35rem;
       border-bottom: 1px solid var(--line); }
  .meta { color: var(--muted); margin-top: 0; font-size: .92rem; }
  .empty { color: var(--muted); font-style: italic; }

  .card { display: block; text-decoration: none; color: inherit;
          margin: .85rem 0; padding: .9rem 1rem 1rem;
          background: var(--card-bg); border: 1px solid var(--card-border);
          border-left: 4px solid var(--badge-bg); border-radius: 12px;
          box-shadow: var(--card-shadow);
          transition: border-color .15s ease, box-shadow .15s ease, transform .15s ease; }
  .card:hover, .card:focus-visible { border-color: var(--card-hover-border);
          box-shadow: var(--card-shadow-hover); transform: translateY(-1px); outline: none; }
  .card.foundational { border-left-color: var(--found); }

  .card-head { display: flex; align-items: baseline; flex-wrap: wrap; gap: .5rem; }
  .rank { color: var(--muted); font-variant-numeric: tabular-nums; font-weight: 600; }
  .badge { display: inline-block; background: var(--badge-bg); color: var(--badge-fg);
           font-variant-numeric: tabular-nums; font-weight: 700; font-size: .82rem;
           padding: .12rem .5rem; border-radius: 999px; }
  .card.foundational .badge { background: var(--found); }
  .card-title { font-weight: 600; font-size: 1.02rem; flex: 1 1 12rem; min-width: 0; }
  .tag { font-size: .68rem; text-transform: uppercase; letter-spacing: .06em; font-weight: 700;
         color: var(--found); border: 1px solid var(--found); border-radius: 999px; padding: .05rem .45rem; }

  .fields { margin: .65rem 0 .2rem; }
  .fields dt { font-size: .66rem; text-transform: uppercase; letter-spacing: .05em;
               font-weight: 700; color: var(--chip-k); margin-top: .55rem; }
  .fields dt:first-child { margin-top: 0; }
  .fields dd { margin: .12rem 0 0; color: var(--fg); opacity: .95; }
  .fields dd.empty { opacity: .5; font-style: italic; }

  .chips { display: flex; flex-wrap: wrap; gap: .4rem; margin: .7rem 0 .2rem; }
  .chip { display: inline-flex; align-items: baseline; gap: .35rem; background: var(--chip-bg);
          border: 1px solid var(--chip-border); border-radius: 999px; padding: .18rem .55rem; font-size: .78rem; }
  .chip-k { color: var(--chip-k); text-transform: uppercase; letter-spacing: .04em; font-size: .66rem; font-weight: 600; }
  .chip-v { color: var(--chip-v); font-weight: 700; font-variant-numeric: tabular-nums; }

  .card-foot { display: flex; justify-content: space-between; align-items: center; gap: .5rem;
               margin-top: .7rem; flex-wrap: wrap; }
  .view { color: var(--accent); font-weight: 600; font-size: .88rem; }
  .card:hover .view, .card:focus-visible .view { text-decoration: underline; }
  .pid { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .78rem; }
</style>
</head>
<body>
{% macro card(it, rank=0) %}
<a class="card{% if it.foundational %} foundational{% endif %}"
   href="https://arxiv.org/abs/{{ it.paper_id }}">
  <div class="card-head">
    {% if rank %}<span class="rank">#{{ rank }}</span>{% endif %}
    <span class="badge" title="composite RICE score">{{ '%.3f'|format(it.score) }}</span>
    <span class="card-title">{{ it.title }}</span>
    {% if it.foundational %}<span class="tag">foundational</span>{% endif %}
  </div>
  <dl class="fields">
    <dt>Contributions</dt>
    <dd{% if not it.contributions %} class="empty"{% endif %}>{{ it.contributions or '—' }}</dd>
    <dt>Applicable to our work</dt>
    <dd{% if not it.applicability %} class="empty"{% endif %}>{{ it.applicability or '—' }}</dd>
    <dt>Additional context</dt>
    <dd{% if not it.reviewer_notes %} class="empty"{% endif %}>{{ it.reviewer_notes or '—' }}</dd>
  </dl>
  <div class="chips" aria-label="RICE components">
    <span class="chip"><span class="chip-k">Impact</span><span class="chip-v">{{ '%.2f'|format(it.rice.impact) }}</span></span>
    <span class="chip"><span class="chip-k">Applicability</span><span class="chip-v">{{ '%.2f'|format(it.rice.applicability) }}</span></span>
    <span class="chip"><span class="chip-k">Confidence</span><span class="chip-v">{{ '%.2f'|format(it.rice.confidence) }}</span></span>
    <span class="chip"><span class="chip-k">Effort</span><span class="chip-v">{{ '%.1f'|format(it.rice.effort) }}</span></span>
  </div>
  <div class="card-foot">
    <span class="view">View paper on arXiv →</span>
    <span class="pid">{{ it.paper_id }}</span>
  </div>
</a>
{% endmacro %}
<h1>{{ title }}</h1>
<p class="meta">{{ date }} · {{ new_count }} new item(s) in the last {{ window }} day(s)</p>

<h2>New this window</h2>
{% if new_items %}
{% for it in new_items %}
{{ card(it) }}
{% endfor %}
{% else %}
<p class="empty">No new items in this window.</p>
{% endif %}

<h2>Current top {{ top_items|length }} backlog</h2>
{% for it in top_items %}
{{ card(it, loop.index) }}
{% endfor %}
</body>
</html>
""",
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=True,
)


# The two legacy substring markers of the old metric-laden ``description``
# format ("Headline results: ...\n\nApplicability to our problem: ..."), kept so
# pre-migration backlog rows still render sensibly into the new three fields.
_DESC_APPLIC_MARKER = "Applicability to our problem:"
_DESC_HEADLINE_MARKER = "Headline results:"


def _legacy_split(description: str) -> tuple[str, str]:
    """Best-effort recovery of (contributions, applicability) from an old
    ``description`` blob, for backlog rows written before the three fields
    existed. Never touches ``rationale`` (that string carried the duplicated
    metric readout we are removing from the body)."""
    text = (description or "").strip()
    if not text:
        return "", ""
    applic = ""
    if _DESC_APPLIC_MARKER in text:
        head, _, tail = text.partition(_DESC_APPLIC_MARKER)
        applic = tail.strip()
        text = head.strip()
    if text.startswith(_DESC_HEADLINE_MARKER):
        text = text[len(_DESC_HEADLINE_MARKER):].strip()
    return text, applic


def _view(item: BacklogItem) -> dict:
    r = item.rice
    contributions = (item.contributions or "").strip()
    applicability = (item.applicability or "").strip()
    reviewer_notes = (item.reviewer_notes or "").strip()
    # Backward-compatible fallbacks for rows created before the three fields.
    if not contributions or not applicability:
        legacy_contrib, legacy_applic = _legacy_split(item.description)
        contributions = contributions or legacy_contrib
        applicability = applicability or legacy_applic
    return {
        "title": item.title,
        "paper_id": item.paper_id,
        "score": item.score,
        "foundational": item.foundational,
        "contributions": contributions,
        "applicability": applicability,
        "reviewer_notes": reviewer_notes,
        "rice": {
            "impact": r.expected_impact,
            "applicability": r.applicability,
            "confidence": r.confidence,
            "effort": r.effort,
        },
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
