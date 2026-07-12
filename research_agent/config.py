"""Stage-0 configuration: the anchor against backlog drift.

The narrow research problem is encoded as (a) a natural-language problem
statement for LLM relevance judging, (b) a hand-picked seed set of papers, and
(c) a keyword/taxonomy filter plus arXiv categories. Every relevance judgment is
anchored to this config, and it changes only deliberately.

Config is loaded from YAML; see ``config/hexgen.yaml`` for the reference domain.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` onto ``base`` (dicts merge; else override wins)."""
    out = dict(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


class LLMConfig(BaseModel):
    # 'anthropic' = direct API (needs a key); 'batch' = agent-as-LLM handoff for
    # Cowork (driven by `research-agent batch-plan`/`batch-apply`); 'mock' = the
    # deterministic offline stub.
    provider: str = Field(default="anthropic", description="'anthropic' | 'batch' | 'mock'")
    relevance_model: str = "claude-haiku-4-5-20251001"
    extraction_model: str = "claude-sonnet-5"
    scoring_model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 4096
    temperature: float = 0.0
    api_key_env: str = "ANTHROPIC_API_KEY"
    # Where the batch client queues requests / reads answers (batch provider).
    batch_dir: str = "data/batch"


class EmbeddingConfig(BaseModel):
    provider: str = Field(default="specter2", description="'specter2' | 'hashing'")
    model_name: str = "allenai/specter2_base"
    dim: int = 768
    # When the real model can't be loaded (offline / no torch), fall back to a
    # deterministic hashing embedder so the pipeline still runs end-to-end.
    fallback_to_hashing: bool = True
    hashing_dim: int = 256
    batch_size: int = 16


class SourcingConfig(BaseModel):
    arxiv_categories: list[str] = Field(default_factory=lambda: ["cs.LG", "cs.CV", "cs.CG"])
    max_results_per_run: int = 200
    # OAI-PMH set for selective harvesting; optional (falls back to the query API).
    oai_set: str | None = None
    use_semantic_scholar: bool = True
    use_openalex: bool = True
    use_hf_papers: bool = False
    semantic_scholar_key_env: str = "S2_API_KEY"
    request_timeout_s: float = 30.0
    # Keyword pre-filter applied at harvest time to keep the corpus bounded.
    harvest_prefilter: bool = True


class RelevanceConfig(BaseModel):
    # Cheap -> expensive cascade thresholds.
    embedding_threshold: float = Field(
        default=0.55, description="Min cosine-to-seed-centroid to survive to the LLM stage"
    )
    embedding_shortlist: int = Field(
        default=60, description="Max papers/run passed to the (expensive) LLM classifier"
    )
    llm_threshold: float = Field(default=0.5, description="Min LLM relevance score to mark RELEVANT")
    use_bm25_rrf: bool = Field(default=False, description="Fuse BM25 with dense via RRF (NLP-KG recipe)")
    rrf_alpha: float = 0.8


class ExtractionConfig(BaseModel):
    use_grobid: bool = False
    grobid_url: str = "http://localhost:8070"
    prefer_html: bool = True  # ar5iv/arXiv HTML avoids PDF-parse errors
    max_chunk_tokens: int = 1200
    max_chunks: int = 24
    min_confidence: float = 0.0
    # Regex hints for locating limitation-bearing sections (BAGELS methodology).
    limitation_section_patterns: list[str] = Field(
        default_factory=lambda: ["limitation", "future work", "discussion", "conclusion"]
    )


class ScoringConfig(BaseModel):
    # Weights let a domain tilt the RICE emphasis without changing the formula.
    weight_impact: float = 1.0
    weight_applicability: float = 1.0
    weight_confidence: float = 1.0
    # One backlog item per paper by default (a paper is one "thing to try").
    # Enable to also spin distinct high-value claimed advantages into their own
    # items — richer, but risks backlog bloat, so it is opt-in.
    emit_secondary_items: bool = False
    # Reserve backlog capacity for high-citation foundational papers to fight
    # recency bias (a documented Matthew-effect failure mode).
    foundational_reserved_slots: int = 5
    foundational_min_citations: int = 100
    # Citations are a *lagging* confidence booster; do not gate recent papers on
    # them. Papers newer than this many days get no citation penalty.
    recent_paper_grace_days: int = 365
    archive_below_score: float = 0.0
    llm_estimate_effort: bool = True


class DeliveryConfig(BaseModel):
    top_n: int = 25
    digest_window_days: int = 7
    output_dir: str = "output"
    render_html: bool = True
    # Near-duplicate detection.
    title_fuzzy_threshold: float = 0.9


class StorageConfig(BaseModel):
    db_path: str = "data/research_agent.db"


class Config(BaseModel):
    """Top-level configuration for one narrow research problem."""

    name: str = "default"
    problem_statement: str = ""
    seed_papers: list[str] = Field(
        default_factory=list, description="arXiv ids anchoring the relevance centroid"
    )
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    # Optional taxonomy seed (e.g. from the frozen Papers With Code method tree).
    taxonomy_terms: list[str] = Field(default_factory=list)

    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    sourcing: SourcingConfig = Field(default_factory=SourcingConfig)
    relevance: RelevanceConfig = Field(default_factory=RelevanceConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    delivery: DeliveryConfig = Field(default_factory=DeliveryConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)

    # Populated at load time; not part of the YAML.
    config_path: str | None = None

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> Config:
        """Load config from a YAML file.

        Supports a top-level ``extends: <relative-path>`` key: the referenced
        base config is loaded first and this file's keys are deep-merged over it
        (dicts merge recursively; scalars and lists override). This lets a
        nightly/variant config change only a few fields without duplicating the
        whole problem definition.
        """
        p = Path(path)
        data = cls._load_raw(p)
        cfg = cls.model_validate(data)
        cfg.config_path = str(p)
        return cfg

    @classmethod
    def _load_raw(cls, p: Path) -> dict[str, Any]:
        raw: dict[str, Any] = yaml.safe_load(p.read_text()) or {}
        base_ref = raw.pop("extends", None)
        if base_ref:
            base_path = Path(base_ref)
            if not base_path.is_absolute():
                base_path = p.parent / base_path
            return _deep_merge(cls._load_raw(base_path), raw)
        return raw

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        return cls.model_validate(data)

    def resolved_db_path(self) -> Path:
        """DB path resolved relative to the config file's directory when relative."""
        db = Path(self.storage.db_path)
        if db.is_absolute() or self.config_path is None:
            return db
        return db  # kept relative to CWD by default; CLI may override

    def resolved_output_dir(self) -> Path:
        return Path(self.delivery.output_dir)
