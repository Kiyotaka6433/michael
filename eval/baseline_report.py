"""Baseline vs Michael: are the writer's drafts (no verifier) as accurate as the verified notes?

Labels: drafts identical to an already-audited sentence reuse its gold label; the rest are in
eval/baseline/labels.jsonl (claude-audit). Prints and saves the comparison for the same 14 notes.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
B = ROOT / "eval" / "baseline"
norm = lambda s: " ".join(s.strip("=").split())


def main():
    cands = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "eval/gold/candidates.jsonl").read_text(encoding="utf8").splitlines() if l.strip()}
    gold = {}
    for l in (ROOT / "eval/gold/gold.jsonl").read_text(encoding="utf8").splitlines():
        if l.strip():
            g = json.loads(l)
            if g["id"] in cands:
                c = cands[g["id"]]
                gold[(c["note"], norm(c["sentence"]))] = (g["label"], c["system"])
    own = {json.loads(l)["id"]: json.loads(l)["label"] for l in (B / "labels.jsonl").read_text(encoding="utf8").splitlines() if l.strip()}
    drafts = [json.loads(l) for l in (B / "drafts.jsonl").read_text(encoding="utf8").splitlines() if l.strip()]
    labels = [gold[(d["note"], norm(d["sentence"]))][0] if (d["note"], norm(d["sentence"])) in gold else own.get(d["id"])
              for d in drafts]
    labels = [l for l in labels if l]
    notes = {d["note"] for d in drafts}
    final = [(lab, sys_) for (note, _), (lab, sys_) in gold.items() if note in notes and sys_ in ("SUPPORTED", "PARTIAL")]
    pct = lambda xs, v: round(100 * sum(x == v for x in xs) / max(1, len(xs)), 1)
    out = {
        "notes": len(notes),
        "baseline_drafts": len(labels), "baseline_correct_pct": pct(labels, "correct"),
        "baseline_partly_pct": pct(labels, "partly"), "baseline_wrong_pct": pct(labels, "wrong"),
        "michael_shown": len(final), "michael_correct_pct": pct([l for l, _ in final], "correct"),
        "michael_partly_pct": pct([l for l, _ in final], "partly"), "michael_wrong_pct": pct([l for l, _ in final], "wrong"),
    }
    (ROOT / "eval/reports").mkdir(exist_ok=True)
    (ROOT / "eval/reports/baseline_comparison.json").write_text(json.dumps(out, indent=1), encoding="utf8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
