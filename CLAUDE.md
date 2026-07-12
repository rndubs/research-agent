# CLAUDE.md — orientation for Claude Code / Cowork

`research-agent` is an **ongoing arXiv research monitor**: a scheduled, idempotent
five-stage pipeline that turns a broad paper corpus into a prioritized,
deduplicated backlog for a *narrow* ML problem. It ships configured for the
**hexgen** problem (neural B-rep → hexproj program generation); retargeting is a
one-file change (`config/hexgen.yaml`).

## Run it

```bash
python -m pip install -e ".[dev]"   # SessionStart hook already does the base install
python -m pytest                    # 42 tests, fully offline (no network/keys/models)
research-agent run -c config/hexgen.yaml     # full pipeline
research-agent backlog -c config/hexgen.yaml # ranked backlog
research-agent status -c config/hexgen.yaml
```

The pipeline is **offline-first**: with no API key and no torch it still runs end
to end (deterministic `MockLLM` + `HashingEmbedder`). That's why the tests are
hermetic — keep them that way.

## The five stages (each owns a subpackage)

`source` → `filter` → `extract` → `score` → `deliver`

| Stage | Package | Entry point |
|---|---|---|
| 1 harvest + enrich | `research_agent/sourcing/` | `stage1_source` |
| 2 relevance cascade | `research_agent/relevance/` | `stage2_relevance` |
| 3 parse + claim extraction | `research_agent/parsing/`, `extraction/` | `stage3_extract` |
| 4 RICE scoring + deps | `research_agent/scoring/` | `stage4_score` |
| 5 dedup + digest | `research_agent/delivery/` | `stage5_deliver` |

Orchestration is `pipeline.py`; CLI is `cli.py`. Design: `docs/ARCHITECTURE.md`.
Module boundaries: `docs/CONTRACTS.md`.

## Invariants (please preserve)

- **Foundation is stable contract.** `models.py`, `config.py`, `db.py`, `http.py`,
  `filters.py`, `llm/`, `embeddings/`, `sourcing/base.py` are depended on by every
  stage — change them deliberately and update `docs/CONTRACTS.md`.
- **Offline-first.** Every path must work with `MockLLM` + `HashingEmbedder` + no
  network. Real providers behind lazy imports / feature flags; degrade, don't crash.
- **Provenance is mandatory** for extracted claims (`FieldProvenance` per field).
  Keep the extraction schema flat (LLMs fail on nested schemas).
- **Tests stay hermetic.** No network, no keys, no model downloads. Use the
  fixtures in `tests/conftest.py`.
- **One narrow problem = one config.** Stage 0 (`config/hexgen.yaml`) is the anchor
  against backlog drift; don't scatter problem-specific logic into code.

## LLM backend is selectable (`llm.provider`)

- `anthropic` — direct API (needs `ANTHROPIC_API_KEY`).
- `batch` — **the Claude Code agent is the LLM** (Cowork nightly, no key), via a
  `batch-plan` → answer → `batch-apply` file handoff. See `docs/NIGHTLY.md`.
- `mock` — deterministic offline stub.

## Nightly in Cowork (how this repo is meant to run)

- Config: `config/hexgen-nightly.yaml` (`provider: batch`, state under `state/`).
  It `extends: hexgen.yaml`, overriding only the provider + paths.
- **Persistence: git.** State (`state/hexgen.db`) and outputs (`state/output/`) are
  git-tracked and committed each run, so the backlog survives the ephemeral
  container and accumulates. (The default `data/`+`output/` are gitignored.)
- **Dashboard: GitHub Pages.** `scripts/publish_pages.sh` copies the rendered
  digest to `docs/index.html`; point Pages at this branch, folder `/docs`.
- Skill: **`/nightly-monitor`** runs the whole cycle. `/retarget-problem` points
  the monitor at a new research area.

To do the nightly run by hand: follow the `nightly-monitor` skill, or the
step-by-step in `docs/NIGHTLY.md`.
