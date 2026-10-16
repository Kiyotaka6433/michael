"""Offline tests: no network, no model downloads (fake embedder and fake NLI)."""
import numpy as np

from michael.models import Chunk, Claim, Source
from michael.host import gabriel
from michael.host.scrolls import chunk_source, sentence_spans
from michael.host.jophiel import hybrid_search, rrf, tokenize
from michael.host.uriel import lexical_candidates
from michael.host.heralds.openalex import rebuild_abstract
from michael.host.heralds.vault import vault_chunks
from michael.host.raguel import label_for, verify_claim
from michael.host.metatron import parse_sentences

TEXT = ("LACP is defined in IEEE 802.3ad. It negotiates link bundles between switches. "
        "PAgP is a Cisco proprietary protocol. Both protocols build EtherChannels.")


def test_sentence_spans_keep_exact_offsets():
    spans = sentence_spans(TEXT)
    assert [TEXT[s:e] for s, e in spans] == [
        "LACP is defined in IEEE 802.3ad.", "It negotiates link bundles between switches.",
        "PAgP is a Cisco proprietary protocol.", "Both protocols build EtherChannels."]


def test_chunks_cover_text_with_offsets():
    src = Source(kind="wikipedia", title="T", url="u", text=TEXT * 10)
    chunks = chunk_source(src, max_chars=200)
    assert len(chunks) > 1
    for c in chunks:
        assert src.text[c.start:c.end] == c.text
        assert len(c.text) <= 200


def test_rrf_prefers_items_ranked_high_in_both_lists():
    scores = rrf([[0, 1, 2], [0, 2, 1]])
    assert max(scores, key=scores.get) == 0


class FakeEmbedder:
    def chunks(self, chunks):
        return np.stack([self._vec(c.text) for c in chunks])

    def query(self, q):
        return self._vec(q)

    def _vec(self, t):
        v = np.zeros(64, np.float32)
        for tok in tokenize(t):
            v[hash(tok) % 64] += 1
        return v / (np.linalg.norm(v) or 1)


def test_hybrid_search_finds_the_relevant_chunk():
    docs = ["PAgP is a Cisco proprietary EtherChannel protocol.", "OSPF is a link-state routing protocol.",
            "Bananas are yellow fruit."]
    chunks = [Chunk(source_id=str(i), kind="t", title=str(i), url="", text=d, start=0, end=len(d)) for i, d in enumerate(docs)]
    top = hybrid_search(["What is PAgP?"], chunks, FakeEmbedder(), top_k=2)
    assert top[0].text.startswith("PAgP")


def test_lexical_candidates_point_at_the_matching_sentence():
    s, e = lexical_candidates("PAgP is proprietary to Cisco", TEXT)[0]
    assert "PAgP" in TEXT[s:e]


def test_writer_parsing_drops_unknown_citations():
    claims = parse_sentences({"sentences": [{"text": "A.", "citations": ["p1", "p9", "[p2]"]}, "B."]}, {"p1", "p2"})
    assert claims[0].citations == ["p1", "p2"]
    assert claims[1].citations == []


class FakeNLI:
    """Entailment = 0.9 if every word of the hypothesis appears in the premise, else 0.1."""

    def scores(self, pairs):
        out = []
        for premise, hyp in pairs:
            ok = set(tokenize(hyp)) <= set(tokenize(premise))
            out.append((0.9 if ok else 0.1, 0.0))
        return out


def test_verifier_picks_tight_supporting_quote():
    chunk = Chunk(source_id="s", kind="wikipedia", title="EtherChannel", url="https://x", text=TEXT, start=0,
                  end=len(TEXT), label="p1")
    v = verify_claim(Claim(index=0, sentence="PAgP is a Cisco proprietary protocol.", citations=["p1"]), {"p1": chunk}, FakeNLI())
    assert v.label == "SUPPORTED"
    assert v.quote == "PAgP is a Cisco proprietary protocol."
    assert TEXT[v.quote_start:v.quote_end] == v.quote


def test_uncited_claim_is_unsupported():
    v = verify_claim(Claim(index=0, sentence="Anything.", citations=[]), {}, FakeNLI())
    assert v.label == "UNSUPPORTED"


def test_thresholds():
    assert label_for(0.95) == "SUPPORTED" and label_for(0.5) == "PARTIAL" and label_for(0.1) == "UNSUPPORTED"


def test_openalex_abstract_rebuild():
    assert rebuild_abstract({"hello": [0], "world": [1], "again": [2]}) == "hello world again"


def test_vault_chunks_split_by_heading(tmp_path):
    (tmp_path / "Networking.md").write_text("---\ntags: [net]\n---\n# LACP\nIEEE 802.3ad.\n## PAgP\nCisco only.\n",
                                            encoding="utf8")
    (tmp_path / "Michael").mkdir()
    (tmp_path / "Michael" / "out.md").write_text("# ignored\n", encoding="utf8")
    chunks = vault_chunks(str(tmp_path))
    assert [c.heading for c in chunks] == ["LACP", "PAgP"]
    assert chunks[1].link == "[[Networking#PAgP]]"


def test_export_renders_footnotes_and_trust_panel():
    chunk = Chunk(source_id="s", kind="wikipedia", title="EtherChannel", url="https://x", text=TEXT, start=0,
                  end=len(TEXT), label="p1")
    claim = Claim(index=0, sentence="PAgP is Cisco proprietary.", citations=["p1"], status="SUPPORTED")
    v = verify_claim(Claim(index=0, sentence="PAgP is a Cisco proprietary protocol.", citations=["p1"]),
                     {"p1": chunk}, FakeNLI())
    stats = {"total": 1, "supported": 1, "partial": 0, "unsupported": 0, "removed": 0}
    md = gabriel.render("What is PAgP?", [claim], {0: v}, [chunk], [], "qwen2.5:3b", stats)
    assert "[^1]" in md and "Trust panel" in md and "[EtherChannel](https://x)" in md
    assert md.startswith("---\nquestion:")


def test_verifier_corrects_a_wrong_citation():
    good = Chunk(source_id="a", kind="t", title="A", url="", text=TEXT, start=0, end=len(TEXT), label="p1")
    other = Chunk(source_id="b", kind="t", title="B", url="", text="Bananas are yellow.", start=0, end=19, label="p2")
    claim = Claim(index=0, sentence="PAgP is a Cisco proprietary protocol.", citations=["p2"])
    v = verify_claim(claim, {"p1": good, "p2": other}, FakeNLI())
    assert v.label == "SUPPORTED" and v.evidence_label == "p1" and claim.citations == ["p1"]


def test_writer_parsing_drops_repeated_sentences():
    claims = parse_sentences({"sentences": [{"text": "A b.", "citations": ["p1"]}, {"text": "a  B.", "citations": ["p1"]}]}, {"p1"})
    assert len(claims) == 1


def test_unreachable_host_fails_fast_and_is_skipped(monkeypatch):
    import httpx
    from michael.host.heralds import http
    calls = []

    class Dead:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get(self, url, params=None):
            calls.append(url)
            raise httpx.ConnectError("getaddrinfo failed")

    monkeypatch.setattr(http, "client", lambda: Dead())
    monkeypatch.setattr(http, "_down", {})
    for _ in range(2):
        try:
            http.get("https://dead.example/x")
        except http.HostDown:
            pass
    assert len(calls) == 1          # no retries, and the second call is skipped without a request


def test_math_regions_found_outside_code():
    from michael.host.heralds.mathcheck import find_math
    found = find_math("a $x^2$ b \$5 `$no$`\n\n$$\int f$$")
    assert [(t, d) for _, _, t, d in found] == [("x^2", False), ("\int f", True)]


def test_web_math_is_protected_and_restored():
    from michael.host.heralds.webmath import protect_math, restore_math
    page = ('<html><body><p>Energy <math alttext="{\displaystyle E=mc^{2}}"><mi>E</mi></math> holds.</p>'
            '<script type="math/tex; mode=display">\sum_i x_i</script></body></html>')
    html, found = protect_math(page)
    assert "MICHAELMATH0X" in html and len(found) == 2
    text = restore_math("Energy MICHAELMATH0X holds. MICHAELMATH1X", found)
    assert "$E=mc^{2}$" in text and "$$\sum_i x_i$$" in text


def test_arxiv_ids():
    from michael.host.heralds.arxiv_latex import parse_arxiv_id
    assert parse_arxiv_id("https://arxiv.org/abs/1706.03762v7") == "1706.03762v7"
    assert parse_arxiv_id("https://arxiv.org/pdf/2101.00001") == "2101.00001"
    assert parse_arxiv_id("arXiv:hep-th/9901001") == "hep-th/9901001"
    assert parse_arxiv_id("https://example.com/1706.03762") is None


def test_long_vault_sections_are_split_not_cut(tmp_path):
    from michael.host.heralds.vault import file_chunks
    body = " ".join(f"Sentence number {i} is here." for i in range(200))
    (tmp_path / "Paper.md").write_text(f"# Method\n{body}\n", encoding="utf8")
    chunks = file_chunks(tmp_path / "Paper.md", max_chars=500)
    assert len(chunks) > 1 and all(len(c.text) <= 500 for c in chunks)
    assert "Sentence number 199" in chunks[-1].text and all(c.heading == "Method" for c in chunks)


def test_compound_contrast_sentences_are_split():
    from michael.host.metatron import split_compound
    assert split_compound("LACP is an open standard, while PAgP is Cisco proprietary.") == [
        "LACP is an open standard.", "PAgP is Cisco proprietary."]
    assert split_compound("It grows while sleeping.") == ["It grows while sleeping."]


def test_quotes_never_include_headings_or_cross_paragraphs():
    from michael.host.uriel import candidate_windows
    text = "### Multi-Head Attention\n*Figure: image*\nHeads run in parallel. They attend jointly.\n\nNext part here."
    wins = [text[s:e] for s, e in candidate_windows(text)]
    assert "Heads run in parallel." in wins and "Heads run in parallel. They attend jointly." in wins
    assert not any("#" in w or "Figure" in w or "Next part" in w and "jointly" in w for w in wins)


def test_delimited_math_from_mkdocs_and_sphinx_pages():
    from michael.host.heralds.webmath import protect_math
    page = ('<html><body><p>Let <span class="arithmatex">$a$</span> divide b.</p>'
            '<div class="arithmatex">$$a x + b y = \gcd(a, b)$$</div>'
            '<p>Sphinx <span class="math notranslate nohighlight">\(w^T x\)</span></p></body></html>')
    _, found = protect_math(page)
    assert sorted(found.values()) == sorted(["$a$", "$$a x + b y = \gcd(a, b)$$", "$w^T x$"])


def test_stackexchange_answer_text_keeps_latex_and_code():
    from michael.host.heralds.stackexchange import _text
    t = _text("<p>Use $ax+by=1$ so $x \equiv a^{-1}$.</p><pre><code>def inv(a, m):\n    return pow(a, -1, m)</code></pre>")
    assert "$ax+by=1$" in t and "pow(a, -1, m)" in t


def test_generated_notes_are_never_vault_evidence(tmp_path):
    from michael.host.heralds.vault import vault_chunks
    (tmp_path / "Real.md").write_text("# A\nReal notes.\n", encoding="utf8")
    (tmp_path / "Answer.md").write_text('---\nquestion: "x"\n---\n# x\nGenerated.\n', encoding="utf8")
    (tmp_path / "Hub.md").write_text("---\nmichael: hub\n---\n# Hub\nLinks.\n", encoding="utf8")
    assert {c.title for c in vault_chunks(str(tmp_path))} == {"Real"}


def test_multi_sentence_claims_are_checked_one_sentence_at_a_time():
    claims = parse_sentences({"sentences": [{"text": "Euclid is old. It finds the GCD of two numbers.", "citations": ["p1"]}]}, {"p1"})
    assert [c.sentence for c in claims] == ["Euclid is old.", "It finds the GCD of two numbers."]


def test_sentence_that_passes_only_in_context_needs_a_high_score():
    class OnlyParagraph:          # the window alone says nothing; the paragraph gives a middling score
        def scores(self, pairs):
            return [(0.8, 0.0) if "\n" not in p and "Transformer" in p and "41.8" in p else (0.05, 0.0) for p, _ in pairs]
    text = "We propose the Transformer. It is new. It is fast. Our model reaches 41.8 BLEU."
    chunk = Chunk(source_id="s", kind="t", title="T", url="", text=text, start=0, end=len(text), label="p1")
    v = verify_claim(Claim(index=0, sentence="The Transformer reaches 41.8 BLEU.", citations=["p1"]), {"p1": chunk}, OnlyParagraph())
    assert v.label == "PARTIAL" and v.in_context
