# Architecture

`research-agent` implements the reference architecture for an *ongoing
monitor → structured, prioritized, deduplicated backlog* for a narrow ML
problem. It is a **scheduled, idempotent five-stage pipeline** — deliberately not
an AutoGPT-style open-ended agent loop — with LLM "agent" behavior confined to
the narrow, well-bounded steps where it demonstrably works: relevance judgment,
claim extraction, and effort/impact estimation.

The design borrows *components* from PaperQA2 (GROBID full-text parse + retrieve
+ contextual summarization + hard provenance), OpenScholar (grounded,
citation-anchored synthesis), ResearchAgent (citation-graph traversal), and
arxiv-sanity-lite (cron-polled incremental harvest + per-topic scoring). No
off-the-shelf system does this exact pattern, so this is an integration project.

## Design principles

1. **Deterministic orchestration, bounded LLM use.** The top-level control flow
   is a plain pipeline. LLMs are called only inside stages, always with a fixed
   rubric or a flat, schema-constrained output. This removes the nondeterminism,
   cost, and failure surface of open-ended loops.
2. **Grounding + provenance are mandatory.** GPT-4o fabricated citations in
   78–90% of cases *without retrieval* (OpenScholar, Nature 2025). Every
   extracted claim field carries a `FieldProvenance` (section + supporting
   quote). A field without grounding is dropped, not asserted.
3. **Cheap → expensive cascade.** Screening at scale must be cheap; full-text
   processing is expensive (cents to dollars per hundred papers, up to thousands
   for OCR at volume). So: keyword prefilter → embedding similarity → LLM on a
   shortlist → full-text extraction only for survivors.
4. **Anchor against drift.** Every relevance judgment is made against a *fixed*
   `problem_statement` + seed set (Stage 0). The extraction forces an
   `applicability_to_our_problem` field and items that can't articulate it are
   dropped. This is the guard against backlog bloat.
5. **Fight recency bias explicitly.** LLM relevance/ranking systematically
   over-favors recent, highly-cited, short-title papers (a Matthew effect across
   ~275k generated references). We reserve backlog capacity for high-citation
   foundational papers and never gate *recent* papers on citation count.
6. **Idempotent and swappable.** Processing state lives on `papers.status`; every
   stage only advances new work. The sourcing layer is abstracted so a provider
   can be swapped (the Papers With Code shutdown is the cautionary tale).
7. **Offline-first.** With no API key / no torch, `MockLLM` + `HashingEmbedder`
   keep the whole pipeline runnable and the test suite hermetic.

## Stage 0 — Problem definition (`config/hexgen.yaml`)

Encodes the narrow problem as (a) a natural-language `problem_statement` for LLM
relevance judging, (b) a hand-curated `seed_papers` set defining the relevance
centroid, and (c) a keyword/taxonomy prefilter + arXiv categories. This is the
anchor referenced by every downstream judgment.

## Stage 1 — Incremental sourcing (`research_agent/sourcing/`)

- **Primary source:** arXiv (Atom query API; OAI-PMH set-harvesting optional).
  The last-harvest datestamp is persisted (`db.set_last_harvest`) for incremental
  pulls; only *new* papers (by version-stripped id) are processed.
- **Enrichment:** Semantic Scholar (citations, influential citations, TLDR,
  fields of study, corpus id, references → dependency graph) and OpenAlex
  (topics, OA status, cited-by cross-check). Both are best-effort and tolerate
  missing coverage — brand-new arXiv papers legitimately lack citation data.
- A keyword prefilter bounds the corpus at harvest time.

## Stage 2 — Relevance filtering (`research_agent/relevance/`)

A cheap→expensive cascade over `SEEN` papers:

1. **Keyword/taxonomy prefilter** (`filters.keyword_prefilter`) — an exclude-term
   hit drops the paper immediately.
2. **Embedding similarity** — SPECTER2 (or the hashing fallback) scores each
   survivor against the seed-set centroid (mean of the problem statement +
   resolvable seed papers). Below `embedding_threshold` ⇒ `IRRELEVANT`.
   Embeddings are persisted for reuse and semantic search.
3. **LLM classification** — only the top `embedding_shortlist` survivors are
   judged by the LLM against the problem statement with a rubric, returning a
   `{relevant, score, rationale}`. Survivors above the dense threshold but beyond
   the shortlist are kept as relevant-by-embedding (no LLM spend).

## Stage 3 — Full-text parse + claim extraction (`research_agent/parsing/`, `research_agent/extraction/`)

Runs on `RELEVANT` papers only.

- **Parse:** GROBID (TEI/XML sections/tables/refs) when a service is configured;
  otherwise arXiv HTML (ar5iv, which avoids PDF-parse errors); otherwise
  abstract-only. Full text is chunked by section, with limitation-bearing
  sections (Discussion/Limitations/Future Work) always retained.
- **Extract:** a flat, schema-constrained LLM extraction into `Extraction`
  (`problem_addressed`, `method_summary`, `key_architecture_choices`, `datasets`,
  `metrics`, `headline_results`, `claimed_advantages`, `limitations`,
  `applicability_to_our_problem`, `implementation_cost_estimate`,
  `dependencies_on_other_methods`, `code_link`). The schema is intentionally flat
  (LLMs degrade on nested schemas); output is validated with pydantic with a
  recovery pass. **Every substantive field carries a provenance quote.**
  Re-extraction is gated on a section-text hash so unchanged versions are skipped.

## Stage 4 — Backlog scoring (`research_agent/scoring/`)

- **RICE-derived score:** `Score = ExpectedImpact × Applicability × Confidence /
  Effort`, adapted so Reach/Impact become expected impact *on our metric*,
  Confidence becomes evidence/extraction quality (code availability, provenance
  completeness, extraction confidence, citations with recency grace), and Effort
  is implementation cost. Impact/applicability/effort are LLM-estimated;
  confidence is computed deterministically.
- **Dependency graph:** edges from citation references and from extracted
  `dependencies_on_other_methods`; a topological order surfaces foundational
  techniques before the papers that build on them.
- **Foundational lane:** high-citation papers predating the recency window are
  flagged so the delivery step can reserve slots for them.

## Stage 5 — Dedup + delivery (`research_agent/delivery/`)

- **Deduplication:** exact keys (DOI, corpus id) + near-duplicate title fuzzy
  match with author overlap (catches v1-preprint vs published). The stronger
  record is kept; the weaker's backlog item is archived.
- **Delivery:** a ranked backlog view (`backlog.md`) that guarantees the reserved
  foundational slots, plus a windowed digest (`digest.md` / `digest.html`) of
  newly-added high-scoring items.

## Storage (`research_agent/db.py`)

A single SQLite file per the compass-artifact decision threshold (skip the
vector/graph DBs while relevant volume is low): paper metadata + status,
embeddings (float32 blobs), extracted claims (JSON), backlog items, a dependency
edge table, a key/value state store (last-harvest datestamp, sealed-set
consultation counters), and an append-only audit log.

## How this targets `hexgen`

Only Stage 0 changes to retarget the monitor. For `hexgen` the config points the
relevance model at the literature that could move the track's live frontier —
**structural validity of generated programs** (constrained/execution-guided
decoding, value-guided search, repair/DAgger distillation), **domain gap /
distribution shift**, **B-rep/CAD representation learning**, **pointer/copy +
graph transformers**, **rotation/pose robustness**, and **self-play /
verifier-in-the-loop training**. The `applicability_to_our_problem` extraction
field and the RICE applicability weight are what keep the backlog tied to "does
this actually help generate valid hexproj programs from a B-rep", rather than
generic ML novelty.

## Scaling knobs (when to grow past this)

- < ~5 relevant papers/day: SQLite + the in-DB vector store suffice.
- > ~50 relevant/day or multiple problems: adopt a real vector DB (Qdrant /
  LanceDB / pgvector) + a graph DB (Neo4j) + an orchestrator (Prefect / Dagster)
  for retries, backfills, and observability. The stage boundaries here are the
  DAG nodes you'd lift into that orchestrator unchanged.
- Faithfulness spot-checks < ~90%: shrink the extraction schema and/or move to a
  stronger extraction model before scaling volume.
