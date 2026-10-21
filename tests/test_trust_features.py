"""Subject substitution ("It ..." -> "Merge sort ..."), conflict flags between sources, and how both reach the note."""
from michael.config import settings
from michael.host import gabriel
from michael.host.jophiel import tokenize
from michael.host.raguel import decontextualise, subject_of, verify_claims
from michael.learning import parse_note_claims
from michael.models import Chunk, Claim


class FakeNLI:
    """Entailment 0.9 if every word of the hypothesis is in the premise; contradiction 0.95 if the premise says
    'never' and the hypothesis doesn't."""

    def scores(self, pairs):
        out = []
        for premise, hyp in pairs:
            if "never" in premise.lower() and "never" not in hyp.lower():
                out.append((0.05, 0.95))
                continue
            out.append((0.9 if set(tokenize(hyp)) <= set(tokenize(premise)) else 0.1, 0.0))
        return out


def chunk(label, title, text, source=None):
    return Chunk(source_id=source or title, kind="vault", title=title, url=title, text=text, start=0, end=len(text),
                 label=label)


def test_subject_of_strips_site_labels():
    assert subject_of("Dijkstra Algorithm (cp-algorithms)") == "Dijkstra Algorithm"
    assert subject_of("Quicksort (Princeton Algorithms)") == "Quicksort"
    assert subject_of("Merge sort - key points") == "Merge sort"


def test_decontextualise_only_rewrites_leading_pronouns():
    assert decontextualise("It runs in linear time.", "Counting sort") == "Counting sort runs in linear time."
    assert decontextualise("This algorithm is stable.", "Merge sort") == "Merge sort is stable."
    assert decontextualise("Its height is logarithmic.", "Heap") is None          # not a leading subject
    assert decontextualise("It splits Merge sort input.", "Merge sort") is None   # subject already named


def test_pronoun_sentence_is_verified_after_substitution(monkeypatch):
    monkeypatch.setattr(settings, "decontextualise", True)
    ev = {"p1": chunk("p1", "Counting sort", "Counting sort runs in linear time when keys are small.")}
    claims = [Claim(index=0, sentence="It runs in linear time.", citations=["p1"])]
    v = verify_claims(claims, ev, FakeNLI(), recite=False)[0]
    assert v.label == "SUPPORTED"
    assert claims[0].sentence == "Counting sort runs in linear time."            # the note shows the clear version


def test_contradicting_source_is_flagged_and_rendered(monkeypatch):
    monkeypatch.setattr(settings, "conflict_check", True)
    ev = {"p1": chunk("p1", "Quicksort", "Quicksort is stable in this variant."),
          "p2": chunk("p2", "Sorting", "Quicksort is never stable in its usual form.")}
    claims = [Claim(index=0, sentence="Quicksort is stable.", citations=["p1"])]
    v = verify_claims(claims, ev, FakeNLI(), recite=False)[0]
    assert v.label == "SUPPORTED" and v.conflict_label == "p2"
    md = gabriel.render("Q?", claims, {0: v}, list(ev.values()), [], "m",
                        {"supported": 1, "total": 1, "partial": 0, "unsupported": 0, "removed": 0})
    assert "appears to disagree" in md and "never stable" in md
    rows = parse_note_claims("---\nquestion: x\n---\n" + md)
    assert rows[0]["conflict"].startswith("[[Sorting")


def test_no_flag_from_the_same_source(monkeypatch):
    monkeypatch.setattr(settings, "conflict_check", True)
    ev = {"p1": chunk("p1", "Quicksort", "Quicksort is stable in this variant.", source="qs"),
          "p2": chunk("p2", "Quicksort", "Quicksort is never stable in its usual form.", source="qs")}
    claims = [Claim(index=0, sentence="Quicksort is stable.", citations=["p1"])]
    assert verify_claims(claims, ev, FakeNLI(), recite=False)[0].conflict_label == ""


def test_split_claim_gives_each_part_the_subject():
    from michael.host.raguel import split_claim
    assert split_claim("Kruskal's algorithm was described by Kruskal in 1956 and combines edges in sorted order.") == [
        "Kruskal's algorithm was described by Kruskal in 1956.", "Kruskal's algorithm combines edges in sorted order."]
    assert split_claim("Cats and dogs are pets.") is None                    # "and" inside the subject: no split


def test_compound_sentence_is_proven_part_by_part(monkeypatch):
    monkeypatch.setattr(settings, "decompose", True)
    ev = {"p1": chunk("p1", "Kruskal", "Kruskal's algorithm was described by Kruskal in 1956."),
          "p2": chunk("p2", "MST", "Kruskal's algorithm combines edges in sorted order.")}
    claims = [Claim(index=0, sentence="Kruskal's algorithm was described by Kruskal in 1956 and combines edges in "
                                      "sorted order.", citations=["p1"])]
    v = verify_claims(claims, ev, FakeNLI(), recite=True)[0]
    assert v.label == "SUPPORTED" and v.parts == 2 and " … " in v.quote


def test_compound_sentence_with_one_false_part_stays_unproven(monkeypatch):
    monkeypatch.setattr(settings, "decompose", True)
    ev = {"p1": chunk("p1", "Kruskal", "Kruskal's algorithm was described by Kruskal in 1956.")}
    claims = [Claim(index=0, sentence="Kruskal's algorithm was described by Kruskal in 1956 and runs in linear time.",
                    citations=["p1"])]
    assert verify_claims(claims, ev, FakeNLI(), recite=True)[0].label != "SUPPORTED"


def test_quote_with_pronoun_passes_with_title_context_and_is_marked(monkeypatch):
    class TitleNLI(FakeNLI):          # entailed only when the premise names the subject
        def scores(self, pairs):
            return [(0.9 if "Dynamic programming" in p else 0.05, 0.0) for p, h in pairs]
    monkeypatch.setattr(settings, "titled_premise", True)
    ev = {"p1": chunk("p1", "Dynamic programming", "In both contexts, it refers to simplifying a complicated problem by "
                                                   "breaking it down into simpler sub-problems in a recursive manner.")}
    claims = [Claim(index=0, sentence="Dynamic programming simplifies a complicated problem by breaking it down into "
                                      "simpler sub-problems in a recursive manner.", citations=["p1"])]
    v = verify_claims(claims, ev, TitleNLI(), recite=False)[0]
    assert v.label == "SUPPORTED" and v.titled
    md = gabriel.render("Q?", claims, {0: v}, list(ev.values()), [], "m",
                        {"supported": 1, "total": 1, "partial": 0, "unsupported": 0, "removed": 0})
    assert "judged with its source title as context" in md
    assert '"In both contexts, it refers to simplifying' in md          # the quote itself is unchanged


def test_title_context_never_rescues_a_quote_about_something_else(monkeypatch):
    class TitleNLI(FakeNLI):          # a model fooled by the title alone
        def scores(self, pairs):
            return [(0.99 if "Sieve" in p else 0.05, 0.0) for p, h in pairs]
    monkeypatch.setattr(settings, "titled_premise", True)
    ev = {"p1": chunk("p1", "Sieve of Eratosthenes", "If any integer n is composite, then n has a prime divisor at most sqrt n.")}
    claims = [Claim(index=0, sentence="To find all primes up to n, create a list of consecutive integers from 2 through n.",
                    citations=["p1"])]
    assert verify_claims(claims, ev, TitleNLI(), recite=False)[0].label != "SUPPORTED"


def test_fact_spanning_two_source_sentences_passes_with_two_quotes(monkeypatch):
    class JoinNLI(FakeNLI):           # entailed only when both facts are in the premise
        def scores(self, pairs):
            # joined quotes need the paragraph bar (0.90): 0.95 passes
            return [(0.95 if ("iterations" in p and "smallest" in p and "filler" not in p) else 0.05, 0.0)
                    for p, h in pairs]
    monkeypatch.setattr(settings, "two_quotes", True)
    monkeypatch.setattr(settings, "titled_premise", False)
    monkeypatch.setattr(settings, "decompose", False)
    text = ("The algorithm runs for n iterations over the vertices. Unrelated filler about graphs here. "
            "More filler about trees. Even more filler about heaps. Still more filler about paths. "
            "Each iteration selects the unmarked vertex with the smallest distance.")
    ev = {"p1": chunk("p1", "Dijkstra", text)}
    claims = [Claim(index=0, sentence="The algorithm runs for n iterations, selecting the unmarked vertex with the "
                                      "smallest distance.", citations=["p1"])]
    v = verify_claims(claims, ev, JoinNLI(), recite=False)[0]
    assert v.label == "SUPPORTED" and " … " in v.quote and "Unrelated filler" not in v.quote
