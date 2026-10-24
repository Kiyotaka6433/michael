"""check_text (fact-check any text) and the MCP server's tool list - offline, with a fake verifier."""
import asyncio

from michael.host import archangel
from michael.host.jophiel import tokenize


class FakeNLI:
    def __init__(self, score=0.9):
        self.score = score

    def scores(self, pairs):
        return [(self.score if set(tokenize(h)) <= set(tokenize(p)) else 0.05, 0.0) for p, h in pairs]


def test_check_text_against_given_evidence(monkeypatch):
    monkeypatch.setattr(archangel, "VERIFIER", FakeNLI())
    r = archangel.check_text("Fenwick trees answer prefix sums quickly. Penguins can fly across the ocean.",
                             evidence_text="Fenwick trees answer prefix sums quickly and support point updates.")
    verdicts = [s["verdict"] for s in r["sentences"]]
    assert verdicts == ["SUPPORTED", "UNSUPPORTED"]
    assert r["summary"] == {"sentences": 2, "supported": 1, "partial": 0, "unsupported": 1}
    assert "Fenwick trees answer prefix sums quickly" in r["sentences"][0]["quote"]


def test_library_check_needs_the_higher_bar(monkeypatch):
    """Passages found by search (not chosen for the sentence): 0.8 is only partial there."""
    from michael import vault_index
    hit = {"id": "c1", "path": "x.md", "title": "Fenwick tree", "text": "Fenwick trees answer prefix sums quickly.",
           "start": 0, "end_": 41, "heading": "Fenwick tree"}
    monkeypatch.setattr(vault_index, "search", lambda *a, **k: [hit])
    monkeypatch.setattr(archangel, "VERIFIER", FakeNLI(0.8))
    r = archangel.check_text("Fenwick trees answer prefix sums quickly.")
    assert r["sentences"][0]["verdict"] == "PARTIAL"
    monkeypatch.setattr(archangel, "VERIFIER", FakeNLI(0.95))
    assert archangel.check_text("Fenwick trees answer prefix sums quickly.")["sentences"][0]["verdict"] == "SUPPORTED"


def test_mcp_server_exposes_the_tools():
    from michael.mcp_server import server
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"check_facts", "search_library", "read_note", "verified_facts", "quiz", "library_gaps",
                     "research_start", "research_result"}
