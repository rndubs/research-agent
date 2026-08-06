"""Full-text acquisition with a graceful fallback chain.

``fetch_fulltext`` tries the configured strategy first and *always* degrades to
an abstract-only :class:`FullText` rather than raising, so Stage 3 runs offline
and never crashes because an optional service (GROBID / ar5iv) is down:

    (a) GROBID  — fetch the PDF and parse TEI            (config.extraction.use_grobid)
    (b) HTML    — fetch ar5iv HTML and parse into sections (config.extraction.prefer_html)
    (c) abstract — a single ``Abstract`` section from ``paper.abstract``

HTML is parsed with the stdlib :mod:`html.parser` so no third-party dependency is
required; headings ``<h1>``-``<h3>`` delimit sections and ``<script>``/``<style>``
content is dropped.
"""

from __future__ import annotations

from html.parser import HTMLParser

from ..config import Config
from ..http import HttpClient
from ..models import FullText, Paper, Section
from .grobid import GrobidClient

# Tags whose textual content should never appear in a section body.
_SKIP_TAGS = {"script", "style", "noscript", "head"}
# Section-delimiting headings.
_HEADING_TAGS = {"h1", "h2", "h3"}
# Block-level tags used only to insert whitespace so adjacent nodes don't fuse.
_BLOCK_TAGS = {
    "p", "div", "section", "article", "li", "ul", "ol", "tr", "td", "th",
    "table", "br", "blockquote", "figure", "figcaption", "header", "footer",
    "aside", "main", "nav", "pre", "h4", "h5", "h6", "dd", "dt", "dl",
}


class _SectionParser(HTMLParser):
    """Group flowing HTML text into ``Section``s delimited by h1-h3 headings."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[Section] = []
        self._skip_depth = 0
        self._in_heading = False
        self._heading_parts: list[str] = []
        self._body_parts: list[str] = []
        self._current_title = ""

    # -- section flushing ------------------------------------------------- #
    def _flush_section(self) -> None:
        text = " ".join("".join(self._body_parts).split())
        title = " ".join(self._current_title.split())
        if title or text:
            self.sections.append(Section(title=title, text=text))
        self._body_parts = []
        self._current_title = ""

    def _sep(self) -> None:
        if self._skip_depth:
            return
        if self._in_heading:
            self._heading_parts.append(" ")
        else:
            self._body_parts.append(" ")

    # -- HTMLParser hooks -------------------------------------------------- #
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in _HEADING_TAGS:
            # A new heading closes the section that preceded it.
            self._flush_section()
            self._in_heading = True
            self._heading_parts = []
            return
        if tag in _BLOCK_TAGS:
            self._sep()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in _HEADING_TAGS and self._in_heading:
            self._current_title = " ".join("".join(self._heading_parts).split())
            self._in_heading = False
            self._heading_parts = []
            return
        if tag in _BLOCK_TAGS:
            self._sep()

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_heading:
            self._heading_parts.append(data)
        else:
            self._body_parts.append(data)

    def close(self):
        super().close()
        # Emit whatever trailed the last heading.
        self._flush_section()


def parse_html_sections(html: str) -> list[Section]:
    """Parse an HTML document into ``Section``s grouped by h1-h3 headings.

    Robust to messy markup; ``<script>``/``<style>`` are stripped. Text before
    the first heading becomes a leading untitled section.
    """
    if not html:
        return []
    parser = _SectionParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # Best-effort: return whatever we managed to accumulate.
        pass
    return parser.sections


def _fetch_html(paper: Paper, http: HttpClient) -> str | None:
    """Fetch arXiv HTML, trying arXiv's own native renderer then the ar5iv mirrors.

    arXiv absorbed ar5iv's LaTeXML rendering into ``arxiv.org/html/<id>`` directly,
    so that's tried first (also the only host reachable from some sandboxed network
    policies, where the standalone ar5iv hosts are unresolvable); the legacy ar5iv
    hosts remain as a fallback for older ids they may still cover.
    """
    urls = [
        f"https://arxiv.org/html/{paper.id}",
        f"https://ar5iv.labs.arxiv.org/html/{paper.id}",
        f"https://ar5iv.org/abs/{paper.id}",
    ]
    for url in urls:
        try:
            text = http.get_text(url)
            if text:
                return text
        except Exception:
            continue
    return None


def _abstract_fulltext(paper: Paper) -> FullText:
    return FullText(
        paper_id=paper.id,
        sections=[Section(title="Abstract", text=paper.abstract)],
        source="abstract",
    )


def fetch_fulltext(paper: Paper, http: HttpClient, config: Config) -> FullText:
    """Acquire a paper's full text, degrading to abstract-only on any failure."""
    ex = config.extraction

    # (a) GROBID: fetch the PDF, hand the bytes to GROBID for TEI parsing.
    if ex.use_grobid:
        try:
            pdf_url = paper.pdf_url or f"http://arxiv.org/pdf/{paper.id}"
            pdf_bytes = http.get_bytes(pdf_url)
            sections = GrobidClient(ex.grobid_url, http).process_pdf(pdf_bytes)
            if sections:
                return FullText(paper_id=paper.id, sections=sections, source="grobid")
        except Exception:
            pass  # fall through to abstract

    # (b) HTML: ar5iv rendering avoids brittle PDF parsing.
    elif ex.prefer_html:
        try:
            html = _fetch_html(paper, http)
            if html:
                sections = parse_html_sections(html)
                if sections:
                    return FullText(paper_id=paper.id, sections=sections, source="html")
        except Exception:
            pass  # fall through to abstract

    # (c) Abstract-only fallback (also the default when no strategy is enabled).
    return _abstract_fulltext(paper)
