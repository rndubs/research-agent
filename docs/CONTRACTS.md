# Module contracts

This file is the source of truth for how the pieces of `research-agent` fit
together. The **foundation** (below) is already implemented and frozen — build
against it, do not modify it. Each pipeline stage exposes exactly one
`stageN_*` entry point with the signature given here; the orchestrator
(`research_agent/pipeline.py`) calls them in order and nothing else.

## Data models (`research_agent/models.py`) — FROZEN

- `Paper` — canonical record. Primary key is `paper.id` (== version-stripped
  `arxiv_id`). `status: PaperStatus` drives idempotency.
- `PaperStatus` — `SEEN → (RELEVANT | IRRELEVANT) → PARSED → EXTRACTED → SCORED`;
  `ARCHIVED` terminal.
- `RelevanceResult` — `{paper_id, relevant, score∈[0,1], rationale, method}`.
- `FullText`, `Section`, `Chunk` — parsed full text.
- `Extraction` — the FLAT claim schema (mirrors compass artifact §3). Every
  substantive field has an entry in `provenance: dict[str, FieldProvenance]`.
- `RiceComponents` — `{expected_impact, applicability, confidence, effort>0}`,
  `.score() = impact*applicability*confidence/effort`.
- `BacklogItem` — `{id, paper_id, title, description, rice, score, foundational,
  dependencies, status}`.
- `DependencyEdge` — `{src, dst, source, paper_id}` (`src` builds on `dst`).
- `Digest` — rendered delivery artifact.

## Foundation services — FROZEN, import and use

| Thing | Import | Notes |
|---|---|---|
| Config | `from research_agent.config import Config` | `Config.load(path)` / `Config.from_dict(d)` |
| Storage | `from research_agent.db import Database` | see method list in `db.py` |
| LLM | `from research_agent.llm import LLMClient, get_llm, MockLLM, build_stub` | `.complete(prompt,...)->str`, `.structured(prompt, schema, ...)->schema instance` |
| Embeddings | `from research_agent.embeddings import Embedder, get_embedder, cosine_similarity, l2_normalize` | `.embed(list[str])->(n,dim) float32`, `.embed_one(str)`; `Embedder.paper_text(title, abstract)` |
| HTTP | `from research_agent.http import HttpClient` | `.get_json/.get_text/.get_bytes/.get/.post`; retries transport errors only |
| Keyword filter | `from research_agent.filters import keyword_prefilter, keyword_hits` | `keyword_prefilter(paper, config)->(passed, score, matched)` |
| Sourcing ABCs | `from research_agent.sourcing.base import PaperSource, Enricher` | implement these |

`LLMClient.structured(prompt, schema)` forces the model to return a **valid
instance of `schema`** (a pydantic model). In tests use `MockLLM` — configure it
with `structured_responses={"SchemaName": instance_or_dict_or_callable}` or a
`handler(kind, prompt, schema, system)`. `build_stub(Schema, **overrides)` makes
a valid throwaway instance.

## Stage entry points — IMPLEMENT THESE EXACTLY

```python
# research_agent/sourcing/__init__.py
def stage1_source(config: Config, db: Database, http: HttpClient,
                  *, since: datetime | None = None) -> list[Paper]: ...
    # harvest arXiv (ArxivSource) since last_harvest, optional keyword prefilter,
    # enrich via Semantic Scholar / OpenAlex, upsert NEW papers as status SEEN,
    # update db.set_last_harvest(...). Return the newly-added papers.

# research_agent/relevance/__init__.py
def stage2_relevance(config: Config, db: Database,
                     embedder: Embedder, llm: LLMClient) -> list[Paper]: ...
    # For SEEN papers run the cascade: keyword_prefilter -> embedding similarity to
    # the seed-set centroid (store embeddings) -> LLM classifier on the shortlist.
    # Set status RELEVANT / IRRELEVANT and relevance_score / rationale / method.
    # Return papers marked RELEVANT this run.

# research_agent/extraction/__init__.py
def stage3_extract(config: Config, db: Database,
                   llm: LLMClient, http: HttpClient) -> list[Extraction]: ...
    # For RELEVANT papers: fetch full text (HTML/PDF/GROBID or abstract fallback),
    # chunk, run schema-constrained LLM extraction into Extraction WITH provenance,
    # persist (db.save_extraction), set status EXTRACTED. Return extractions.

# research_agent/scoring/__init__.py
def stage4_score(config: Config, db: Database, llm: LLMClient) -> list[BacklogItem]: ...
    # Turn each EXTRACTED paper's Extraction into >=1 BacklogItem with RICE
    # components (LLM-estimated impact/applicability/effort; confidence from
    # evidence + provenance completeness + citations w/ recency grace). Build the
    # dependency graph (citation + extracted deps), reserve the foundational lane,
    # persist items + edges, set status SCORED. Return items.

# research_agent/delivery/__init__.py
def stage5_deliver(config: Config, db: Database) -> Digest: ...
    # Dedup (arxiv_id/doi + title fuzzy), render ranked backlog + a windowed
    # digest (markdown + optional HTML via jinja2), write to config output dir,
    # return the Digest.
```

## Conventions

- **Never modify foundation files** (`models.py`, `config.py`, `db.py`, `http.py`,
  `filters.py`, `llm/`, `embeddings/`, `sourcing/base.py`) or another stage's
  files. Add your own files inside your subpackage.
- **Offline-first.** Every code path must work with `MockLLM` +
  `HashingEmbedder` + no network. Real providers behind lazy imports / feature
  flags; degrade gracefully (log + fallback), never crash a run because an
  optional service is down.
- **Provenance is mandatory** for extracted claims — never assert a field without
  a `FieldProvenance`. Keep the extraction schema flat; validate with pydantic;
  add a recovery pass for malformed output.
- **Tests**: put them in `tests/test_<area>.py`, use the fixtures in
  `tests/conftest.py` (`config`, `db`, `mock_llm`, `hashing_embedder`,
  `mock_http_factory`, `sample_papers`, `make_paper`). Tests must pass with
  `python -m pytest` and touch no network.
- Report `k/N` with intervals where relevant; compare against a naive baseline.
  Confine LLM use to bounded sub-tasks.
