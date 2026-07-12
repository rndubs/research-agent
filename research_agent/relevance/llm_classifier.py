"""LLM rung of the relevance cascade: the expensive, most-precise judgment.

Only the dense-similarity shortlist reaches this rung. The classifier hands the
model the configured ``problem_statement`` (the drift anchor), a short rubric,
and the paper's title + abstract, and forces a flat structured verdict. Prompts
are deterministic and temperature-0 so runs are reproducible and cheap to cache.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..config import Config
from ..llm import LLMClient
from ..models import Paper, RelevanceMethod, RelevanceResult


class RelevanceJudgment(BaseModel):
    """Flat request schema the LLM is forced to return.

    Kept flat (no nesting) because nested schemas are a documented structured-
    output failure mode. ``score`` is the graded relevance in ``[0, 1]``;
    ``relevant`` is the model's own boolean, retained for logging even though the
    cascade thresholds on ``score``.
    """

    relevant: bool = Field(..., description="Whether the paper plausibly helps the problem")
    score: float = Field(..., ge=0.0, le=1.0, description="Graded relevance in [0, 1]")
    rationale: str = Field(default="", description="One or two sentences justifying the verdict")


_RUBRIC = (
    "Judge whether the paper plausibly helps the target research problem below.\n"
    "Mark it RELEVANT (high score) if its methods or findings could bear on any of the "
    "care-areas: structural validity of generated programs, domain gap / distribution "
    "shift, pointer networks / graph transformers, rotation robustness / equivariance, "
    "self-play or verifier-in-the-loop training, and program synthesis. A paper from a "
    "different application area is still relevant if there is a clear methodological "
    "bridge to those care-areas.\n"
    "Mark it NOT RELEVANT (low score) only if it is an unrelated application with no "
    "plausible bridge to the problem.\n"
    "Anchor every judgment to the problem statement and care-areas above; do not let the "
    "backlog drift toward merely-adjacent topics."
)


class LLMRelevanceClassifier:
    """Wraps a schema-forced LLM call into a :class:`RelevanceResult`."""

    def __init__(self, llm: LLMClient, config: Config) -> None:
        self.llm = llm
        self.config = config

    def _build_prompt(self, paper: Paper) -> str:
        return (
            f"{_RUBRIC}\n\n"
            f"=== TARGET RESEARCH PROBLEM ===\n{self.config.problem_statement}\n\n"
            f"=== CANDIDATE PAPER ===\n"
            f"Title: {paper.title}\n"
            f"Abstract: {paper.abstract}\n\n"
            "Return your verdict as the structured schema."
        )

    def classify(self, paper: Paper) -> RelevanceResult:
        """Classify one paper's relevance to the configured problem."""
        prompt = self._build_prompt(paper)
        judgment = self.llm.structured(
            prompt,
            RelevanceJudgment,
            model=self.config.llm.relevance_model,
            temperature=0,
            cache_key=paper.id,  # stable key for batch/agent-as-LLM mode
        )
        return RelevanceResult(
            paper_id=paper.id,
            relevant=judgment.relevant,
            score=judgment.score,
            rationale=judgment.rationale,
            method=RelevanceMethod.LLM,
        )
