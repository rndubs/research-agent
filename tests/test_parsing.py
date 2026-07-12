"""Tests for Stage-3 full-text parsing: HTML sections, chunking, fetch fallback."""

from __future__ import annotations

import httpx

from research_agent.models import FullText, Section
from research_agent.parsing import (
    chunk_sections,
    fetch_fulltext,
    parse_html_sections,
)
from tests.conftest import make_paper


# --------------------------------------------------------------------------- #
# parse_html_sections
# --------------------------------------------------------------------------- #
def test_parse_html_sections_groups_by_headings_and_strips_scripts():
    html = """
    <html>
      <head>
        <style>.hidden { color: red; }</style>
        <script>var secret = "SHOULD_NOT_APPEAR";</script>
      </head>
      <body>
        <p>Leading preamble text.</p>
        <h1>Introduction</h1>
        <p>We study B-rep to hex-mesh program synthesis.</p>
        <h2>Method</h2>
        <p>Our model uses a pointer network.</p>
        <p>It decodes a DSL program.</p>
        <script>var inline = "ALSO_HIDDEN";</script>
        <h2>Limitations</h2>
        <p>The decoder struggles with rotation.</p>
      </body>
    </html>
    """
    sections = parse_html_sections(html)
    titles = [s.title for s in sections]

    assert "Introduction" in titles
    assert "Method" in titles
    assert "Limitations" in titles

    by_title = {s.title: s.text for s in sections}
    # Body text is attributed to its preceding heading.
    assert "pointer network" in by_title["Method"]
    assert "decodes a DSL program" in by_title["Method"]
    assert "rotation" in by_title["Limitations"]

    # Script/style content is stripped from every section.
    blob = " ".join(s.text for s in sections)
    assert "SHOULD_NOT_APPEAR" not in blob
    assert "ALSO_HIDDEN" not in blob
    assert "color: red" not in blob


def test_parse_html_sections_empty_input():
    assert parse_html_sections("") == []


# --------------------------------------------------------------------------- #
# chunk_sections
# --------------------------------------------------------------------------- #
def test_chunk_sections_packs_small_sections_within_token_budget():
    ft = FullText(
        paper_id="p",
        sections=[
            Section(title="A", text=" ".join(["word"] * 10)),
            Section(title="B", text=" ".join(["word"] * 10)),
        ],
    )
    chunks = chunk_sections(ft, max_tokens=25, max_chunks=10)
    # Both 10-word sections fit into a single 25-word chunk.
    assert len(chunks) == 1
    assert len(chunks[0].text.split()) == 20
    assert all(len(c.text.split()) <= 25 for c in chunks)


def test_chunk_sections_splits_oversize_section():
    ft = FullText(
        paper_id="p",
        sections=[Section(title="Big", text=" ".join(["w"] * 100))],
    )
    chunks = chunk_sections(ft, max_tokens=40, max_chunks=10)
    assert len(chunks) == 3  # 40 + 40 + 20
    assert all(len(c.text.split()) <= 40 for c in chunks)
    # Split pieces keep the section title.
    assert all(c.section == "Big" for c in chunks)


def test_chunk_sections_always_keeps_limitations_under_budget_pressure():
    # Many filler sections would exhaust a tight chunk budget...
    sections = [
        Section(title=f"Section {i}", text=" ".join(["filler"] * 50))
        for i in range(20)
    ]
    # ...but the limitations section must still survive truncation.
    sections.append(
        Section(title="Limitations", text="the model fails on rotated parts")
    )
    ft = FullText(paper_id="p", sections=sections)

    chunks = chunk_sections(
        ft, max_tokens=40, max_chunks=3, limitation_patterns=["limitation"]
    )

    assert all(len(c.text.split()) <= 40 for c in chunks)
    # The Limitations content is present despite the budget being consumed by
    # earlier sections.
    assert any("limitation" in (c.section or "").lower() for c in chunks)
    limitation_text = " ".join(
        c.text for c in chunks if "limitation" in (c.section or "").lower()
    )
    assert "rotated parts" in limitation_text


# --------------------------------------------------------------------------- #
# fetch_fulltext
# --------------------------------------------------------------------------- #
def test_fetch_fulltext_falls_back_to_abstract_when_fetch_raises(
    config, mock_http_factory
):
    def raising_handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("network down")

    http = mock_http_factory(raising_handler)
    paper = make_paper("2401.09999", "A paper", abstract="A concise abstract.")

    ft = fetch_fulltext(paper, http, config)

    assert ft.source == "abstract"
    assert len(ft.sections) == 1
    assert ft.sections[0].title == "Abstract"
    assert ft.sections[0].text == "A concise abstract."


def test_fetch_fulltext_returns_html_sections_when_served(config, mock_http_factory):
    html = (
        "<html><body>"
        "<h1>Introduction</h1><p>Pointer networks for B-reps.</p>"
        "<h2>Limitations</h2><p>Rotation is hard.</p>"
        "</body></html>"
    )

    def html_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    http = mock_http_factory(html_handler)
    paper = make_paper("2401.08888", "HTML paper", abstract="ignored abstract")

    ft = fetch_fulltext(paper, http, config)

    assert ft.source == "html"
    titles = [s.title for s in ft.sections]
    assert "Introduction" in titles
    assert "Limitations" in titles
    body = {s.title: s.text for s in ft.sections}
    assert "Pointer networks" in body["Introduction"]
