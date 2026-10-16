"""Score Michael's own notes against the audited gold labels.

    python eval/gold_report.py   ->  eval/gold/report.md (+ prints the table)

Definitions (each sentence Michael drafted ends up SUPPORTED, PARTIAL or REMOVED):
  precision (strict)   = correct / SUPPORTED                 "a verified sentence is right"
  precision (lenient)  = (correct + partly) / SUPPORTED      "...or at least not wrong"
  wrong-in-note        = wrong among SUPPORTED + PARTIAL     errors a reader would actually see
  over-removal         = correct / REMOVED                   true sentences Michael threw away
  catch rate           = wrong REMOVED / all wrong           errors the verifier stopped
  yield                = SUPPORTED / all drafted
"""
import json
from collections import Counter
from pathlib import Path

GOLD = Path(__file__).parent / "gold"


def load():
    cands = {json.loads(l)["id"]: json.loads(l) for l in (GOLD / "candidates.jsonl").read_text(encoding="utf8").splitlines() if l.strip()}
    labels = {json.loads(l)["id"]: json.loads(l) for l in (GOLD / "gold.jsonl").read_text(encoding="utf8").splitlines() if l.strip()}
    return [{**cands[i], **labels[i]} for i in labels if i in cands]


def metrics(rows):
    c = Counter((r["system"], r["label"]) for r in rows)
    sup = sum(v for (s, _), v in c.items() if s == "SUPPORTED")
    part = sum(v for (s, _), v in c.items() if s == "PARTIAL")
    rem = sum(v for (s, _), v in c.items() if s == "REMOVED")
    wrong_total = sum(v for (_, l), v in c.items() if l == "wrong")
    pct = lambda a, b: round(100 * a / b, 1) if b else None
    return {
        "sentences": len(rows), "supported": sup, "partial": part, "removed": rem,
        "precision_strict": pct(c["SUPPORTED", "correct"], sup),
        "precision_lenient": pct(c["SUPPORTED", "correct"] + c["SUPPORTED", "partly"], sup),
        "wrong_in_note": c["SUPPORTED", "wrong"] + c["PARTIAL", "wrong"],
        "over_removal": pct(c["REMOVED", "correct"], rem),
        "catch_rate": pct(c["REMOVED", "wrong"], wrong_total),
        "yield": pct(sup, len(rows)),
        "labelers": dict(Counter(r["labeler"] for r in rows)),
    }


def main():
    rows = load()
    m = metrics(rows)
    lines = ["# Gold-set report", "",
             f"{m['sentences']} sentences from Michael's notes, labelled by: {m['labelers']} "
             "(`claude-audit` = AI-audited, not human-labelled).", "",
             "| Metric | Value | Meaning |", "|---|---|---|",
             f"| Precision (strict) | **{m['precision_strict']}%** | verified sentences that are right |",
             f"| Precision (lenient) | {m['precision_lenient']}% | verified sentences that are right or only imprecise |",
             f"| Wrong sentences left in notes | {m['wrong_in_note']} | errors a reader would see |",
             f"| Catch rate | {m['catch_rate']}% | wrong drafts the verifier removed |",
             f"| Over-removal | {m['over_removal']}% | removed sentences that were actually true |",
             f"| Yield | {m['yield']}% | drafted sentences kept as verified |", ""]
    (GOLD / "report.md").write_text("\n".join(lines), encoding="utf8")
    print("\n".join(lines))
    print(json.dumps(m))


if __name__ == "__main__":
    main()
