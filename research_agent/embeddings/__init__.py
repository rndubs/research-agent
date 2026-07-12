"""Embeddings: SPECTER2 with a deterministic offline fallback.

Relevance filtering scores each paper against a seed-set centroid using
scientific-document embeddings (SPECTER2). When torch/transformers or the model
weights aren't available, we fall back to a :class:`HashingEmbedder` so the
whole pipeline still runs and its tests stay hermetic.
"""

from __future__ import annotations

from ..config import EmbeddingConfig
from .base import Embedder, cosine_similarity, l2_normalize
from .hashing import HashingEmbedder

__all__ = [
    "Embedder",
    "HashingEmbedder",
    "get_embedder",
    "cosine_similarity",
    "l2_normalize",
]


def get_embedder(config: EmbeddingConfig) -> Embedder:
    """Build the configured embedder, degrading to hashing when needed."""
    if config.provider == "hashing":
        return HashingEmbedder(dim=config.hashing_dim)
    if config.provider == "specter2":
        try:
            from .specter2 import Specter2Embedder

            return Specter2Embedder(model_name=config.model_name, batch_size=config.batch_size)
        except Exception as exc:  # torch/transformers/adapters missing or offline
            if config.fallback_to_hashing:
                import logging

                logging.getLogger(__name__).warning(
                    "SPECTER2 unavailable (%s); falling back to HashingEmbedder", exc
                )
                return HashingEmbedder(dim=config.hashing_dim)
            raise
    raise ValueError(f"Unknown embedding provider: {config.provider!r}")
