"""One-time backfill of the three human-facing reviewer fields onto backlog
items created before those fields existed.

Going forward the extraction LLM fills ``contributions_summary`` /
``applicability_to_our_problem`` / ``reviewer_notes`` directly (see
``extraction/schema.py``). This script populates the same three fields on the
already-scored rows so the live digest reflects the new format immediately,
without re-parsing the PDFs:

  * contributions  <- the grounded ``method_summary`` from the stored extraction
  * applicability  <- the stored (already liberal) ``applicability_to_our_problem``
  * reviewer_notes <- concise reviewer context authored from each paper's
                      limitations + the caveat already recorded in the item's
                      impact rationale (agent-as-LLM judgment, same as nightly)

Run from the repo root:  python scripts/backfill_reviewer_fields.py
"""

from __future__ import annotations

from research_agent.config import Config
from research_agent.db import Database
from research_agent.delivery import stage5_deliver

# Reviewer "additional context" authored per paper from the stored extraction
# (limitations + the impact-rationale caveat). Keyed by arxiv id.
REVIEWER_NOTES: dict[str, str] = {
    "2607.08766": (
        "Demonstrated only on few-step AR video diffusion, not on executable "
        "program grammars, so transfer to hexgen's discrete program rollouts is "
        "unproven. No released code. The 'cleaner-context teacher' has no direct "
        "hexgen analogue — you'd need to synthesize one (e.g. verifier-repaired "
        "continuations), which is a moderate new training-loop component rather "
        "than a drop-in."
    ),
    "2607.08392": (
        "The domain is optical-coating inverse design, not CAD/geometry — the "
        "relevance is by analogy (open-vocabulary + joint discrete/continuous "
        "flow matching), not a direct method transfer. Implementation cost is "
        "high: a flow-matching generator is a substantial departure from the "
        "current autoregressive pointer-decoder. No released code noted."
    ),
    "2607.08256": (
        "Evaluated only in zero-shot TTS with learned ASR verifiers; hexgen's "
        "verifier is a single frozen deterministic checker, not an ensemble of "
        "learned models, so the cross-family confound may not bite us directly. "
        "The value here is evaluation hygiene for best-of-N reporting rather than "
        "a capability gain — cheap to adopt only if we ever add proxy verifiers."
    ),
    "2607.07993": (
        "The co-evolution loop assumes a learned detector/reward model; hexgen's "
        "verifier is frozen and deterministic, so applicability is speculative "
        "and would first require training a learned proxy verifier or a "
        "rollout-difficulty generator. Evaluated on RAGTruth (NLP faithfulness), "
        "far from geometry/program synthesis."
    ),
}


def main() -> None:
    config = Config.load("config/hexgen-nightly.yaml")
    db = Database(config.storage.db_path)

    updated = 0
    for item in list(db.iter_backlog()):
        ex = db.get_extraction(item.paper_id)
        if ex is None:
            continue
        # Contributions: prefer the dedicated summary, else the grounded method
        # summary (both come straight from the stored extraction).
        item.contributions = (
            (ex.contributions_summary or ex.method_summary or "").strip()
        )
        item.applicability = (ex.applicability_to_our_problem or "").strip()
        item.reviewer_notes = (
            (ex.reviewer_notes or REVIEWER_NOTES.get(item.paper_id, "")).strip()
        )
        db.save_backlog_item(item)
        updated += 1
        print(f"  backfilled {item.id}")

    # Re-render digest + backlog and write them under state/output.
    stage5_deliver(config, db)
    db.close()
    print(f"backfilled {updated} item(s); re-rendered state/output/")


if __name__ == "__main__":
    main()
