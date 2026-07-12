---
name: retarget-problem
description: Point the research-agent monitor at a NEW narrow research problem. Use when asked to retarget the monitor, monitor a different research area/topic, create a new config for another problem, or change what the agent considers relevant. Walks through editing Stage 0 (problem statement, seed papers, keyword taxonomy) — the only thing that changes to monitor a different subject.
---

# Retarget the monitor to a new problem

The architecture is problem-agnostic. To monitor a different narrow ML problem you
change **only Stage 0** — a config file — not any code.

## Steps

1. **Copy the reference config:** `cp config/hexgen.yaml config/<name>.yaml`.

2. **Rewrite the Stage-0 fields** in the new file (these are the anchor against
   backlog drift — get them right):
   - `name`: a short slug.
   - `problem_statement`: a rich natural-language description of the problem and,
     crucially, an explicit list of what makes a paper RELEVANT vs NOT (the LLM
     judges every paper against this). Mirror the structure of the hexgen one.
   - `seed_papers`: 10–50 hand-picked arXiv ids that define the relevance centroid.
     Curate them (Connected Papers / ResearchRabbit are good for this). Ids are
     version-stripped, e.g. `"2409.13740"`.
   - `include_keywords` / `taxonomy_terms`: cheap-prefilter terms that on-domain
     papers hit. `exclude_keywords`: obvious off-domain noise (keep short so you
     don't kill signal).
   - `sourcing.arxiv_categories`: the arXiv sets to harvest (e.g. cs.LG, cs.CV).

3. **Tune thresholds if needed** (usually leave defaults): `relevance.embedding_threshold`
   (calibrated for SPECTER2; the hashing fallback auto-lowers it),
   `scoring.foundational_reserved_slots`, `delivery.top_n`.

4. **Dry-run offline** to sanity-check the plumbing (uses MockLLM + hashing):
   ```bash
   research-agent run -c config/<name>.yaml       # provider defaults to anthropic->mock w/o key
   research-agent backlog -c config/<name>.yaml
   ```
   For a *meaningful* dry run with real judgments, set `ANTHROPIC_API_KEY` and
   `llm.provider: anthropic`, or use the batch flow (see `/nightly-monitor`).

5. **For a nightly Cowork setup**, add a thin nightly variant that inherits it:
   ```yaml
   # config/<name>-nightly.yaml
   extends: <name>.yaml
   llm: { provider: batch, batch_dir: state/<name>/batch }
   storage: { db_path: state/<name>/<name>.db }
   delivery: { output_dir: state/<name>/output }
   ```

## Guardrails
- Keep problem-specific logic in the config, never in code.
- Every relevance judgment and the `applicability_to_our_problem` extraction field
  are anchored to `problem_statement` — vague statements produce a noisy backlog.
- Verify offline (`python -m pytest`) still passes after adding the config.
