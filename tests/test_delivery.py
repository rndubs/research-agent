"""Stage-5 delivery tests: dedup, reserved foundational lane, and digest.

All hermetic/offline — build papers + backlog items directly and exercise
``stage5_deliver`` against an in-memory DB with output written under ``tmp_path``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from research_agent.config import Config
from research_agent.db import Database
from research_agent.delivery import (
    dedupe_backlog,
    render_backlog_markdown,
    render_digest,
    select_top,
    stage5_deliver,
)
from research_agent.models import (
    BacklogItem,
    BacklogStatus,
    Paper,
    PaperStatus,
    RiceComponents,
    utcnow,
)


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def _paper(
    arxiv_id: str,
    title: str,
    *,
    authors: list[str],
    citation_count: int,
    version: int = 1,
    doi: str | None = None,
) -> Paper:
    return Paper(
        arxiv_id=arxiv_id,
        version=version,
        title=title,
        authors=authors,
        citation_count=citation_count,
        doi=doi,
        status=PaperStatus.SCORED,
    )


def _item(
    item_id: str,
    paper_id: str,
    title: str,
    *,
    impact: float,
    applicability: float,
    confidence: float,
    effort: float,
    foundational: bool = False,
    dependencies: list[str] | None = None,
    created_at=None,
    rationale: str = "",
    contributions: str = "",
    applicability_text: str = "",
    reviewer_notes: str = "",
) -> BacklogItem:
    rice = RiceComponents(
        expected_impact=impact,
        applicability=applicability,
        confidence=confidence,
        effort=effort,
    )
    item = BacklogItem(
        id=item_id,
        paper_id=paper_id,
        title=title,
        rice=rice,
        score=rice.score(),
        foundational=foundational,
        dependencies=dependencies or [],
        rationale=rationale,
        contributions=contributions,
        applicability=applicability_text,
        reviewer_notes=reviewer_notes,
        status=BacklogStatus.NEW,
    )
    if created_at is not None:
        item.created_at = created_at
    return item


@pytest.fixture
def delivery_config(tmp_path) -> Config:
    """Config whose output dir points at pytest tmp_path; small reserved lane."""
    return Config.from_dict(
        {
            "name": "hexgen-test",
            "llm": {"provider": "mock"},
            "embedding": {"provider": "hashing", "hashing_dim": 256},
            "storage": {"db_path": ":memory:"},
            "scoring": {"foundational_reserved_slots": 2},
            "delivery": {
                "output_dir": str(tmp_path),
                "top_n": 5,
                "digest_window_days": 7,
                "render_html": True,
                "title_fuzzy_threshold": 0.9,
            },
        }
    )


@pytest.fixture
def seeded_db() -> Database:
    """In-memory DB seeded with a duplicate pair, a low-score foundational item,
    and higher-scoring non-foundational items (one old, one fresh)."""
    db = Database(":memory:")

    # --- near-duplicate pair: same title ~, shared author, different ids ---- #
    dup_keep = _paper(
        "2401.10000",
        "Pointer Networks for B-rep to Hex Mesh Program Synthesis",
        authors=["Ada Lovelace", "Grace Hopper"],
        citation_count=120,  # published record -> keeper
        version=2,
    )
    dup_weak = _paper(
        "2312.09999",
        "Pointer Networks for B-Rep to Hex-Mesh Program Synthesis",  # minor drift
        authors=["Ada Lovelace"],  # overlapping author
        citation_count=4,  # weaker -> archived
        version=1,
    )

    # --- foundational item with a LOW score ------------------------------- #
    foundational_paper = _paper(
        "1706.03762",
        "Attention Is All You Need for CAD",
        authors=["A. Vaswani"],
        citation_count=9000,
    )

    # --- higher-scoring non-foundational papers --------------------------- #
    strong_a = _paper(
        "2405.00001", "Execution-Guided Hex Decoding", authors=["X. One"], citation_count=30
    )
    strong_b = _paper(
        "2405.00002", "Equivariant B-rep Encoders", authors=["Y. Two"], citation_count=40
    )
    strong_c = _paper(
        "2405.00003", "Graph Transformers for Meshing", authors=["Z. Three"], citation_count=10
    )

    for p in (dup_keep, dup_weak, foundational_paper, strong_a, strong_b, strong_c):
        db.upsert_paper(p)

    now = utcnow()
    old = now - timedelta(days=60)  # outside the 7-day window
    fresh = now - timedelta(days=1)  # inside the window

    items = [
        # duplicate items (keeper high score, weaker lower)
        _item("2401.10000#0", "2401.10000", dup_keep.title,
              impact=0.9, applicability=0.9, confidence=0.9, effort=2.0, created_at=fresh),
        _item("2312.09999#0", "2312.09999", dup_weak.title,
              impact=0.9, applicability=0.9, confidence=0.9, effort=2.0, created_at=old),
        # foundational, deliberately LOW score (small impact / high effort)
        _item("1706.03762#0", "1706.03762", foundational_paper.title,
              impact=0.2, applicability=0.2, confidence=0.5, effort=8.0,
              foundational=True, created_at=fresh,
              rationale="Canonical attention mechanism the decoder builds on."),
        # strong non-foundational items
        _item("2405.00001#0", "2405.00001", strong_a.title,
              impact=0.8, applicability=0.8, confidence=0.8, effort=1.0,
              dependencies=["pointer-network"], created_at=fresh),
        _item("2405.00002#0", "2405.00002", strong_b.title,
              impact=0.7, applicability=0.9, confidence=0.8, effort=1.0, created_at=old),
        _item("2405.00003#0", "2405.00003", strong_c.title,
              impact=0.6, applicability=0.7, confidence=0.7, effort=1.0, created_at=fresh),
    ]
    for it in items:
        db.save_backlog_item(it)

    yield db
    db.close()


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_dedupe_archives_weaker_duplicate(seeded_db, delivery_config):
    pairs = dedupe_backlog(seeded_db, delivery_config)

    assert ("2401.10000", "2312.09999") in pairs, pairs
    # weaker duplicate's item is archived; keeper stays live
    assert seeded_db.get_backlog_item("2312.09999#0").status == BacklogStatus.ARCHIVED
    assert seeded_db.get_backlog_item("2401.10000#0").status != BacklogStatus.ARCHIVED


def test_dedupe_by_exact_doi(delivery_config):
    db = Database(":memory:")
    a = _paper("2400.00001", "Totally Different Title A", authors=["No Overlap One"],
               citation_count=5, doi="10.1234/shared")
    b = _paper("2400.00002", "Completely Unrelated Wording B", authors=["No Overlap Two"],
               citation_count=50, doi="10.1234/SHARED")  # same DOI, different case
    db.upsert_paper(a)
    db.upsert_paper(b)
    db.save_backlog_item(_item("2400.00001#0", "2400.00001", a.title,
                               impact=0.5, applicability=0.5, confidence=0.5, effort=1.0))
    db.save_backlog_item(_item("2400.00002#0", "2400.00002", b.title,
                               impact=0.5, applicability=0.5, confidence=0.5, effort=1.0))

    pairs = dedupe_backlog(db, delivery_config)
    assert ("2400.00002", "2400.00001") in pairs  # higher-cited kept
    assert db.get_backlog_item("2400.00001#0").status == BacklogStatus.ARCHIVED
    db.close()


def test_select_top_reserves_low_score_foundational(seeded_db, delivery_config):
    dedupe_backlog(seeded_db, delivery_config)
    items = list(seeded_db.iter_backlog())
    top = select_top(items, delivery_config)

    ids = [i.id for i in top]
    # foundational item survives despite its low score (reserved lane)
    assert "1706.03762#0" in ids
    foundational = next(i for i in top if i.id == "1706.03762#0")
    # its score is genuinely lower than a non-foundational item that made the cut
    non_found_scores = [i.score for i in top if not i.foundational]
    assert foundational.score < max(non_found_scores)
    # archived duplicate never appears
    assert "2312.09999#0" not in ids
    # respects top_n
    assert len(top) <= delivery_config.delivery.top_n


def test_select_top_would_exclude_foundational_without_reservation(delivery_config):
    """With top_n small and many strong items, only the reserved lane saves it."""
    db = Database(":memory:")
    # papers first (backlog rows carry a FK to papers)
    db.upsert_paper(_paper("pf", "Foundational Low", authors=["F"], citation_count=999))
    for k in range(10):
        db.upsert_paper(_paper(f"ps{k}", f"Strong {k}", authors=[f"S{k}"], citation_count=1))
    # one low-score foundational
    found = _item("f#0", "pf", "Foundational Low", impact=0.1, applicability=0.1,
                  confidence=0.1, effort=9.0, foundational=True)
    db.save_backlog_item(found)
    # several strong items, more than top_n
    for k in range(10):
        db.save_backlog_item(
            _item(f"s{k}#0", f"ps{k}", f"Strong {k}", impact=0.9, applicability=0.9,
                  confidence=0.9, effort=1.0)
        )
    cfg = delivery_config
    cfg.delivery.top_n = 3
    cfg.scoring.foundational_reserved_slots = 1
    top = select_top(list(db.iter_backlog()), cfg)
    assert any(i.foundational for i in top)
    assert len(top) == 3
    db.close()


def test_render_backlog_markdown_has_arxiv_link_and_rice_columns(seeded_db, delivery_config):
    items = select_top(list(seeded_db.iter_backlog()), delivery_config)
    md = render_backlog_markdown(items, delivery_config, seeded_db)

    assert "https://arxiv.org/abs/" in md
    # RICE columns present in the header
    for col in ("Impact", "Applic", "Conf", "Effort"):
        assert col in md
    assert "Foundational lane" in md
    # a specific arxiv link renders
    assert "https://arxiv.org/abs/2405.00001" in md


def test_digest_renders_three_fields_and_drops_metric_prose(delivery_config):
    """The digest body shows the three reviewer fields and never re-emits the
    metric-laden rationale prose (which is what the RICE chips are for)."""
    db = Database(":memory:")
    db.upsert_paper(_paper("2607.11111", "A Fresh Relevant Paper", authors=["A. Uthor"],
                           citation_count=3))
    metric_prose = (
        "Impact 0.55 (targets our #1 problem); Applicability 0.60; "
        "Confidence 0.51 [code=False, provenance=0.78]; Effort 6.0/10. Score=0.0280."
    )
    db.save_backlog_item(_item(
        "2607.11111#1", "2607.11111", "A Fresh Relevant Paper",
        impact=0.55, applicability=0.60, confidence=0.51, effort=6.0,
        rationale=metric_prose,
        contributions="Proposes an on-policy self-distillation scheme for AR rollouts.",
        applicability_text="The corrective-rollout template transfers to hexgen program repair.",
        reviewer_notes="Demonstrated only on video diffusion, not executable grammars.",
    ))

    digest = render_digest(delivery_config, db)

    for surface in (digest.markdown, digest.html):
        assert "on-policy self-distillation scheme" in surface
        assert "transfers to hexgen program repair" in surface
        assert "video diffusion, not executable grammars" in surface
        # the labels are present...
        assert "Contributions" in surface
        assert "Additional context" in surface
        # ...but the duplicated metric readout prose is NOT in the body.
        assert "provenance=0.78" not in surface
        assert "Score=0.0280" not in surface
    db.close()


def test_digest_falls_back_for_legacy_items_without_new_fields(delivery_config):
    """A pre-migration row (only description + metric rationale) still renders a
    sensible body and never leaks the metric prose."""
    db = Database(":memory:")
    db.upsert_paper(_paper("2607.22222", "Legacy Row Paper", authors=["L. Egacy"],
                           citation_count=3))
    db.save_backlog_item(_item(
        "2607.22222#1", "2607.22222", "Legacy Row Paper",
        impact=0.4, applicability=0.4, confidence=0.4, effort=5.0,
        rationale="Impact 0.40 (...); Confidence 0.40 [provenance=0.45]; Score=0.0128.",
    ))
    # simulate the old description blob on the stored row
    legacy = db.get_backlog_item("2607.22222#1")
    legacy.description = (
        "Headline results: strong held-out generalization.\n\n"
        "Applicability to our problem: the query-time vocabulary idea could "
        "generalize hexgen's closed coordinate vocabulary."
    )
    db.save_backlog_item(legacy)

    digest = render_digest(delivery_config, db)
    assert "strong held-out generalization" in digest.html
    assert "closed coordinate vocabulary" in digest.html
    assert "provenance=0.45" not in digest.html
    db.close()


def test_render_digest_window_filters_old_and_keeps_fresh(seeded_db, delivery_config):
    dedupe_backlog(seeded_db, delivery_config)
    digest = render_digest(delivery_config, seeded_db)

    # fresh item is "new"; 60-days-old item is excluded from the window
    assert "Execution-Guided Hex Decoding" in digest.markdown
    # the old strong item (created 60d ago) must not be in the NEW section
    new_titles = digest.markdown.split("Current top")[0]
    assert "Equivariant B-rep Encoders" not in new_titles
    assert digest.new_item_count >= 1
    assert digest.html is not None and "<html" in digest.html


def test_stage5_deliver_writes_artifacts(seeded_db, delivery_config, tmp_path):
    digest = stage5_deliver(delivery_config, seeded_db)

    backlog_md = tmp_path / "backlog.md"
    digest_md = tmp_path / "digest.md"
    digest_html = tmp_path / "digest.html"

    for f in (backlog_md, digest_md, digest_html):
        assert f.exists(), f
        assert f.stat().st_size > 0, f

    # weaker duplicate archived by the run
    assert seeded_db.get_backlog_item("2312.09999#0").status == BacklogStatus.ARCHIVED
    # foundational reserved in the returned top view
    assert any(i.foundational for i in digest.top_items)
    assert isinstance(digest.new_item_count, int)


def test_stage5_deliver_respects_render_html_false(seeded_db, delivery_config, tmp_path):
    delivery_config.delivery.render_html = False
    digest = stage5_deliver(delivery_config, seeded_db)
    assert digest.html is None
    assert not (tmp_path / "digest.html").exists()
    assert (tmp_path / "backlog.md").exists()
