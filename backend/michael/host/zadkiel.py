"""Cross-encoder reranker: reads each (question, passage) pair together; more accurate than the
bi-encoder search but too slow to run on everything, hence top 30 -> best 8."""
from ..config import settings
from ..models import Chunk


class Reranker:
    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or settings.rerank_model
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name, device="cpu", max_length=512)
        return self._model

    def rerank(self, question: str, candidates: list[Chunk], keep: int | None = None) -> list[Chunk]:
        keep = keep or settings.keep
        if not candidates:
            return []
        scores = self.model.predict([(question, c.text) for c in candidates], batch_size=16, show_progress_bar=False)
        ranked = sorted(zip(candidates, scores), key=lambda x: float(x[1]), reverse=True)[:keep]
        for c, s in ranked:
            c.score = float(s)
        return [c for c, _ in ranked]
