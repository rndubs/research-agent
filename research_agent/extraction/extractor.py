"""Schema-constrained claim extraction with mandatory provenance.

``ClaimExtractor`` chunks a paper's full text, prompts the LLM to fill the flat
:class:`ExtractionResult` schema *grounded only in the provided text* (a short
verbatim quote per non-empty field), and maps the result back to the canonical
:class:`~research_agent.models.Extraction`. Provenance quotes are relocated to
their originating chunk/section on a best-effort basis. Malformed model output
triggers one recovery pass, then a zero-confidence stub — a run never crashes.
"""

from __future__ import annotations

from ..config import Config
from ..llm import LLMClient, build_stub
from ..models import Chunk, Extraction, FieldProvenance, FullText, Paper
from ..parsing import chunk_sections
from .schema import ExtractionResult

# Fields that carry substantive claims and therefore need provenance.
_CLAIM_FIELDS = (
    "problem_addressed",
    "method_summary",
    "key_architecture_choices",
    "datasets",
    "metrics",
    "headline_results",
    "claimed_advantages",
    "limitations",
    "applicability_to_our_problem",
    "implementation_cost_estimate",
    "dependencies_on_other_methods",
    "code_link",
)


class ClaimExtractor:
    """Extract a grounded, provenance-carrying ``Extraction`` from full text."""

    def __init__(self, llm: LLMClient, config: Config) -> None:
        self.llm = llm
        self.config = config

    # -- public ----------------------------------------------------------- #
    def extract(self, paper: Paper, fulltext: FullText) -> Extraction:
        ex = self.config.extraction
        chunks = chunk_sections(
            fulltext,
            max_tokens=ex.max_chunk_tokens,
            max_chunks=ex.max_chunks,
            limitation_patterns=ex.limitation_section_patterns,
        )
        prompt = self._build_prompt(paper, chunks)
        result = self._run_llm(prompt, cache_key=paper.id)
        return self._to_extraction(paper, result, chunks)

    # -- internals -------------------------------------------------------- #
    def _model_name(self) -> str:
        # ExtractionConfig has no model field; the model lives on LLMConfig.
        # Tolerate either location so this keeps working if that ever changes.
        return (
            getattr(self.config.extraction, "extraction_model", None)
            or self.config.llm.extraction_model
        )

    def _run_llm(self, prompt: str, cache_key: str | None = None) -> ExtractionResult:
        model = self._model_name()
        try:
            return self.llm.structured(
                prompt, ExtractionResult, model=model, temperature=0, cache_key=cache_key
            )
        except Exception:
            # Malformed output (ValidationError / coercion error) or a transient
            # provider fault: one recovery attempt with an explicit reminder,
            # then a safe zero-confidence stub.
            recovery = (
                prompt
                + "\n\nIMPORTANT: your previous output was invalid. Return ONLY a "
                "valid object matching the schema exactly; use empty strings/lists "
                "for anything unsupported by the text."
            )
            try:
                return self.llm.structured(
                    recovery, ExtractionResult, model=model, temperature=0
                )
            except Exception:
                return build_stub(ExtractionResult, confidence=0.0)

    def _build_prompt(self, paper: Paper, chunks: list[Chunk]) -> str:
        problem = self.config.problem_statement or "(no problem statement configured)"
        if chunks:
            body = "\n\n".join(
                f"[chunk {c.index} | section: {c.section or 'Body'}]\n{c.text}"
                for c in chunks
            )
        else:
            body = "(no full text available)"
        return (
            "You extract structured, grounded claims from a machine-learning "
            "research paper. Extract ONLY claims supported by the PAPER TEXT "
            "below — never invent facts.\n\n"
            "For EVERY non-empty substantive PAPER-CLAIM field you fill (e.g. "
            "problem_addressed, method_summary, contributions_summary, "
            "headline_results, claimed_advantages, limitations), add an entry to "
            "`provenance` mapping that field's name to a SHORT verbatim quote "
            "(<= 200 chars) copied from the PAPER TEXT that supports it. Do not "
            "assert a paper-claim field you cannot ground in a quote.\n\n"
            "Write `contributions_summary` as a clear 2-4 sentence plain-prose "
            "summary of what the paper CLAIMS to contribute (its novel "
            "method/result) — no scores, no our-problem framing.\n"
            "For `applicability_to_our_problem`, be LIBERAL against OUR PROBLEM "
            "STATEMENT: it need not be the whole paper — name any subset, single "
            "mechanism, or tangential/analogous idea worth borrowing. Only leave it "
            "empty if there is genuinely nothing transferable.\n"
            "Use `reviewer_notes` for freeform additional context a reviewer should "
            "know (caveats, relevant limitations, connections, risks). "
            "`applicability_to_our_problem` and `reviewer_notes` are your own "
            "judgment relative to OUR PROBLEM and do NOT require a paper quote.\n"
            "Set `implementation_cost_estimate` to S, M, or L (or a short phrase).\n"
            "Set `confidence` in [0,1] for your overall extraction confidence.\n\n"
            f"OUR PROBLEM STATEMENT:\n{problem}\n\n"
            f"PAPER: {paper.title}\n\n"
            f"PAPER TEXT (chunked by section):\n{body}\n"
        )

    def _locate_quote(
        self, quote: str, chunks: list[Chunk]
    ) -> tuple[str | None, int | None, int | None]:
        """Best-effort: find which chunk/section a provenance quote came from."""
        q = (quote or "").strip().lower()
        if q:
            for c in chunks:
                if q in (c.text or "").lower():
                    return c.section, c.index, c.page
        return None, None, None

    def _to_extraction(
        self, paper: Paper, result: ExtractionResult, chunks: list[Chunk]
    ) -> Extraction:
        provenance: dict[str, FieldProvenance] = {}
        for field, quote in (result.provenance or {}).items():
            if not quote:
                continue
            section, chunk_index, page = self._locate_quote(quote, chunks)
            provenance[field] = FieldProvenance(
                section=section, chunk_index=chunk_index, page=page, quote=quote
            )

        return Extraction(
            paper_id=paper.id,
            problem_addressed=result.problem_addressed,
            method_summary=result.method_summary,
            contributions_summary=result.contributions_summary,
            key_architecture_choices=result.key_architecture_choices,
            datasets=result.datasets,
            metrics=result.metrics,
            headline_results=result.headline_results,
            claimed_advantages=result.claimed_advantages,
            limitations=result.limitations,
            applicability_to_our_problem=result.applicability_to_our_problem,
            reviewer_notes=result.reviewer_notes,
            implementation_cost_estimate=result.implementation_cost_estimate,
            dependencies_on_other_methods=result.dependencies_on_other_methods,
            code_link=result.code_link,
            provenance=provenance,
            extraction_model=self._model_name(),
            extraction_confidence=result.confidence,
        )
