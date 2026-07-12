"""Deterministic feature-hashing embedder — the offline fallback.

Not semantically deep, but stable and dependency-free: texts sharing tokens land
closer in cosine space, which is enough to exercise the relevance cascade end to
end and to keep tests hermetic. Uses signed feature hashing over word unigrams
and bigrams, then L2-normalizes.
"""

from __future__ import annotations

import hashlib
import re

import numpy as np

from .base import Embedder, l2_normalize

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _char_ngrams(word: str, n: int = 3) -> list[str]:
    """Character n-grams (with boundary markers) so morphological variants
    like 'hex'/'hexahedral' and 'brep'/'b-rep' share features."""
    padded = f"#{word}#"
    if len(padded) <= n:
        return [f"c:{padded}"]
    return [f"c:{padded[i : i + n]}" for i in range(len(padded) - n + 1)]


def _tokens(text: str) -> list[str]:
    words = _TOKEN_RE.findall(text.lower())
    grams: list[str] = list(words)
    grams += [f"{a}_{b}" for a, b in zip(words, words[1:], strict=False)]  # word bigrams
    for w in words:
        if len(w) >= 3:
            grams += _char_ngrams(w, 3)  # subword robustness
    return grams


def _hash(token: str, dim: int) -> tuple[int, float]:
    h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    idx = int.from_bytes(h[:4], "little") % dim
    sign = 1.0 if (h[4] & 1) else -1.0
    return idx, sign


class HashingEmbedder(Embedder):
    name = "hashing"
    # Crude subword-hash cosines run much lower than dense SPECTER2 ones.
    suggested_relevance_threshold = 0.15

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for tok in _tokens(text or ""):
                idx, sign = _hash(tok, self.dim)
                out[i, idx] += sign
        return l2_normalize(out, axis=1)
