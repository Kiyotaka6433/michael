"""Collect every sentence Michael wrote in the vault's generated notes, with its verdict and quote, for labelling.

    python eval/extract_claims.py [--vault PATH]  ->  eval/gold/candidates.jsonl

Each row: note, sentence, system ("SUPPORTED" | "PARTIAL" | "REMOVED"), quote, source link, entailment.
Labels are added to eval/gold/gold.jsonl as {"id", "label": "correct" | "wrong" | "partly", "reason", "labeler"}.
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "eval" / "gold" / "candidates.jsonl"
FOOT = re.compile(r'^\[\^(\d+)\]: "(.*)" - (\[\[.*?\]\]|\[.*?\]\(.*?\)) · (\w+)(?: in the context of its paragraph)? \(entailment ([\d.]+)\)', re.M)


def note_claims(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf8", errors="ignore")
    if not re.search(r"(?m)^question:", text[:400]):
        return []
    feet = {m.group(1): {"quote": m.group(2), "source": m.group(3), "verdict": m.group(4).upper(),
                         "entailment": float(m.group(5))} for m in FOOT.finditer(text)}
    body = text.split("> Verifier:", 1)[-1].split("\n## ", 1)[0]
    rows = []
    # sentences end with [^n] (optionally followed by a warning icon); highlighted ==...== means PARTIAL
    for m in re.finditer(r"(==)?([^\[\n]+?)(==)?\[\^(\d+)\]", body):
        f = feet.get(m.group(4), {})
        rows.append({"note": path.name, "sentence": m.group(2).strip().lstrip("⚠✗ ").strip(), "system": f.get("verdict", "?"),
                     "quote": f.get("quote", ""), "source": f.get("source", ""), "entailment": f.get("entailment")})
    removed = text.split("## Removed claims", 1)
    if len(removed) == 2:
        for s in re.findall(r"^- ~~(.*)~~$", removed[1].split("\n## ", 1)[0], re.M):
            rows.append({"note": path.name, "sentence": s, "system": "REMOVED", "quote": "", "source": "",
                         "entailment": None})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=str(ROOT.parent / "Michael Vault"))
    a = ap.parse_args()
    rows = []
    for p in sorted(Path(a.vault).rglob("*.md")):
        if any(part in ("Topics", "Key points", "Michael") for part in p.parts):
            rows += note_claims(p)
    for i, r in enumerate(rows):
        r["id"] = f"c{i:04d}"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf8")
    by = {}
    for r in rows:
        by[r["system"]] = by.get(r["system"], 0) + 1
    print(f"{len(rows)} sentences from generated notes -> {OUT}  {by}")


if __name__ == "__main__":
    main()
