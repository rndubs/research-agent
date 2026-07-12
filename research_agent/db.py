"""SQLite storage — the canonical store and idempotency backbone.

A solo/small-scale setup (the compass-artifact decision threshold: skip the
vector/graph DBs when relevant volume is low) keeps everything in one SQLite
file: paper metadata, embeddings (float32 blobs), extracted claims (JSON),
backlog items, the dependency edge table, a key/value state store (last-harvest
datestamp, sealed-set consultation counters), and an append-only audit log.

Processing state lives on ``papers.status`` so reruns never re-process work.
All timestamps are stored as ISO-8601 UTC strings.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

import numpy as np

from .models import (
    BacklogItem,
    BacklogStatus,
    DependencyEdge,
    Extraction,
    Paper,
    PaperStatus,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id            TEXT PRIMARY KEY,          -- arxiv_id (version-stripped)
    version       INTEGER NOT NULL DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'seen',
    title         TEXT,
    published     TEXT,
    relevance_score REAL,
    data          TEXT NOT NULL,             -- full Paper JSON
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
CREATE INDEX IF NOT EXISTS idx_papers_published ON papers(published);

CREATE TABLE IF NOT EXISTS embeddings (
    paper_id  TEXT PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
    model     TEXT NOT NULL,
    dim       INTEGER NOT NULL,
    vector    BLOB NOT NULL                  -- float32 little-endian
);

CREATE TABLE IF NOT EXISTS claims (
    paper_id   TEXT PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
    data       TEXT NOT NULL,                -- full Extraction JSON
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backlog (
    id         TEXT PRIMARY KEY,
    paper_id   TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    score      REAL NOT NULL DEFAULT 0,
    foundational INTEGER NOT NULL DEFAULT 0,
    status     TEXT NOT NULL DEFAULT 'new',
    data       TEXT NOT NULL,                -- full BacklogItem JSON
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_backlog_score ON backlog(score DESC);
CREATE INDEX IF NOT EXISTS idx_backlog_status ON backlog(status);

CREATE TABLE IF NOT EXISTS dependencies (
    src      TEXT NOT NULL,
    dst      TEXT NOT NULL,
    source   TEXT NOT NULL DEFAULT 'extracted',
    paper_id TEXT,
    PRIMARY KEY (src, dst, source)
);

CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    ts     TEXT NOT NULL,
    event  TEXT NOT NULL,
    detail TEXT
);
"""


class Database:
    """Thin, well-typed wrapper over a SQLite file.

    Not thread-safe; the pipeline is single-process. Use as a context manager or
    call :meth:`close` explicitly.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.init_schema()

    # -- lifecycle -------------------------------------------------------- #
    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- papers ----------------------------------------------------------- #
    def upsert_paper(self, paper: Paper) -> None:
        """Insert or update a paper, preserving created_at on update."""
        paper.updated_at = paper.updated_at or paper.created_at
        existing = self.get_paper(paper.id)
        created = existing.created_at if existing else paper.created_at
        paper.created_at = created
        payload = paper.model_dump(mode="json")
        pub = paper.published.isoformat() if paper.published else None
        self.conn.execute(
            """INSERT INTO papers (id, version, status, title, published, relevance_score, data, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 version=excluded.version, status=excluded.status, title=excluded.title,
                 published=excluded.published, relevance_score=excluded.relevance_score,
                 data=excluded.data, updated_at=excluded.updated_at""",
            (
                paper.id,
                paper.version,
                paper.status.value,
                paper.title,
                pub,
                paper.relevance_score,
                json.dumps(payload),
                created.isoformat(),
                paper.updated_at.isoformat(),
            ),
        )
        self.conn.commit()

    def get_paper(self, paper_id: str) -> Optional[Paper]:
        row = self.conn.execute("SELECT data FROM papers WHERE id = ?", (paper_id,)).fetchone()
        return Paper.model_validate_json(row["data"]) if row else None

    def has_paper(self, paper_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM papers WHERE id = ?", (paper_id,)).fetchone()
        return row is not None

    def set_status(self, paper_id: str, status: PaperStatus) -> None:
        paper = self.get_paper(paper_id)
        if paper is None:
            raise KeyError(paper_id)
        paper.status = status
        self.upsert_paper(paper)

    def iter_papers(self, status: Optional[PaperStatus] = None) -> Iterator[Paper]:
        if status is not None:
            cur = self.conn.execute(
                "SELECT data FROM papers WHERE status = ? ORDER BY published DESC", (status.value,)
            )
        else:
            cur = self.conn.execute("SELECT data FROM papers ORDER BY published DESC")
        for row in cur:
            yield Paper.model_validate_json(row["data"])

    def papers_by_status(self, status: PaperStatus) -> list[Paper]:
        return list(self.iter_papers(status))

    def count_papers(self, status: Optional[PaperStatus] = None) -> int:
        if status is not None:
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM papers WHERE status = ?", (status.value,)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS c FROM papers").fetchone()
        return int(row["c"])

    # -- embeddings ------------------------------------------------------- #
    def save_embedding(self, paper_id: str, vector: np.ndarray, model: str) -> None:
        vec = np.asarray(vector, dtype=np.float32).ravel()
        self.conn.execute(
            """INSERT INTO embeddings (paper_id, model, dim, vector) VALUES (?, ?, ?, ?)
               ON CONFLICT(paper_id) DO UPDATE SET model=excluded.model, dim=excluded.dim, vector=excluded.vector""",
            (paper_id, model, int(vec.shape[0]), vec.tobytes()),
        )
        self.conn.commit()

    def get_embedding(self, paper_id: str) -> Optional[np.ndarray]:
        row = self.conn.execute(
            "SELECT vector FROM embeddings WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        if row is None:
            return None
        return np.frombuffer(row["vector"], dtype=np.float32).copy()

    def all_embeddings(self) -> dict[str, np.ndarray]:
        out: dict[str, np.ndarray] = {}
        for row in self.conn.execute("SELECT paper_id, vector FROM embeddings"):
            out[row["paper_id"]] = np.frombuffer(row["vector"], dtype=np.float32).copy()
        return out

    # -- claims / extractions -------------------------------------------- #
    def save_extraction(self, extraction: Extraction) -> None:
        self.conn.execute(
            """INSERT INTO claims (paper_id, data, created_at) VALUES (?, ?, ?)
               ON CONFLICT(paper_id) DO UPDATE SET data=excluded.data, created_at=excluded.created_at""",
            (
                extraction.paper_id,
                json.dumps(extraction.model_dump(mode="json")),
                extraction.created_at.isoformat(),
            ),
        )
        self.conn.commit()

    def get_extraction(self, paper_id: str) -> Optional[Extraction]:
        row = self.conn.execute("SELECT data FROM claims WHERE paper_id = ?", (paper_id,)).fetchone()
        return Extraction.model_validate_json(row["data"]) if row else None

    def iter_extractions(self) -> Iterator[Extraction]:
        for row in self.conn.execute("SELECT data FROM claims"):
            yield Extraction.model_validate_json(row["data"])

    # -- backlog ---------------------------------------------------------- #
    def save_backlog_item(self, item: BacklogItem) -> None:
        self.conn.execute(
            """INSERT INTO backlog (id, paper_id, score, foundational, status, data, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 paper_id=excluded.paper_id, score=excluded.score, foundational=excluded.foundational,
                 status=excluded.status, data=excluded.data""",
            (
                item.id,
                item.paper_id,
                item.score,
                int(item.foundational),
                item.status.value,
                json.dumps(item.model_dump(mode="json")),
                item.created_at.isoformat(),
            ),
        )
        self.conn.commit()

    def get_backlog_item(self, item_id: str) -> Optional[BacklogItem]:
        row = self.conn.execute("SELECT data FROM backlog WHERE id = ?", (item_id,)).fetchone()
        return BacklogItem.model_validate_json(row["data"]) if row else None

    def iter_backlog(
        self,
        status: Optional[BacklogStatus] = None,
        order_by_score: bool = True,
    ) -> Iterator[BacklogItem]:
        q = "SELECT data FROM backlog"
        params: tuple[Any, ...] = ()
        if status is not None:
            q += " WHERE status = ?"
            params = (status.value,)
        q += " ORDER BY score DESC" if order_by_score else " ORDER BY created_at DESC"
        for row in self.conn.execute(q, params):
            yield BacklogItem.model_validate_json(row["data"])

    def top_backlog(self, n: int, include_archived: bool = False) -> list[BacklogItem]:
        items = list(self.iter_backlog())
        if not include_archived:
            items = [i for i in items if i.status != BacklogStatus.ARCHIVED]
        return items[:n]

    # -- dependency graph ------------------------------------------------- #
    def add_dependency_edge(self, edge: DependencyEdge) -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO dependencies (src, dst, source, paper_id) VALUES (?, ?, ?, ?)""",
            (edge.src, edge.dst, edge.source, edge.paper_id),
        )
        self.conn.commit()

    def iter_dependency_edges(self) -> Iterator[DependencyEdge]:
        for row in self.conn.execute("SELECT src, dst, source, paper_id FROM dependencies"):
            yield DependencyEdge(
                src=row["src"], dst=row["dst"], source=row["source"], paper_id=row["paper_id"]
            )

    # -- key/value state -------------------------------------------------- #
    def get_state(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def get_last_harvest(self) -> Optional[datetime]:
        v = self.get_state("last_harvest")
        return datetime.fromisoformat(v) if v else None

    def set_last_harvest(self, when: datetime) -> None:
        self.set_state("last_harvest", when.isoformat())

    # -- audit log -------------------------------------------------------- #
    def log(self, event: str, detail: str | dict[str, Any] | None = None) -> None:
        from .models import utcnow

        if isinstance(detail, dict):
            detail = json.dumps(detail)
        self.conn.execute(
            "INSERT INTO audit_log (ts, event, detail) VALUES (?, ?, ?)",
            (utcnow().isoformat(), event, detail),
        )
        self.conn.commit()

    def bulk_upsert_papers(self, papers: Iterable[Paper]) -> int:
        n = 0
        for p in papers:
            self.upsert_paper(p)
            n += 1
        return n
