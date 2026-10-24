"""Study mode: multiple-choice questions made from Michael's VERIFIED facts - no LLM, so nothing new is invented.

Each question blanks one key term out of a verified sentence (a formula, a name, a number or a technical word) and
offers distractors of the same kind - from the same note first (same topic, so plausible), then the same subject.
For ordinary words the distractors share the answer's ending (-ing, -tion, ...) so grammar doesn't give it away.
After answering, the reader sees the exact source quote that proves the fact.
"""
import random
import re

from . import learning

MATH = re.compile(r"\$[^$]{1,60}\$")
NUMBER = re.compile(r"(?<![\w.$])\d+(?:\.\d+)?(?![\w.])")
NAME = re.compile(r"(?<=\s)([A-Z][a-z]{2,}(?:[\s-][A-Z][a-z]+)*)")         # capitalised, not the first word
WORD = re.compile(r"(?<![A-Za-z-])([a-z][a-z-]{6,})(?![A-Za-z-])")             # whole lower-case words only
STOP = set("""about above across after again against algorithm algorithms another because before between called
computed contains defined during either example function however instead number numbers others problem problems
should similar since therefore through typically usually various whether which within without""".split())
KINDS = ("math", "name", "number", "word")       # preferred blank, best first


def _terms(sentence: str) -> list[tuple[str, str]]:
    out = [("math", m.group(0)) for m in MATH.finditer(sentence)]
    plain = MATH.sub(" ", sentence)
    out += [("name", m.group(1)) for m in NAME.finditer(plain)    # not the tail of a longer name ("Sparse Table")
            if not plain[:m.start()].split()[-1:] or not plain[:m.start()].split()[-1][:1].isupper()]
    out += [("number", m.group(0)) for m in NUMBER.finditer(plain)]
    words = sorted({m.group(1) for m in WORD.finditer(plain) if m.group(1) not in STOP}, key=len, reverse=True)
    out += [("word", w) for w in words[:2]]
    return sorted(out, key=lambda kt: KINDS.index(kt[0]))


def _blank(sentence: str, term: str) -> str | None:
    """Replace the term as a whole word/formula (never inside a longer word)."""
    pat = re.escape(term) if term.startswith("$") else rf"(?<![A-Za-z0-9-]){re.escape(term)}(?![A-Za-z0-9-])"
    out, n = re.subn(pat, "_____", sentence, count=1)
    return out if n else None


def make_quiz(subject: str | None = None, n: int = 10, seed: int | None = None) -> list[dict]:
    rng = random.Random(seed)
    facts = [c for c in learning.query_claims("SUPPORTED", subject=subject, limit=1000)["claims"] if c.get("quote")]
    by_note, by_subject = {}, {}                  # kind -> terms, per note and per subject (distractor pools)
    for c in facts:
        for kind, term in _terms(c["sentence"]):
            by_note.setdefault((c["path"], kind), set()).add(term)
            by_subject.setdefault(kind, set()).add(term)
    rng.shuffle(facts)
    questions, used = [], set()
    for c in facts:
        low = c["sentence"].lower()
        for kind, term in _terms(c["sentence"]):
            question = _blank(c["sentence"], term)
            if not question or (c["path"], term) in used:
                continue
            ok = lambda t: t.lower() != term.lower() and t.lower() not in low
            near = sorted(t for t in by_note.get((c["path"], kind), ()) if ok(t))
            far = sorted(t for t in by_subject.get(kind, ()) if ok(t) and t not in near)
            if kind == "word":                     # same ending, so the sentence's grammar doesn't reveal the answer
                near = [t for t in near if t[-3:] == term[-3:]] or near
                far = [t for t in far if t[-3:] == term[-3:]] or far
            rng.shuffle(near)
            rng.shuffle(far)
            distractors = (near + far)[:3]
            if len(distractors) < 3:
                continue
            options = distractors + [term]
            rng.shuffle(options)
            questions.append({"question": question, "answer": term, "options": options, "kind": kind,
                              "fact": c["sentence"], "quote": c["quote"], "source": c["source"],
                              "note": c.get("rel") or c["path"]})
            used.add((c["path"], term))
            break
        if len(questions) >= n:
            break
    return questions
