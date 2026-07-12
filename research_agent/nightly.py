"""Two-phase driver for batch / agent-as-LLM mode (see ``docs/NIGHTLY.md``).

``batch_plan`` runs the LLM stages against a *throwaway snapshot* of the DB with
a collecting :class:`BatchLLM`, so it surfaces the requests for the earliest
unsatisfied stage without committing anything. The agent answers those requests;
``batch_plan`` is re-run until it reports ``ready``; then ``batch_apply`` runs the
stages for real with a strict client (every call must hit the answer cache).

Why a snapshot: the stages compute *and* commit in one pass, so running them to
collect requests would otherwise persist decisions made from stub answers. The
snapshot is discarded, leaving only ``requests.jsonl``.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from typing import Any

from .config import Config
from .db import Database
from .delivery import stage5_deliver
from .embeddings import get_embedder
from .extraction import stage3_extract
from .http import HttpClient
from .llm.batch import BatchLLM
from .models import Digest
from .relevance import stage2_relevance
from .scoring import stage4_score


def _snapshot(db_path: str) -> str:
    """Back up ``db_path`` to a fresh temp file and return its path.

    Uses the SQLite backup API so it is correct under WAL. The caller owns the
    returned file and must delete it.
    """
    Database(db_path).close()  # ensure the real DB (and schema) exists
    fd, tmp = tempfile.mkstemp(suffix=".db", prefix="ra_snapshot_")
    os.close(fd)
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    return tmp


def batch_plan(config: Config) -> dict[str, Any]:
    """Collect the next round of LLM requests for the batch flow.

    Returns ``{"status": "ready"}`` when every LLM call is already answered, or
    ``{"status": "pending", "stage": ..., "count": n, "requests_path": ...}``
    when ``n`` requests were written for the agent to answer.
    """
    tmp = _snapshot(config.storage.db_path)
    db = Database(tmp)
    embedder = get_embedder(config.embedding)
    http = HttpClient(timeout=config.sourcing.request_timeout_s)
    llm = BatchLLM(config.llm.batch_dir, strict=False)
    try:
        stage2_relevance(config, db, embedder, llm)
        stage = "filter" if llm.pending else None
        if stage is None:
            stage3_extract(config, db, llm, http)
            stage = "extract" if llm.pending else None
        if stage is None:
            stage4_score(config, db, llm)
            stage = "score" if llm.pending else None
    finally:
        http.close()
        db.close()
        try:
            os.remove(tmp)
        except OSError:
            pass

    count = llm.flush_requests()
    if count:
        return {
            "status": "pending",
            "stage": stage,
            "count": count,
            "requests_path": str(llm.requests_path),
            "answers_path": str(llm.answers_path),
        }
    return {"status": "ready"}


def batch_apply(config: Config) -> Digest:
    """Run the LLM stages for real using the answered cache; deliver the digest.

    Raises :class:`~research_agent.llm.batch.MissingBatchAnswer` if any request is
    still unanswered (i.e. ``batch_plan`` was not run to ``ready`` first).
    """
    db = Database(config.storage.db_path)
    embedder = get_embedder(config.embedding)
    http = HttpClient(timeout=config.sourcing.request_timeout_s)
    llm = BatchLLM(config.llm.batch_dir, strict=True)
    try:
        stage2_relevance(config, db, embedder, llm)
        stage3_extract(config, db, llm, http)
        stage4_score(config, db, llm)
        digest = stage5_deliver(config, db)
    finally:
        http.close()
        db.close()
    llm.clear_requests()
    return digest
