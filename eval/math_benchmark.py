"""Maths-aware verification benchmark: does the verifier notice a wrong formula or number?

Positives: real sentences from the library's saved articles that contain a formula or a number, judged against
their own paragraph (they are true by construction).
Negatives: the same sentences with ONE quantitative detail changed - an exponent, a constant, an operator,
a big-O bound or a number - so the prose is identical and only the math is wrong.

For each pair we record the NLI entailment (DeBERTa-v3-large) and the ophaniel math verdict, then compare:
  NLI only        : accepted if entailment >= 0.70
  NLI + math      : accepted if entailment >= 0.70 and math != "mismatch"

    python eval/math_benchmark.py [--n 200]   ->  eval/reports/math_benchmark_<time>.json (+ printed table)
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

from michael.host import ophaniel                                  # noqa: E402
from michael.host.heralds.mathcheck import find_math              # noqa: E402
from michael.host.scrolls import sentence_spans                    # noqa: E402

VAULT = ROOT.parent / "Michael Vault"
REFERENCE = re.compile(r"↑|\bdoi\b|ISBN|Retrieved|Archived|\bpp\.|et al\.|arXiv:|\(\d{4}\)\.|Proceedings|Journal"
                       r"|Press\b|<sub>|<sup>", re.I)
NUM = re.compile(r"(?<![\w.$\\^_{])(\d+(?:\.\d+)?)(?![\w}])")


# ------------------------------------------------------------------ mutations (change exactly one quantity)
def mutate_formula(tex: str, rng) -> str | None:
    if re.search(r"(O|Theta|Omega)\s*\(", tex):          # big-O: only changes that alter the growth rate
        options = []
        if re.search(r"\\log\s*\\log", tex):
            options.append(lambda t: re.sub(r"\\log\s*\\log", r"\\log", t, count=1))
        elif "\\log" in tex:
            options.append(lambda t: t.replace("\\log", "\\sqrt", 1))
        if re.search(r"\^\{?\d", tex):
            options.append(lambda t: re.sub(r"\^(\{?)(\d)", lambda m: f"^{m.group(1)}{int(m.group(2)) + 1}", t, count=1))
        if not options and re.search(r"\(\s*[a-z]\s*\)", tex):
            options.append(lambda t: re.sub(r"\(\s*([a-z])\s*\)", r"(\1^2)", t, count=1))
        if not options:
            return None
        new = rng.choice(options)(tex)
        return new if new != tex else None
    options = []
    if re.search(r"\\log\s*\\log", tex):
        options.append(lambda t: re.sub(r"\\log\s*\\log", r"\\log", t, count=1))
    elif "\\log" in tex and re.search(r"O\s*\(", tex):
        options.append(lambda t: t.replace("\\log", "\\sqrt", 1))
    if re.search(r"\^\{?\d", tex):
        options.append(lambda t: re.sub(r"\^(\{?)(\d)", lambda m: f"^{m.group(1)}{int(m.group(2)) + 1}", t, count=1))
    if "\\sqrt" in tex:
        options.append(lambda t: re.sub(r"\\sqrt\{([^{}]*)\}", r"\1", t, count=1))
    if re.search(r"(?<![\^_{\d])\d+(?![\d}])", tex):
        options.append(lambda t: re.sub(r"(?<![\^_{\d])(\d+)(?![\d}])", lambda m: str(int(m.group(1)) + 2), t, count=1))
    if re.search(r"[^\\]\+", tex):
        options.append(lambda t: re.sub(r"(?<=[^\\])\+", "-", t, count=1))
    if "\\le" in tex:
        options.append(lambda t: t.replace("\\le", "\\ge", 1))
    if not options:
        return None
    new = rng.choice(options)(tex)
    return new if new != tex else None


def make_pairs(n: int, seed: int = 0):
    rng = random.Random(seed)
    candidates = []
    for p in sorted(VAULT.rglob("Sources/*.md")):
        text = p.read_text(encoding="utf8", errors="ignore").split("<!-- michael:")[0]
        for s, e in sentence_spans(text):
            sent = text[s:e]
            if not (40 <= len(sent) <= 260) or sent.startswith((">", "#", "|", "-", "*")) or "$$" in sent:
                continue
            if REFERENCE.search(sent) or re.match(r"^\d+[.)]?\s", sent):      # bibliography lines are not claims
                continue
            maths = [t for _, _, t, d in find_math(sent) if not d and 1 < len(t) < 60]
            nums = NUM.findall(re.sub(r"\$[^$]*\$", " ", sent))
            if maths or nums:
                para_s = text.rfind("\n", 0, s) + 1
                para_e = text.find("\n", e)
                candidates.append((p.stem, sent, text[para_s:para_e if para_e != -1 else len(text)], maths, nums))
    rng.shuffle(candidates)
    pairs = []
    for note, sent, para, maths, nums in candidates:
        if len(pairs) >= n:
            break
        bad, kind = None, None
        if maths:                                           # formulas first: they are what NLI struggles with
            t = rng.choice(maths)
            m = mutate_formula(t, rng)
            if m:
                bad, kind = sent.replace(f"${t}$", f"${m}$", 1), "formula"
        if bad is None and nums:
            x = rng.choice(nums)
            y = str(round(float(x) * rng.choice([1.5, 2, 0.5]) + (1 if "." not in x else 0.1), 1 if "." in x else None))
            if y != x:
                bad, kind = re.sub(rf"(?<![\w.]){re.escape(x)}(?![\w])", y, sent, count=1), "number"
        if bad and bad != sent:
            pairs.append({"note": note, "evidence": para, "true": sent, "false": bad, "kind": kind})
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--rescore", default=None, help="saved report: reuse its NLI scores, re-run only the math check")
    a = ap.parse_args()
    pairs = make_pairs(a.n)
    k = len(pairs)
    t0 = time.time()
    if a.rescore:
        old = json.loads(Path(a.rescore).read_text(encoding="utf8"))["rows"]
        scores = [(r["entailment"], 0.0) for r in old[0::2]] + [(r["entailment"], 0.0) for r in old[1::2]]
    else:
        from michael.host.raguel import NLI
        flat = [(p["evidence"], p["true"]) for p in pairs] + [(p["evidence"], p["false"]) for p in pairs]
        scores = NLI().scores(flat)
    rows = []
    for i, p in enumerate(pairs):
        for which, claim, (ent, _) in (("true", p["true"], scores[i]), ("false", p["false"], scores[k + i])):
            mv = ophaniel.check(claim, p["evidence"])
            rows.append({"kind": p["kind"], "label": which, "entailment": round(ent, 3), "math": mv.status,
                         "claim": claim, "note": p["note"]})
    def rate(sel, accept):
        sel = list(sel)
        return round(100 * sum(accept(r) for r in sel) / max(1, len(sel)), 1), len(sel)
    nli_ok = lambda r: r["entailment"] >= 0.70
    both_ok = lambda r: r["entailment"] >= 0.70 and r["math"] != "mismatch"
    report = {"pairs": k, "seconds": round(time.time() - t0, 1), "by": {}}
    for kind in ("formula", "number", "all"):
        sel = [r for r in rows if kind == "all" or r["kind"] == kind]
        report["by"][kind] = {
            "true_accepted_nli": rate((r for r in sel if r["label"] == "true"), nli_ok),
            "true_accepted_nli_math": rate((r for r in sel if r["label"] == "true"), both_ok),
            "false_accepted_nli": rate((r for r in sel if r["label"] == "false"), nli_ok),
            "false_accepted_nli_math": rate((r for r in sel if r["label"] == "false"), both_ok),
        }
    out = ROOT / "eval" / "reports" / f"math_benchmark_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({**report, "rows": rows}, indent=1, ensure_ascii=False), encoding="utf8")
    print(f"{k} pairs ({sum(p['kind'] == 'formula' for p in pairs)} formula, {sum(p['kind'] == 'number' for p in pairs)} number)")
    print(f"{'':10s} {'true kept: NLI':>16s} {'NLI+math':>10s} {'wrong accepted: NLI':>22s} {'NLI+math':>10s}")
    for kind, b in report["by"].items():
        print(f"{kind:10s} {b['true_accepted_nli'][0]:>15}% {b['true_accepted_nli_math'][0]:>9}% "
              f"{b['false_accepted_nli'][0]:>21}% {b['false_accepted_nli_math'][0]:>9}%")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
