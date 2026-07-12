"""SPECTER2 embedder (allenai/specter2) — the real scientific-doc embedder.

Requires the ``embeddings`` extra (torch + transformers + adapters). Imports are
lazy so the base package stays installable without a deep-learning stack; the
:func:`~research_agent.embeddings.get_embedder` factory catches import/load
errors and falls back to hashing.
"""

from __future__ import annotations

import numpy as np

from .base import Embedder, l2_normalize


class Specter2Embedder(Embedder):
    name = "specter2"

    def __init__(
        self,
        model_name: str = "allenai/specter2_base",
        adapter: str = "allenai/specter2",
        batch_size: int = 16,
        device: str | None = None,
    ) -> None:
        import torch  # noqa: F401
        from transformers import AutoModel, AutoTokenizer

        self.batch_size = batch_size
        self._torch = __import__("torch")
        self.device = device or ("cuda" if self._torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name)
        try:
            # Proximity adapter improves near-duplicate / similarity behavior.
            self.model.load_adapter(adapter, source="hf", set_active=True)
        except Exception:
            pass
        self.model.to(self.device)
        self.model.eval()
        self.dim = int(self.model.config.hidden_size)

    def embed(self, texts: list[str]) -> np.ndarray:
        torch = self._torch
        vecs: list[np.ndarray] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            enc = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=512,
            ).to(self.device)
            with torch.no_grad():
                out = self.model(**enc)
            # SPECTER2 uses the [CLS]/first-token representation.
            cls = out.last_hidden_state[:, 0, :].cpu().numpy().astype(np.float32)
            vecs.append(cls)
        arr = np.vstack(vecs) if vecs else np.zeros((0, self.dim), dtype=np.float32)
        return l2_normalize(arr, axis=1)
