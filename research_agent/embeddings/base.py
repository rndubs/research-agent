"""Embedder interface plus small vector utilities."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class Embedder(ABC):
    """Encodes text into fixed-width vectors.

    Implementations must return an ``(n, dim)`` float32 array from
    :meth:`embed` and expose their ``dim``. A conventional input for scientific
    papers is ``f"{title}{sep}{abstract}"``.
    """

    dim: int
    name: str = "embedder"
    # A calibrated cosine cutoff for relevance filtering. It differs sharply
    # between embedders (dense SPECTER2 vectors sit much higher than the crude
    # hashing fallback), so Stage 2 uses it to auto-correct a config threshold
    # that was tuned for a different embedder when a fallback silently occurs.
    suggested_relevance_threshold: float = 0.3

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed a batch of texts -> ``(len(texts), dim)`` float32 array."""

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    @staticmethod
    def paper_text(title: str, abstract: str) -> str:
        """SPECTER-style input: title and abstract joined by [SEP]."""
        return f"{title}{SEP}{abstract}".strip()


SEP = " [SEP] "


def l2_normalize(v: np.ndarray, axis: int = -1, eps: float = 1e-12) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    norm = np.linalg.norm(v, axis=axis, keepdims=True)
    return v / np.maximum(norm, eps)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1-D vectors."""
    a = np.asarray(a, dtype=np.float32).ravel()
    b = np.asarray(b, dtype=np.float32).ravel()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-12:
        return 0.0
    return float(np.dot(a, b) / denom)
