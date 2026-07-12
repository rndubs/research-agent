"""arXiv harvesting via the Atom query API.

:class:`ArxivSource` is the pipeline's primary :class:`PaperSource`. It queries
the public arXiv Atom API (``export.arxiv.org/api/query``) for the configured
categories, newest-first, and parses each ``<entry>`` into a :class:`Paper` with
``status=SEEN``. Parsing is factored into :meth:`ArxivSource._parse_atom` so it
can be unit-tested against an inline feed with no network.

The OAI-PMH ``oai_set`` knob is accepted for selective harvesting parity with
the config but the query API is the default (and only) path here; it degrades to
the full category query when unset.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from dateutil import parser as date_parser

from ..http import HttpClient
from ..models import Paper, PaperStatus
from .base import PaperSource

logger = logging.getLogger(__name__)

QUERY_URL = "http://export.arxiv.org/api/query"

# Atom + arXiv-schema namespaces used throughout the feed.
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# arXiv abstract URL -> (id, version); e.g. .../abs/2409.13740v2 -> ('2409.13740', 2).
_ID_RE = re.compile(r"^(?P<id>.+?)v(?P<version>\d+)$")


def _parse_arxiv_id(id_url: str) -> tuple[str, int]:
    """Split an arXiv ``<id>`` URL into a version-stripped id and version int."""
    tail = (id_url or "").rsplit("/abs/", 1)[-1].strip()
    m = _ID_RE.match(tail)
    if m:
        return m.group("id"), int(m.group("version"))
    return tail, 1


def _parse_dt(text: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp into an aware UTC datetime (or None)."""
    if not text or not text.strip():
        return None
    try:
        dt = date_parser.isoparse(text.strip())
    except (ValueError, OverflowError, TypeError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _clean(text: str | None) -> str:
    """Collapse arXiv's line-wrapped whitespace into single spaces."""
    return " ".join((text or "").split())


class ArxivSource(PaperSource):
    """Harvest new papers from the arXiv Atom query API, newest-first."""

    name = "arxiv"

    def __init__(
        self,
        http: HttpClient,
        categories: list[str],
        oai_set: str | None = None,
    ) -> None:
        self._http = http
        self.categories = list(categories)
        self.oai_set = oai_set

    # -- harvesting ------------------------------------------------------- #
    def _search_query(self) -> str:
        cats = self.categories or ["cs.LG"]
        return " OR ".join(f"cat:{c}" for c in cats)

    def harvest(
        self,
        *,
        since: datetime | None = None,
        max_results: int = 200,
    ) -> Iterator[Paper]:
        """Yield up to ``max_results`` papers, skipping any older than ``since``.

        Results are requested sorted by submission date descending and paged in
        blocks; a short page (fewer entries than requested) signals the end of
        the result set. Network/parse failures are logged and end the harvest
        rather than crashing the run.
        """
        search_query = self._search_query()
        page_size = 100
        fetched = 0
        start = 0

        while fetched < max_results:
            want = min(page_size, max_results - fetched)
            params = {
                "search_query": search_query,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "start": start,
                "max_results": want,
            }
            try:
                xml_text = self._http.get_text(QUERY_URL, params=params)
            except Exception as exc:  # network, HTTP status, timeout
                logger.warning("arXiv harvest request failed at start=%d: %s", start, exc)
                return

            try:
                papers = self._parse_atom(xml_text)
            except ET.ParseError as exc:
                logger.warning("arXiv feed parse failed at start=%d: %s", start, exc)
                return

            if not papers:
                return

            for paper in papers:
                # Post-filter: drop entries submitted before the harvest cursor.
                if since is not None and paper.published is not None and paper.published < since:
                    continue
                yield paper

            fetched += len(papers)
            start += len(papers)
            # A short page means we've exhausted the query results.
            if len(papers) < want:
                return

    # -- parsing (network-free, unit-testable) ---------------------------- #
    @staticmethod
    def _parse_atom(xml_text: str) -> list[Paper]:
        """Parse an arXiv Atom feed string into a list of :class:`Paper`."""
        root = ET.fromstring(xml_text)
        papers: list[Paper] = []

        for entry in root.findall("atom:entry", NS):
            id_url = entry.findtext("atom:id", "", NS) or ""
            arxiv_id, version = _parse_arxiv_id(id_url)
            if not arxiv_id:
                continue

            title = _clean(entry.findtext("atom:title", "", NS))
            abstract = (entry.findtext("atom:summary", "", NS) or "").strip()

            authors: list[str] = []
            for author in entry.findall("atom:author", NS):
                name = _clean(author.findtext("atom:name", "", NS))
                if name:
                    authors.append(name)

            categories: list[str] = []
            for cat in entry.findall("atom:category", NS):
                term = cat.get("term")
                if term and term not in categories:
                    categories.append(term)

            published = _parse_dt(entry.findtext("atom:published", None, NS))
            updated = _parse_dt(entry.findtext("atom:updated", None, NS))

            pdf_url: str | None = None
            html_url: str | None = None
            for link in entry.findall("atom:link", NS):
                href = link.get("href")
                if not href:
                    continue
                if link.get("type") == "application/pdf" or link.get("title") == "pdf":
                    pdf_url = href
                elif link.get("rel") == "alternate" and link.get("type") == "text/html":
                    html_url = href
            if pdf_url is None:
                pdf_url = f"http://arxiv.org/pdf/{arxiv_id}"
            if html_url is None:
                html_url = f"https://arxiv.org/abs/{arxiv_id}"

            doi = entry.findtext("arxiv:doi", None, NS)

            papers.append(
                Paper(
                    arxiv_id=arxiv_id,
                    version=version,
                    doi=doi or None,
                    title=title,
                    abstract=abstract,
                    authors=authors,
                    categories=categories,
                    published=published,
                    updated=updated,
                    pdf_url=pdf_url,
                    html_url=html_url,
                    status=PaperStatus.SEEN,
                    source="arxiv",
                )
            )

        return papers
