"""List every sentence in the vault that passed only with its source title as context, with its quote and the
word overlap between them, for a hand check (eval/audit_titled.md).

    python eval/audit_titled.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from rapidfuzz import fuzz                          # noqa: E402
from michael.learning import FOOT, SENT             # noqa: E402

VAULT = ROOT.parent / "Michael Vault"
MARK = "judged with its source title"


def rows():
    for p in sorted(VAULT.rglob("*.md")):
        if "Archive" in p.parts:
            continue
        t = p.read_text(encoding="utf8", errors="ignore")
        if MARK not in t:
            continue
        feet = {m.group(1): m for m in FOOT.finditer(t)}
        body = t.split("> Verifier:", 1)[-1].split("\n## ", 1)[0]
        for m in SENT.finditer(body):
            f = feet.get(m.group(4))
            if f and MARK in t[f.start():t.find("\n", f.start())]:
                s = m.group(2).strip().strip("=")
                yield p.relative_to(VAULT).as_posix(), s, f.group(2), fuzz.token_set_ratio(s, f.group(2))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    rs = list(rows())
    lines = [f"# Title-context sentences ({len(rs)})", ""]
    for i, (note, s, q, ov) in enumerate(rs, 1):
        lines += [f"{i}. **{note}** (overlap {ov:.0f})", f"   - S: {s}", f"   - Q: {q}", ""]
    (ROOT / "eval" / "audit_titled.md").write_text("\n".join(lines), encoding="utf8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
