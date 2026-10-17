"""Ophaniel, angel of the heavenly wheels (order and precision): checks the mathematics in a claim.

NLI models read formulas as text: `$O(n^2)$` and `$O(n \\log n)$`, or `\\frac{1}{\\sqrt{d_k}}` and `\\sqrt{d_k}`, look
almost identical to them. This module checks quantitative content against the evidence:

  formulas  LaTeX -> SymPy; equivalence by evaluating both sides at random points (robust where simplify() fails)
  big-O     O(f), Θ(f), Ω(f) compared by growth rate (ratio stays bounded as n grows)
  numbers   every number in the claim's prose must appear in the evidence

check(claim, evidence) -> MathVerdict(status = "match" | "mismatch" | "unchecked", details)
A formula with no comparable formula in the evidence is "unchecked", never a mismatch: only a formula over the
same symbols that evaluates differently counts as a contradiction.
"""
import math
import random
import re
import warnings
from dataclasses import dataclass, field
from functools import lru_cache

from .heralds.mathcheck import find_math

RELATIONS = [r"\\equiv", r"\\leq?", r"\\geq?", r"\\neq", r"\\approx", r"\\sim", r"=", r"<", r">"]
ORDER = re.compile(r"^(?:\\mathcal\{O\}|O|\\Theta|\\Omega|\\operatorname\{O\})\s*(?:\\left)?\s*[(\[]")
NUMBER = re.compile(r"(?<![\w.$\\^_{])(\d+(?:[.,]\d+)?)(?:\s*%)?(?![\w}])")


@dataclass
class MathVerdict:
    status: str = "unchecked"                 # match | mismatch | unchecked
    details: list = field(default_factory=list)
    complete: bool = False                    # every formula of the claim proven equivalent to the evidence


# ------------------------------------------------------------------ LaTeX -> SymPy
def _clean(tex: str) -> str:
    tex = re.sub(r"\\(displaystyle|textstyle|left|right|big|Big|bigg|Bigg|,|;|!|quad|qquad)(?![a-zA-Z])", " ", tex)
    tex = re.sub(r"\\(mathrm|text|operatorname|mathit|mathbf|boldsymbol|mathbb)\{([^{}]*)\}", r"\2", tex)
    tex = tex.replace("\\cdot", "*").replace("\\times", "*").replace("\\lvert", "|").replace("\\rvert", "|")
    tex = re.sub(r"\\(?:bmod|mod)\b", r" \\bmod ", tex)
    return " ".join(tex.split()).strip(" .,;")


@lru_cache(maxsize=4096)
def to_sympy(tex: str):
    """A SymPy expression, or None when the LaTeX can't be parsed reliably."""
    tex = _clean(tex)
    if not tex or len(tex) > 160 or "\\begin" in tex or "\\sum" in tex or "\\prod" in tex or "\\int" in tex:
        return None
    try:
        from sympy.parsing.latex import parse_latex
        from sympy import Expr
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            e = parse_latex(tex)
        return e if isinstance(e, Expr) else None          # equations / relations inside a side: not comparable
    except Exception:
        return None


def _split_relation(tex: str):
    """'a^{p-1} \\equiv 1 \\pmod{p}' -> ('\\equiv', 'a^{p-1}', '1'); single expressions -> (None, tex, None)."""
    tex = re.sub(r"\\pmod\s*(\{[^{}]*\}|\w+)|\(\s*\\bmod\s*([^)]*)\)", "", tex)    # modulus checked as text elsewhere
    tex = tex.replace("\\phi", "phi").replace("\\varphi", "phi")
    depth, i = 0, 0
    while i < len(tex):
        ch = tex[i]
        depth += ch in "{(["
        depth -= ch in "})]"
        if depth == 0:
            for rel in RELATIONS:
                m = re.match(rel + r"(?![a-zA-Z])", tex[i:])
                if m:
                    return m.group(0), tex[:i].strip(), tex[i + m.end():].strip()
        i += 1
    return None, tex.strip(), None


def _order_arg(tex: str):
    m = ORDER.match(tex.strip())
    if not m:
        return None
    rest = tex.strip()[m.end():]
    depth, out = 1, []
    for ch in rest:
        depth += ch in "(["
        depth -= ch in ")]"
        if depth == 0:
            break
        out.append(ch)
    return "".join(out)


# ------------------------------------------------------------------ comparisons
def _values(expr, symbols, point):
    try:
        v = complex(expr.subs({s: point[s] for s in symbols}).evalf())
        return v if math.isfinite(v.real) and math.isfinite(v.imag) else None
    except Exception:
        return None


def equivalent(a, b, trials: int = 6) -> bool | None:
    """True / False when both evaluate at random points over the same symbols; None when not comparable."""
    sa, sb = a.free_symbols, b.free_symbols
    if sa != sb:
        return None
    if not sa:                       # constants: only plain arithmetic is comparable ("2^{10} = 1024"), never an
        from sympy import Function   # unknown function like \varphi(10) against some other number in the text
        if a.atoms(Function) or b.atoms(Function) or not (a.is_number and b.is_number):
            return None
    rng = random.Random(7)
    agree = tested = 0
    for _ in range(trials):
        point = {s: rng.choice([2, 3, 5, 7, 11]) + rng.random() for s in sa}
        va, vb = _values(a, sa, point), _values(b, sb, point)
        if va is None or vb is None:
            continue
        tested += 1
        agree += abs(va - vb) <= 1e-6 * max(1.0, abs(va), abs(vb))
    if tested < 2:
        return None
    return agree == tested


def same_order(a, b) -> bool | None:
    """Big-O comparison in one variable: the ratio a/b must stay bounded (no growth) between n = 1e3 and 1e9."""
    syms = a.free_symbols | b.free_symbols
    if len(syms) != 1:
        return None
    (n,) = syms
    try:
        r1 = abs(complex((a / b).subs(n, 1e3).evalf()))
        r2 = abs(complex((a / b).subs(n, 1e9).evalf()))
    except Exception:
        return None
    if not (r1 > 0 and r2 > 0 and math.isfinite(r1) and math.isfinite(r2)):
        return None
    return abs(math.log(r2 / r1)) < math.log(1.6)          # log n vs log log n etc. moves by more than this


def _sides(tex: str):
    """Parsed (relation, lhs, rhs) of a formula, plus its big-O argument if it is one."""
    rel, lhs, rhs = _split_relation(tex)
    order = _order_arg(rhs) if rhs is not None else _order_arg(lhs)
    if order is not None:
        return ("order", to_sympy(order), None)
    return (rel, to_sympy(lhs), to_sympy(rhs) if rhs is not None else None)


def compare_formula(claim_tex: str, evidence_tex: str) -> bool | None:
    """True (equivalent), False (contradicts), None (not comparable). Never raises: anything SymPy can't handle
    is simply 'not comparable', so the math check can only ever remove errors, not break verification."""
    try:
        return _compare(claim_tex, evidence_tex)
    except Exception:
        return None


def _compare(claim_tex: str, evidence_tex: str) -> bool | None:
    rel_c, l_c, r_c = _sides(claim_tex)
    rel_e, l_e, r_e = _sides(evidence_tex)
    if rel_c == "order" or rel_e == "order":
        if rel_c == rel_e == "order" and l_c is not None and l_e is not None:
            return same_order(l_c, l_e)
        return None
    if l_c is None:
        return None
    candidates = [x for x in (l_e, r_e) if x is not None]
    if r_c is None:                                   # a bare expression: compare with either side of the evidence
        results = [equivalent(l_c, x) for x in candidates]
    elif rel_c and rel_e and r_e is not None:        # two relations: compare lhs - rhs (sign-insensitive)
        d_c, d_e = l_c - r_c, l_e - r_e
        results = [equivalent(d_c, d_e), equivalent(d_c, -d_e)]
        results += [equivalent(l_c, l_e) and equivalent(r_c, r_e)] if equivalent(l_c, l_e) is not None else []
    else:
        results = [equivalent(r_c, x) for x in candidates] + [equivalent(l_c, x) for x in candidates]
    if any(r is True for r in results):
        return True
    if any(r is False for r in results):
        return False
    return None


WORDS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
WORDS.update({"thirty": "30", "forty": "40", "fifty": "50", "hundred": "100", "thousand": "1000",
              "twice": "2", "half": "0.5", "double": "2", "triple": "3"})


def _norm(n: str) -> str:
    n = n.replace(",", "")
    return n.rstrip("0").rstrip(".") if "." in n else n


def _numbers(text: str, words: bool = False) -> set[str]:
    prose = re.sub(r"\$\$.*?\$\$|\$[^$]*\$|`[^`]*`|\[\^?\d+\]|\[\[.*?\]\]", " ", text, flags=re.S)
    found = {_norm(n) for n in NUMBER.findall(prose)}
    if words:                                    # evidence may spell numbers out ("eleven tasks", "twice")
        found |= {WORDS[w] for w in re.findall(r"[a-z]+", prose.lower()) if w in WORDS}
    return found


def check(claim: str, evidence: str) -> MathVerdict:
    v = MathVerdict()
    claim_math = [t for _, _, t, _ in find_math(claim)]
    evid_math = [t for _, _, t, _ in find_math(evidence)]
    results = []
    evid_clean = {_clean(t) for t in evid_math}
    for ct in claim_math:
        outcome = True if _clean(ct) in evid_clean else None       # quoted verbatim: nothing to compute
        for et in ([] if outcome else evid_math):
            r = compare_formula(ct, et)
            if r is True:
                outcome = True
                break
            if r is False:
                outcome = False
        results.append(outcome)
        if outcome is not None:
            v.details.append(f"{'✓' if outcome else '✗'} ${ct}$")
    # numbers in the prose of the claim must appear in the evidence (formatting-insensitive)
    ev_numbers = _numbers(evidence, words=True) | {_norm(n) for t in evid_math for n in re.findall(r"\d+(?:\.\d+)?", t)}
    for n in _numbers(claim):
        if len(n) == 1 and not ev_numbers:
            continue
        ok = n in ev_numbers
        results.append(ok)
        v.details.append(f"{'✓' if ok else '✗'} {n}")
    if any(r is False for r in results):
        v.status = "mismatch"
    elif any(r is True for r in results):
        v.status = "match"
        # every formula in the claim was proven equivalent (numbers alone don't count as proof of a formula claim)
        v.complete = bool(claim_math) and all(r is True for r in results)
    return v
