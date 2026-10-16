"""Embeddings (with a SQLite cache) and hybrid BM25 + dense search fused with reciprocal rank fusion."""
import re

import numpy as np
from rank_bm25 import BM25Okapi

from .. import db
from ..config import settings
from ..models import Chunk, sha

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "   # bge models expect this on queries
_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class Embedder:
    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or settings.embed_model
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name, device="cpu")
        return self._model

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self.model.encode(texts, normalize_embeddings=True, batch_size=32,
                                            show_progress_bar=False), dtype=np.float32)

    def query(self, text: str) -> np.ndarray:
        return self.encode([QUERY_PREFIX + text])[0]

    def chunks(self, chunks: list[Chunk]) -> np.ndarray:
        """Embed chunk texts, reusing cached vectors (keyed by content hash)."""
        hashes = [sha(c.text) for c in chunks]
        cached = db.get_embeddings(hashes, self.model_name)
        missing = [i for i, h in enumerate(hashes) if h not in cached]
        if missing:
            vecs = self.encode([chunks[i].text for i in missing])
            fresh = {hashes[i]: v for i, v in zip(missing, vecs)}
            db.put_embeddings(fresh, self.model_name)
            cached.update(fresh)
        return np.stack([cached[h] for h in hashes]) if chunks else np.zeros((0, 1), np.float32)


def rrf(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    """Reciprocal rank fusion: sum of 1 / (k + rank) over every ranking list."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return scores


def hybrid_search(queries: list[str], chunks: list[Chunk], embedder, top_k: int | None = None) -> list[Chunk]:
    """BM25 and dense rankings for every query, fused with RRF. Returns the top_k chunks with .score set."""
    top_k = top_k or settings.candidates
    if not chunks:
        return []
    bm25 = BM25Okapi([tokenize(c.text) or ["_"] for c in chunks])
    vecs = embedder.chunks(chunks)
    rankings = []
    for q in queries:
        rankings.append(list(np.argsort(-bm25.get_scores(tokenize(q) or ["_"]))))
        rankings.append(list(np.argsort(-(vecs @ embedder.query(q)))))
    fused = rrf(rankings)
    best = sorted(fused, key=fused.get, reverse=True)[:top_k]
    out = []
    for i in best:
        chunks[i].score = fused[i]
        out.append(chunks[i])
    return out
