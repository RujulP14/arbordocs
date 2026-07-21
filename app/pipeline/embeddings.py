from functools import lru_cache

import numpy as np

from app.config import settings

EMBEDDING_DIM = 384


class Embedder:
    """Wraps a local sentence-transformers model for Stage 0/1 embeddings.

    Local, not API-based (ADR-0003) — these run per-message/per-pair at
    ingestion volume, so cost matters. API-quality embeddings are reserved
    for the low-frequency Stage 3 supersession search (Phase 4).
    """

    def __init__(self, model_name: str = settings.embedding_model_name) -> None:
        self._model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, text: str) -> list[float]:
        vector = self._load().encode(text, normalize_embeddings=True)
        return vector.tolist()


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    return Embedder()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a), np.array(b)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)
