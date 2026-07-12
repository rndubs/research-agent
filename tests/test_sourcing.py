"""Stage 1 (Sourcing) tests — arXiv parsing, the end-to-end flow, and graceful
degradation. All hermetic: the network is an ``httpx.MockTransport`` handler.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from research_agent.db import Database
from research_agent.models import PaperStatus
from research_agent.sourcing import (
    OpenAlexEnricher,
    SemanticScholarEnricher,
    stage1_source,
)
from research_agent.sourcing.arxiv_source import ArxivSource

# --------------------------------------------------------------------------- #
# Canned provider payloads
# --------------------------------------------------------------------------- #
ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2409.13740v2</id>
    <updated>2024-09-25T10:00:00Z</updated>
    <published>2024-09-20T09:30:00Z</published>
    <title>Pointer Networks over B-rep Graphs for Hex Mesh
      Program Synthesis</title>
    <summary>  We decode a hex meshing DSL program from a B-rep face graph using a
pointer network and a graph transformer.  </summary>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
    <arxiv:doi>10.1234/hexgen.2024</arxiv:doi>
    <link href="http://arxiv.org/abs/2409.13740v2" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2409.13740v2" rel="related" type="application/pdf"/>
    <arxiv:primary_category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.GR" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2408.00002v1</id>
    <updated>2024-08-02T10:00:00Z</updated>
    <published>2024-08-01T09:30:00Z</published>
    <title>A Recommender System for Streaming Movies</title>
    <summary>Collaborative filtering with matrix factorization, a recommender system.</summary>
    <author><name>Grace Hopper</name></author>
    <link href="http://arxiv.org/abs/2408.00002v1" rel="alternate" type="text/html"/>
    <category term="cs.IR" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2407.55555v1</id>
    <updated>2024-07-10T10:00:00Z</updated>
    <published>2024-07-09T09:30:00Z</published>
    <title>Equivariant CAD Encoders for Program Synthesis</title>
    <summary>An equivariant graph transformer over CAD solid models for program synthesis.</summary>
    <author><name>Katherine Johnson</name></author>
    <category term="cs.CV" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>
"""

S2_JSON = {
    "citationCount": 42,
    "influentialCitationCount": 7,
    "tldr": {"model": "tldr@v2", "text": "Decodes hex meshing programs from B-reps."},
    "fieldsOfStudy": ["Computer Science", "Engineering"],
    "externalIds": {"ArXiv": "2409.13740", "DOI": "10.1234/hexgen.2024", "CorpusId": 99999},
    "references": [
        {"externalIds": {"ArXiv": "1506.03134", "CorpusId": 111}},
        {"externalIds": {"CorpusId": 222}},
        {"externalIds": {}},
    ],
}

OPENALEX_WORK = {
    "id": "https://openalex.org/W123456",
    "cited_by_count": 55,
    "open_access": {"is_oa": True},
    "concepts": [{"display_name": "Mesh generation"}, {"display_name": "Computer science"}],
    "topics": [{"display_name": "Geometric deep learning"}],
}


def _router(request: httpx.Request) -> httpx.Response:
    """Route by host to the appropriate canned provider payload."""
    host = request.url.host
    path = request.url.path
    if host == "export.arxiv.org":
        return httpx.Response(200, text=ATOM_FEED)
    if host == "api.semanticscholar.org":
        if path.startswith("/graph/"):
            return httpx.Response(200, json=S2_JSON)
        return httpx.Response(200, json={"recommendedPapers": []})
    if host == "api.openalex.org":
        return httpx.Response(200, json=OPENALEX_WORK if "doi.org" in str(request.url)
                              else {"results": [OPENALEX_WORK]})
    return httpx.Response(404, json={"error": "not found"})


# --------------------------------------------------------------------------- #
# _parse_atom
# --------------------------------------------------------------------------- #
def test_parse_atom_extracts_fields():
    papers = ArxivSource._parse_atom(ATOM_FEED)
    assert len(papers) == 3

    p1 = papers[0]
    assert p1.arxiv_id == "2409.13740"
    assert p1.version == 2
    assert p1.title == "Pointer Networks over B-rep Graphs for Hex Mesh Program Synthesis"
    assert "pointer network" in p1.abstract.lower()
    assert p1.authors == ["Ada Lovelace", "Alan Turing"]
    assert p1.categories == ["cs.LG", "cs.GR"]
    assert p1.doi == "10.1234/hexgen.2024"
    assert p1.pdf_url == "http://arxiv.org/pdf/2409.13740v2"
    assert p1.html_url == "http://arxiv.org/abs/2409.13740v2"
    assert p1.status == PaperStatus.SEEN
    assert p1.source == "arxiv"
    # Aware UTC datetimes.
    assert p1.published == datetime(2024, 9, 20, 9, 30, tzinfo=timezone.utc)
    assert p1.updated == datetime(2024, 9, 25, 10, 0, tzinfo=timezone.utc)

    # v1 default id, and a missing pdf link falls back to the canonical URL.
    p3 = papers[2]
    assert p3.arxiv_id == "2407.55555"
    assert p3.version == 1
    assert p3.pdf_url == "http://arxiv.org/pdf/2407.55555"
    assert p3.html_url == "https://arxiv.org/abs/2407.55555"


# --------------------------------------------------------------------------- #
# stage1_source end-to-end
# --------------------------------------------------------------------------- #
def test_stage1_source_end_to_end(config, db: Database, mock_http_factory):
    http = mock_http_factory(_router)

    new_papers = stage1_source(config, db, http)

    # The off-domain "recommender system" entry is dropped by the prefilter.
    ids = {p.id for p in new_papers}
    assert ids == {"2409.13740", "2407.55555"}
    assert not db.has_paper("2408.00002")

    # Persisted as SEEN with enrichment folded in.
    stored = db.get_paper("2409.13740")
    assert stored is not None
    assert stored.status == PaperStatus.SEEN
    assert stored.citation_count == 42  # from S2 (OpenAlex does not overwrite)
    assert stored.influential_citation_count == 7
    assert stored.corpus_id == "99999"
    assert stored.tldr and "hex meshing" in stored.tldr
    assert "1506.03134" in stored.reference_ids
    assert "CorpusId:222" in stored.reference_ids
    # OpenAlex enrichment.
    assert stored.openalex_id == "https://openalex.org/W123456"
    assert stored.extra.get("open_access") is True
    assert "Geometric deep learning" in stored.fields_of_study

    # The harvest cursor is advanced to the newest published date seen.
    last = db.get_last_harvest()
    assert last == datetime(2024, 9, 20, 9, 30, tzinfo=timezone.utc)

    # Rerun is idempotent: nothing new, corpus unchanged.
    again = stage1_source(config, db, http)
    assert again == []
    assert db.count_papers() == 2


# --------------------------------------------------------------------------- #
# Graceful degradation on a 404
# --------------------------------------------------------------------------- #
def _not_found(request: httpx.Request) -> httpx.Response:
    return httpx.Response(404, json={"error": "not found"})


def test_semantic_scholar_tolerates_404(config, mock_http_factory, sample_papers):
    http = mock_http_factory(_not_found)
    enricher = SemanticScholarEnricher(http)
    paper = sample_papers[0]
    before = paper.model_dump()
    result = enricher.enrich(paper)  # must not raise
    assert result is paper
    assert result.model_dump() == before


def test_openalex_tolerates_404(config, mock_http_factory, sample_papers):
    http = mock_http_factory(_not_found)
    enricher = OpenAlexEnricher(http)
    paper = sample_papers[0]
    before = paper.model_dump()
    result = enricher.enrich(paper)  # must not raise
    assert result is paper
    assert result.model_dump() == before
