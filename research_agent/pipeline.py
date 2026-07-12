"""Pipeline orchestrator — a scheduled, idempotent five-stage funnel.

This is deliberately a straight-line pipeline, not an open-ended agent loop:
``source -> filter -> extract -> score -> deliver``, with LLM behavior confined
to the bounded steps inside stages (relevance judging, claim extraction,
effort/impact estimation). Idempotency lives in the DB (``papers.status``), so
reruns only process new work.

Resources (DB, HTTP client, embedder, LLM) are built once and shared across
stages. Use as a context manager to release them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .config import Config
from .db import Database
from .delivery import stage5_deliver
from .embeddings import Embedder, get_embedder
from .extraction import stage3_extract
from .http import HttpClient
from .llm import LLMClient, get_llm
from .models import BacklogItem, Digest, Extraction, Paper
from .relevance import stage2_relevance
from .scoring import stage4_score

# Stage entry points (each implemented in its own subpackage; see docs/CONTRACTS.md).
from .sourcing import stage1_source

STAGES = ("source", "filter", "extract", "score", "deliver")


class Pipeline:
    """Owns the shared resources and runs stages in order."""

    def __init__(
        self,
        config: Config,
        *,
        db: Database | None = None,
        http: HttpClient | None = None,
        embedder: Embedder | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.config = config
        self._db = db
        self._http = http
        self._embedder = embedder
        self._llm = llm

    # -- lazily-built shared resources ----------------------------------- #
    @property
    def db(self) -> Database:
        if self._db is None:
            self._db = Database(self.config.storage.db_path)
        return self._db

    @property
    def http(self) -> HttpClient:
        if self._http is None:
            self._http = HttpClient(timeout=self.config.sourcing.request_timeout_s)
        return self._http

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = get_embedder(self.config.embedding)
        return self._embedder

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = get_llm(self.config.llm)
        return self._llm

    # -- individual stages ------------------------------------------------ #
    def source(self, *, since: datetime | None = None) -> list[Paper]:
        return stage1_source(self.config, self.db, self.http, since=since)

    def filter(self) -> list[Paper]:
        return stage2_relevance(self.config, self.db, self.embedder, self.llm)

    def extract(self) -> list[Extraction]:
        return stage3_extract(self.config, self.db, self.llm, self.http)

    def score(self) -> list[BacklogItem]:
        return stage4_score(self.config, self.db, self.llm)

    def deliver(self) -> Digest:
        return stage5_deliver(self.config, self.db)

    # -- full run --------------------------------------------------------- #
    def run(
        self,
        stages: tuple[str, ...] = STAGES,
        *,
        since: datetime | None = None,
    ) -> dict[str, Any]:
        """Run the requested stages in canonical order; return a per-stage summary."""
        results: dict[str, Any] = {}
        if "source" in stages:
            sourced = self.source(since=since)
            results["source"] = {"new_papers": len(sourced)}
        if "filter" in stages:
            relevant = self.filter()
            results["filter"] = {"relevant": len(relevant)}
        if "extract" in stages:
            extractions = self.extract()
            results["extract"] = {"extracted": len(extractions)}
        if "score" in stages:
            items = self.score()
            results["score"] = {"backlog_items": len(items)}
        if "deliver" in stages:
            digest = self.deliver()
            results["deliver"] = {
                "new_items": digest.new_item_count,
                "top_items": len(digest.top_items),
            }
        self.db.log("pipeline_run", {"stages": list(stages), "results": results})
        return results

    # -- lifecycle -------------------------------------------------------- #
    def close(self) -> None:
        if self._http is not None:
            self._http.close()
        if self._db is not None:
            self._db.close()

    def __enter__(self) -> Pipeline:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
