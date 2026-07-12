# research-agent

An **ongoing arXiv research monitor** that turns a broad, incrementally-harvested
paper corpus into a **prioritized, deduplicated backlog of "things to try"** for a
*narrow* ML research problem.

It is a scheduled, idempotent **five-stage pipeline** — not an open-ended agent
loop — with LLM behavior confined to the bounded steps where it demonstrably
works (relevance judging, claim extraction, effort/impact estimation). The design
follows the architecture synthesized from PaperQA2, OpenScholar, ResearchAgent,
and arxiv-sanity-lite (see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)).

This repo ships pre-configured for the **`hexgen`** research problem — a neural
decoder that reads a mechanical part's boundary representation (B-rep) and
generates a `hexproj` hex-meshing program — but the architecture is
problem-agnostic: retarget it by editing one config file
([`config/hexgen.yaml`](config/hexgen.yaml)).

```
                Stage 0: problem statement + seed set + taxonomy (config/hexgen.yaml)
                                     │  (the anchor against backlog drift)
   arXiv OAI/API ─┐                 ▼
   Semantic Sch. ─┼─► 1. SOURCE ─► 2. FILTER ─► 3. EXTRACT ─► 4. SCORE ─► 5. DELIVER
   OpenAlex ──────┘   incremental   keyword→      GROBID/HTML   RICE +      dedup +
                      harvest +     embedding→     + schema-     dependency  ranked backlog
                      enrich        LLM cascade    constrained   graph +     + digest
                                                   extraction    found. lane
```

## Why this shape

- **Sourcing is solved; the hard parts are extraction faithfulness and backlog
  drift.** So the pipeline grounds every extracted claim in a source quote
  (provenance is mandatory), screens abstracts before spending on full text, and
  anchors every relevance judgment to a fixed problem statement + seed set.
- **A cheap→expensive cascade** keeps cost bounded: a keyword/taxonomy prefilter
  kills the bulk, SPECTER2 embedding similarity ranks the rest, and the LLM only
  judges a shortlist.
- **RICE-derived scoring** (`Impact × Applicability × Confidence / Effort`) plus a
  dependency graph surfaces foundational techniques before their descendants, and
  a reserved **foundational lane** counteracts the well-documented recency /
  Matthew-effect bias.

## Install

```bash
python -m pip install -e .            # core pipeline (runs fully offline)
python -m pip install -e ".[llm]"     # + Anthropic Claude client
python -m pip install -e ".[embeddings]"  # + real SPECTER2 embeddings
python -m pip install -e ".[parsing]"     # + PDF/TEI helpers
python -m pip install -e ".[dev]"     # + pytest/ruff/mypy
```

**Offline-first by design.** With no API key and no deep-learning stack the
pipeline still runs end to end: the LLM falls back to a deterministic `MockLLM`
and embeddings fall back to a `HashingEmbedder`. That makes the whole thing
testable with `pytest` and lets you dry-run the plumbing before spending a cent.

To use real models:

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # enables the Claude relevance/extraction/scoring calls
export S2_API_KEY=...                   # optional: higher Semantic Scholar rate limit
```

## Usage

```bash
research-agent init                          # create the SQLite DB
research-agent run                           # full pipeline (source→filter→extract→score→deliver)
research-agent run --stages source,filter    # a subset
research-agent backlog --top 25              # the current ranked backlog
research-agent status                        # counts by processing state
```

Individual stages (`source`, `filter`, `extract`, `score`, `deliver`) run
independently and idempotently, so a cron entry like

```cron
0 7 * * *  cd /path/to/research-agent && research-agent run >> data/cron.log 2>&1
```

is the entire "ongoing monitor". Outputs (ranked `backlog.md`, `digest.md`,
`digest.html`) land in `output/`.

## Configuration (Stage 0)

Everything domain-specific lives in [`config/hexgen.yaml`](config/hexgen.yaml):

| Key | Purpose |
|---|---|
| `problem_statement` | Natural-language anchor the LLM judges relevance against |
| `seed_papers` | Hand-curated arXiv ids defining the relevance centroid |
| `include_keywords` / `exclude_keywords` / `taxonomy_terms` | Cheap prefilter |
| `sourcing.arxiv_categories` | Which arXiv sets to harvest |
| `relevance.*` | Cascade thresholds (embedding cutoff, LLM shortlist size) |
| `extraction.*` | GROBID toggle, HTML preference, chunking |
| `scoring.*` | RICE weights, foundational-lane reservation, recency grace |
| `delivery.*` | Digest window, top-N, output dir |

To monitor a **different** research problem, copy the file, rewrite the Stage-0
fields, and point the CLI at it with `--config`.

## Layout

```
research_agent/
  models.py        # data vocabulary (Paper, Extraction, BacklogItem, RICE) — frozen contract
  config.py        # Stage-0 config
  db.py            # SQLite canonical store + idempotency state machine
  http.py          # shared HTTP client (retries, mockable transport)
  filters.py       # keyword/taxonomy prefilter
  llm/             # LLMClient interface, Anthropic client, deterministic MockLLM
  embeddings/      # Embedder interface, SPECTER2, offline HashingEmbedder
  sourcing/        # Stage 1: arXiv + Semantic Scholar + OpenAlex
  relevance/       # Stage 2: keyword → embedding → LLM cascade
  parsing/         # full-text fetch (GROBID/HTML), chunking
  extraction/      # Stage 3: schema-constrained claim extraction w/ provenance
  scoring/         # Stage 4: RICE + dependency graph + foundational lane
  delivery/        # Stage 5: dedup, ranked backlog, digest
  pipeline.py      # orchestrator
  cli.py           # command-line interface
docs/              # ARCHITECTURE.md, CONTRACTS.md
config/hexgen.yaml # the reference domain configuration
tests/             # hermetic, offline test suite
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the design rationale and
[`docs/CONTRACTS.md`](docs/CONTRACTS.md) for the module boundaries.

## Testing

```bash
python -m pytest        # fully offline; no network, no API key, no model download
```
