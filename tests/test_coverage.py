"""Coverage map counts verified facts per source article from the claims table."""
import json

from michael import coverage, db, learning


def test_coverage_counts_citing_facts(tmp_path, monkeypatch):
    (tmp_path / "library").mkdir()
    (tmp_path / "library" / "manifest.json").write_text(json.dumps({"subjects": [{"name": "S", "topics": [
        {"name": "T", "items": ["wiki:A", "wiki:B"]}]}]}), encoding="utf8")
    (tmp_path / "library" / "state.json").write_text(json.dumps({
        "wiki:A": {"status": "saved", "path": "S/Sources/A.md", "title": "A"},
        "wiki:B": {"status": "saved", "path": "S/Sources/B.md", "title": "B"},
        "topic:S/T": {"supported": 2}}), encoding="utf8")
    monkeypatch.setattr(coverage, "ROOT", tmp_path)
    learning.init()
    with db.connect() as con:
        con.execute("DELETE FROM note_claims")
        con.execute("INSERT INTO note_claims (path, idx, sentence, status, entailment, quote, source, in_context, math, conflict) "
                    "VALUES ('n.md', 0, 's', 'SUPPORTED', 0.9, 'q', '[[A#x]]', 0, '', '')")
    c = coverage.coverage()
    t = c["subjects"][0]["topics"][0]
    assert {s["note"]: s["verified_facts"] for s in t["sources"]} == {"A": 1, "B": 0}
    assert t["unused_sources"] == 1 and t["thin"] is True and c["summary"]["cited_by_verified_facts"] == 1
