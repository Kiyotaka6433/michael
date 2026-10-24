"""Instant answers: verified facts ranked by meaning (fake embedder: shared words)."""
import numpy as np

from michael import db, learning
from michael.host import archangel

VOCAB = ["dropout", "overfitting", "dijkstra", "negative", "weights", "graph"]


class FakeEmbedder:
    def _v(self, t):
        v = np.array([float(w in t.lower()) for w in VOCAB]) + 1e-6
        return v / np.linalg.norm(v)

    def chunks(self, chunks):
        return np.stack([self._v(c.text) for c in chunks])

    def query(self, t):
        return self._v(t)


def test_semantic_facts_ranks_by_meaning(monkeypatch):
    monkeypatch.setattr(archangel, "EMBEDDER", FakeEmbedder())
    learning._fact_index.update(key=None)
    learning.init()
    with db.connect() as con:
        con.execute("DELETE FROM note_claims")
        for i, s in enumerate(["Dropout reduces overfitting.", "Dijkstra fails with negative weights in a graph."]):
            con.execute("INSERT INTO note_claims (path, idx, sentence, status, entailment, quote, source, in_context, "
                        "math, conflict) VALUES ('n.md', ?, ?, 'SUPPORTED', 0.9, 'q', '[[S]]', 0, '', '')", (i, s))
    top = learning.semantic_facts("does dijkstra work with negative weights", k=1, min_score=0.1)
    assert top[0]["fact"].startswith("Dijkstra")
