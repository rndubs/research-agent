---
name: nightly-monitor
description: Run the research-agent nightly cycle in Cowork (agent-as-LLM / batch mode). Use when asked to run the nightly research monitor, refresh the arXiv backlog, do the nightly hexgen run, or when a scheduled Routine fires the nightly job. Harvests new papers, answers the relevance/extraction/scoring LLM requests yourself, scores the backlog, publishes to GitHub Pages, and commits state.
---

# Nightly research monitor

Runs the full monitor for the current config using **batch / agent-as-LLM mode**:
*you* are the LLM for the relevance, extraction, and scoring judgments (no API
key). State is persisted by committing `state/` to the branch.

Default config: `config/hexgen-nightly.yaml` (override with `$ARGUMENTS` if a
different config path is given).

## Procedure

1. **Prep.** Ensure the CLI is installed (the SessionStart hook usually did this):
   `python3 -c 'import research_agent' 2>/dev/null || python3 -m pip install -e . --quiet`.
   Set `CFG=config/hexgen-nightly.yaml` (or the path in `$ARGUMENTS`).

2. **Harvest** (deterministic, no LLM):
   `research-agent source -c "$CFG"`.

3. **Plan → answer loop** (repeat, cap ~6 rounds):
   - Run `research-agent batch-plan -c "$CFG"`. It prints a JSON status line.
   - If `{"status": "ready"}` → break out of the loop.
   - Otherwise it wrote `state/batch/requests.jsonl`. **Read that file.** For EACH
     request object, produce a JSON `payload` that satisfies its `json_schema`,
     judged **only** from its `prompt` (the prompt carries the problem statement +
     the paper). Ground every field in the text; leave a field empty/false when the
     text doesn't support it — do not invent citations or results. Append one line
     per request to `state/batch/answers.jsonl`:
     `{"key": "<the request's key>", "payload": { …schema-valid object… }}`.
   - Re-run `batch-plan`. Each round advances one stage (relevance → extraction →
     scoring), so expect ~3 answering rounds before `ready`.

   Answer as carefully as you would interactively: the relevance rubric and the
   `applicability_to_our_problem` field are what keep the backlog on-target.

4. **Apply** (runs the stages for real against your answers, delivers the digest):
   `research-agent batch-apply -c "$CFG"`. If it exits non-zero with a
   `MissingBatchAnswer`, a request went unanswered — go back to step 3.

5. **Publish to GitHub Pages:** `bash scripts/publish_pages.sh state/output`
   (copies the digest to `docs/index.html`).

6. **Persist state** so tomorrow's run continues from here:
   ```bash
   git add state/ docs/
   git commit -m "nightly monitor: $(date -I)"
   git push -u origin "$(git rev-parse --abbrev-ref HEAD)"
   ```
   (Retry the push a few times on transient network errors.)

7. **Report.** Summarize the new high-scoring items from `state/output/digest.md`
   (title + score + why + arXiv link), or say "no new items this run." Keep it short.

## Notes
- Idempotent: if `source` finds nothing new, `batch-plan` goes straight to `ready`
  and `batch-apply` produces an empty digest — still commit (state may have
  advanced the harvest cursor).
- Never edit the scorer/verifier or hand-tune thresholds to make numbers look
  better. To change what's "relevant", edit Stage 0 (`config/hexgen.yaml`).
- Full reference: `docs/NIGHTLY.md`.
