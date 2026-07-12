# Running the monitor nightly in Claude Cowork

This guide covers scheduling `research-agent` as a nightly job inside Claude Code
on the web (Cowork), where the natural "LLM" is the Claude Code agent itself.

There are **two ways** the three LLM touchpoints (relevance, extraction, scoring)
get fulfilled — pick one with `llm.provider`:

| `llm.provider` | Who is the LLM | Needs a key? | Command |
|---|---|---|---|
| `anthropic` | The Anthropic API, called by the pipeline | Yes (`ANTHROPIC_API_KEY`) | `research-agent run` |
| `batch` | **The Claude Code agent** (you, at nightly time) | No | `research-agent source` + `batch-plan`/`batch-apply` |
| `mock` | Deterministic stub (dry-run / tests) | No | `research-agent run` |

Everything else in the pipeline (arXiv harvest, embeddings, parsing, dedup, RICE
arithmetic, rendering) is deterministic Python either way.

## Two things that bite you in an ephemeral container

1. **State must be committed.** The nightly container is fresh each run and the
   repo is re-cloned, so the SQLite DB (`last_harvest`, seen papers, the
   accumulated backlog) is lost unless persisted. The nightly config writes to
   `state/` (which is git-tracked — see `.gitignore`) and the nightly job
   **commits `state/` back to the branch**, so the backlog accumulates.
2. **A subprocess can't call the agent.** In `batch` mode the pipeline can't
   synchronously ask "you" for a judgment mid-loop, so it uses a file handoff
   (below).

## Mode A — Direct API (simplest)

Add `ANTHROPIC_API_KEY` as an environment secret in your Cowork environment,
then the nightly job is just:

```bash
research-agent run -c config/hexgen.yaml
git add data/ output/ && git commit -m "nightly: $(date -I)" && git push
```

Here Claude Code only schedules + commits; the pipeline makes its own API calls.
(You'd un-ignore `data/`+`output/` or point the config at `state/` as below.)

## Mode B — Agent-as-LLM (no key), the `batch` flow

Uses `config/hexgen-nightly.yaml` (`llm.provider: batch`, state under `state/`).
The flow is **plan → answer → apply**:

```
research-agent source     -c config/hexgen-nightly.yaml     # harvest (deterministic)

# repeat until batch-plan prints "ready":
research-agent batch-plan -c config/hexgen-nightly.yaml     # emits state/batch/requests.jsonl
#   -> read state/batch/requests.jsonl; for each request produce a JSON object
#      matching its `json_schema`, grounded in its `prompt`; append one line
#      {"key": "<request key>", "payload": {...}} to state/batch/answers.jsonl

research-agent batch-apply -c config/hexgen-nightly.yaml    # runs for real, delivers digest
```

Each `batch-plan` round surfaces one stage's worth of requests (relevance, then
extraction, then scoring) computed against a **throwaway DB snapshot**, so
nothing is committed until `batch-apply`. Cache keys are per-paper, so the loop
converges deterministically and re-runs are idempotent.

### Request / answer file formats

`state/batch/requests.jsonl` (written by `batch-plan`, one JSON object per line):

```json
{"key": "RelevanceJudgment:2405.11111", "schema": "RelevanceJudgment",
 "prompt": "…the full relevance prompt…", "json_schema": { … }}
```

`state/batch/answers.jsonl` (you append; last write for a key wins):

```json
{"key": "RelevanceJudgment:2405.11111", "payload": {"relevant": true, "score": 0.9, "rationale": "…"}}
```

`batch-apply` runs strictly: if any request is unanswered it exits non-zero
rather than committing a stub, so an incomplete loop can't corrupt the backlog.

## Scheduling it (a Routine)

Create a Routine (cron trigger) that fires a **fresh session** nightly and hands
it the standalone prompt below. In this repo you can create it with the
`create_trigger` MCP tool (`create_new_session_on_fire: true`, e.g. cron
`0 7 * * *`). Paste this as the Routine's prompt:

```
You are running the nightly hexgen research monitor in this repo (batch / agent-as-LLM mode).

1. Ensure deps: `python -m pip install -e . >/dev/null 2>&1 || true`.
2. Harvest: `research-agent source -c config/hexgen-nightly.yaml`.
3. Loop until ready: run `research-agent batch-plan -c config/hexgen-nightly.yaml`.
   It prints a JSON status line. If status is "ready", stop looping. Otherwise read
   state/batch/requests.jsonl; for EACH request, produce a JSON object that satisfies
   its `json_schema`, judged ONLY from its `prompt` (ground every field; leave a field
   empty if the text doesn't support it), and append one line
   {"key": "<request key>", "payload": {...}} to state/batch/answers.jsonl. Then re-run
   batch-plan. Cap at ~6 rounds.
4. Apply: `research-agent batch-apply -c config/hexgen-nightly.yaml`.
5. Commit state so it survives to tomorrow:
   `git add state/ && git commit -m "nightly monitor: $(date -I)" && git push -u origin <this branch>`.
6. Reply with the top new backlog items from state/output/digest.md (or say "no new items").

You ARE the LLM for the relevance/extraction/scoring judgments — answer them as
carefully as you would in an interactive session, anchored to the problem statement
that appears in each prompt.
```

Notes:
- First night bootstraps an empty backlog; it accumulates from there because
  `state/hexgen.db` is committed.
- If you'd rather review than auto-commit to the working branch, point the last
  step at a dedicated `research-agent/nightly` branch and open/update a PR.
- To retarget to a different research problem, change only `config/hexgen.yaml`
  (Stage 0); the nightly config inherits it via `extends:`.
