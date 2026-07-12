"""Section -> chunk packing for schema-constrained extraction.

Approximates token count by word count (good enough for budgeting), greedily
packs sections into chunks up to ``max_tokens``, and splits any oversize section
across multiple chunks. Sections whose title matches a ``limitation_patterns``
hint are *prioritized*: each becomes its own chunk (so its title is preserved)
and it is always retained when the ``max_chunks`` budget forces truncation —
limitations/failure-mode text is the highest-signal content for a research
backlog and must never be dropped in favour of front-matter.
"""

from __future__ import annotations

from collections.abc import Iterator

from ..models import Chunk, FullText


def _split_words(words: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(words), size):
        yield words[i : i + size]


def chunk_sections(
    fulltext: FullText,
    max_tokens: int,
    max_chunks: int,
    limitation_patterns: list[str] | None = None,
) -> list[Chunk]:
    """Pack ``fulltext`` sections into at most ~``max_chunks`` word-bounded chunks.

    Each returned chunk holds <= ``max_tokens`` words and carries the title/page
    of the (first) section that contributes to it. Limitation-bearing sections
    are isolated and survive truncation even beyond ``max_chunks``.
    """
    size = max(1, int(max_tokens))
    patterns = [p.lower() for p in (limitation_patterns or []) if p]

    def is_limitation(title: str) -> bool:
        t = (title or "").lower()
        return any(p in t for p in patterns)

    # Each raw entry: (title, page, text, is_limitation).
    raw: list[tuple[str, int | None, str, bool]] = []
    buf_words: list[str] = []
    buf_title: str | None = None
    buf_page: int | None = None

    def flush() -> None:
        nonlocal buf_words, buf_title, buf_page
        if buf_words:
            raw.append((buf_title or "", buf_page, " ".join(buf_words), False))
        buf_words = []
        buf_title = None
        buf_page = None

    for sec in fulltext.sections:
        words = (sec.text or "").split()
        if is_limitation(sec.title):
            # Isolate limitation sections so title is preserved and they can be
            # prioritized during truncation.
            flush()
            if words:
                for piece in _split_words(words, size):
                    raw.append((sec.title, sec.page, " ".join(piece), True))
            elif sec.title:
                raw.append((sec.title, sec.page, "", True))
            continue

        if not words:
            continue

        idx = 0
        while idx < len(words):
            space = size - len(buf_words)
            if space <= 0:
                flush()
                space = size
            if buf_title is None:
                buf_title = sec.title
                buf_page = sec.page
            take = words[idx : idx + space]
            buf_words.extend(take)
            idx += len(take)
            if len(buf_words) >= size:
                flush()
    flush()

    # Truncate to the chunk budget, but always keep limitation chunks.
    if max_chunks is not None and len(raw) > max_chunks:
        indexed = list(enumerate(raw))
        limit_items = [(i, r) for i, r in indexed if r[3]]
        non_limit = [(i, r) for i, r in indexed if not r[3]]
        keep_non = max(0, max_chunks - len(limit_items))
        kept = limit_items + non_limit[:keep_non]
        kept.sort(key=lambda x: x[0])  # restore document order
        raw = [r for _, r in kept]

    return [
        Chunk(index=i, text=text, section=title or None, page=page)
        for i, (title, page, text, _lim) in enumerate(raw)
    ]
