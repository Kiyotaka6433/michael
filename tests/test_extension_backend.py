"""Browser-extension backend: topic classification, URL normalisation, link notes, hub reading lists (offline)."""
import numpy as np

from michael.host import raziel


def _fake_embed(text):
    words = ("modular", "inverse", "congruence", "graph", "dijkstra", "shortest", "gradient", "descent", "loss")
    v = np.array([text.lower().count(w) for w in words], dtype=np.float32)
    return v / (np.linalg.norm(v) or 1)


def _centroids():
    topics = [("Number Theory", "Modular arithmetic"), ("DSA and Competitive Programming", "Graphs"),
              ("Machine Learning", "Optimisation")]
    m = np.stack([_fake_embed("modular inverse congruence"), _fake_embed("graph dijkstra shortest"),
                  _fake_embed("gradient descent loss")])
    return topics, m


def test_classify_ranks_the_right_topic_first():
    s = raziel.classify("Modular inverse", "The modular inverse of a modulo m solves a congruence ...",
                        embed=_fake_embed, centroids=_centroids())
    assert s[0]["subject"] == "Number Theory" and s[0]["topic"] == "Modular arithmetic"
    assert s[0]["confidence"] > 0.9 and sum(x["confidence"] for x in s) <= 1.0001


def test_urls_are_normalised():
    a = raziel.normalize_url("https://www.Example.com/post/?utm_source=x&id=3#section")
    assert a == raziel.normalize_url("https://example.com/post?id=3") == "https://example.com/post?id=3"


def test_link_note_is_written_once_per_url_and_listed_in_the_hub(tmp_path):
    p1 = raziel.link_note(tmp_path, "https://cp-algorithms.com/algebra/module-inverse.html?utm_source=x",
                          "Modular Multiplicative Inverse", "Number Theory", "Modular arithmetic", "number-theory")
    p2 = raziel.link_note(tmp_path, "https://cp-algorithms.com/algebra/module-inverse.html",
                          "Modular Multiplicative Inverse (updated)", "Number Theory", "Modular arithmetic")
    assert p1 == p2 and len(list((tmp_path / "Number Theory" / "Links").glob("*.md"))) == 1
    text = p1.read_text(encoding="utf8")
    assert 'topic: "Modular arithmetic"' in text and "michael: link" in text and "[[Number Theory]]" in text

    import importlib.util
    spec = importlib.util.spec_from_file_location("build_library", raziel.ROOT / "scripts" / "build_library.py")
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    assert b.saved_links(tmp_path / "Number Theory") == {"Modular arithmetic": [p1.stem]}


def test_link_notes_are_never_evidence(tmp_path):
    from michael.host.heralds.vault import vault_chunks
    raziel.link_note(tmp_path, "https://x.org/a", "A page", "Number Theory", "Inbox")
    assert vault_chunks(str(tmp_path)) == []
