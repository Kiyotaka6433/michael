"""Harder maths benchmark: the claim states the formula in a DIFFERENT but equivalent form.

Text models compare surface strings, so `x^2 + 2x + 1` vs `(x+1)^2` or `\\frac{1}{\\sqrt{d}}` vs `d^{-1/2}` look
different to them. Positives: the sentence with its formula rewritten by SymPy into an equivalent form (expanded,
factored, combined, powers). Negatives: the same rewrite applied to a formula with one quantity changed.

Compared rules
  NLI only        : accept if entailment >= 0.70
  NLI + math      : as above, but reject on a math mismatch, and accept a 0.40-0.70 (PARTIAL) sentence
                    when ALL its formulas/numbers are proven equivalent (the upgrade rule in raguel.py)

    python eval/math_equivalence_benchmark.py [--n 150]
"""
import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval"))

import sympy                                                     # noqa: E402
from math_benchmark import REFERENCE, VAULT, mutate_formula      # noqa: E402
from michael.host import ophaniel                                # noqa: E402
from michael.host.heralds.mathcheck import find_math             # noqa: E402
from michael.host.scrolls import sentence_spans                  # noqa: E402

REWRITES = [sympy.expand, sympy.factor, sympy.together, sympy.cancel, sympy.powsimp,
            lambda e: sympy.expand(e, power_base=True), lambda e: e.rewrite(sympy.Pow)]


NOT_ALGEBRA = re.compile(r"[\[\],;|]|\\[cl]?dots|\\operatorname|\\text|\\mathrm|\\to\b|\\in\b|\\{|\\}|'")


def faithful(tex: str, e) -> bool:
    """SymPy kept every variable of the LaTeX (no silent loss like 'A[1]+...+A[i]' -> 'A')."""
    letters = set(re.findall(r"(?<![\\a-zA-Z])([a-zA-Z])(?![a-zA-Z])", re.sub(r"\\[a-zA-Z]+", " ", tex)))
    return letters == {str(s)[0] for s in e.free_symbols} and len(letters) >= 1


def rewrite(tex: str) -> str | None:
    """An equivalent formula written differently (or None). Plain algebra only: in CS articles '+' can be string
    concatenation and brackets are array indexing, where SymPy's rewrites would change the meaning."""
    if NOT_ALGEBRA.search(tex):
        return None
    rel, lhs, rhs = ophaniel._split_relation(tex)
    target = rhs if rhs is not None else lhs
    e = ophaniel.to_sympy(target)
    if e is None or not e.free_symbols or len(e.free_symbols) > 3 or not faithful(target, e):
        return None
    base = ophaniel._clean(target).replace(" ", "")
    for f in REWRITES:
        try:
            new = sympy.latex(f(e))
        except Exception:
            continue
        if new.replace(" ", "") != base and ophaniel.equivalent(e, ophaniel.to_sympy(new) or e) is True and len(new) < 80:
            return f"{lhs} {rel} {new}" if rhs is not None else new
    return None


def make_pairs(n: int, seed: int = 1):
    rng = random.Random(seed)
    out = []
    files = sorted(VAULT.rglob("Sources/*.md"))
    rng.shuffle(files)
    for p in files:
        text = p.read_text(encoding="utf8", errors="ignore").split("<!-- michael:")[0]
        for s, e in sentence_spans(text):
            sent = text[s:e]
            if not (30 <= len(sent) <= 260) or REFERENCE.search(sent) or "$$" in sent or sent.startswith((">", "#", "|")):
                continue
            for _, _, tex, disp in find_math(sent):
                if disp or len(tex) < 3 or not re.search(r"[+\-*/^]|\\frac|\\sqrt", tex):
                    continue
                good = rewrite(tex)
                bad_src = mutate_formula(tex, rng)
                bad = rewrite(bad_src) if bad_src else None
                if good and bad and ophaniel.compare_formula(bad, tex) is False:
                    ps, pe = text.rfind("\n", 0, s) + 1, text.find("\n", e)
                    para = text[ps:pe if pe != -1 else len(text)]
                    out.append({"note": p.stem, "evidence": para, "original": tex,
                                "true": sent.replace(f"${tex}$", f"${good}$", 1),
                                "false": sent.replace(f"${tex}$", f"${bad}$", 1)})
                    break
            if len(out) >= n:
                return out
    return out


def accept_with_math(r) -> bool:
    """The verifier's rule (raguel.py): reject on a math mismatch; upgrade a PARTIAL (0.40-0.70) sentence only when
    every formula in it was proven equivalent to the evidence."""
    formulas = [d for d in r["details"] if d[2:3] == "$"]
    complete = bool(formulas) and all(d.startswith("✓") for d in r["details"])
    return (r["entailment"] >= 0.70 and r["math"] != "mismatch") or (0.40 <= r["entailment"] < 0.70 and complete)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150)
    a = ap.parse_args()
    t0 = time.time()
    pairs = make_pairs(a.n)
    from michael.host.raguel import NLI
    flat = [(p["evidence"], p["true"]) for p in pairs] + [(p["evidence"], p["false"]) for p in pairs]
    scores = NLI().scores(flat)
    k = len(pairs)
    rows = []
    for i, p in enumerate(pairs):
        for which, claim, ent in (("true", p["true"], scores[i][0]), ("false", p["false"], scores[k + i][0])):
            mv = ophaniel.check(claim, p["evidence"])
            rows.append({"label": which, "entailment": round(ent, 3), "math": mv.status, "details": mv.details,
                         "claim": claim, "original": p["original"]})
    nli = lambda r: r["entailment"] >= 0.70
    both = accept_with_math
    pct = lambda rs, f: round(100 * sum(f(r) for r in rs) / max(1, len(rs)), 1)
    T = [r for r in rows if r["label"] == "true"]
    F = [r for r in rows if r["label"] == "false"]
    report = {"pairs": k, "seconds": round(time.time() - t0, 1),
              "true_accepted": {"nli": pct(T, nli), "nli_math": pct(T, both)},
              "false_accepted": {"nli": pct(F, nli), "nli_math": pct(F, both)},
              "math_status_true": {s: sum(r["math"] == s for r in T) for s in ("match", "mismatch", "unchecked")},
              "math_status_false": {s: sum(r["math"] == s for r in F) for s in ("match", "mismatch", "unchecked")}}
    out = ROOT / "eval" / "reports" / f"math_equivalence_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps({**report, "rows": rows}, indent=1, ensure_ascii=False), encoding="utf8")
    print(json.dumps(report, indent=1))
    for r in T[:4] + F[:3]:
        print(r["label"], r["entailment"], r["math"], "|", r["claim"][:120])
    print(f"saved {out}")


if __name__ == "__main__":
    main()
