"""Controlled baseline: the SAME draft sentences scored with and without the verifier.

For each writer (drafts_7b.jsonl, drafts_3b.jsonl from baseline_drafts.py) every draft sentence has a correctness
label (gold label if the sentence was audited before, else eval/baseline/labels.jsonl) and the verifier's verdict.

  without verifier : every draft is shown
  with verifier    : only SUPPORTED drafts are shown (no repair/rescue, so this isolates the filter itself)

    python eval/baseline_controlled.py            # report  (+ writes unlabelled.txt for anything missing)
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
B = ROOT / "eval" / "baseline"
norm = lambda s: " ".join(s.strip("=").split())
jl = lambda p: [json.loads(l) for l in p.read_text(encoding="utf8").splitlines() if l.strip()] if p.exists() else []


def labels_for(drafts):
    cands = {c["id"]: c for c in jl(ROOT / "eval/gold/candidates.jsonl")}
    gold = {(cands[g["id"]]["note"], norm(cands[g["id"]]["sentence"])): g["label"]
            for g in jl(ROOT / "eval/gold/gold.jsonl") if g["id"] in cands}
    own = {r["id"]: r["label"] for r in jl(B / "labels.jsonl")}
    return [gold.get((d["note"], norm(d["sentence"]))) or own.get(d["id"]) for d in drafts]


def stats(rows):
    n = len(rows)
    pct = lambda v: round(100 * sum(l == v for l in rows) / max(1, n), 1)
    return {"n": n, "correct": pct("correct"), "partly": pct("partly"), "wrong": pct("wrong")}


def main():
    report, missing = {}, []
    for name in ("7b", "3b"):
        drafts = jl(B / f"drafts_{name}.jsonl")
        if not drafts:
            continue
        labels = labels_for(drafts)
        missing += [d for d, l in zip(drafts, labels) if not l]
        lab = [(d, l) for d, l in zip(drafts, labels) if l]
        shown = [l for d, l in lab if d["verdict"] == "SUPPORTED"]
        dropped = [l for d, l in lab if d["verdict"] != "SUPPORTED"]
        report[name] = {"drafts": len(drafts), "labelled": len(lab),
                        "without_verifier": stats([l for _, l in lab]),
                        "with_verifier": stats(shown),
                        "removed_by_verifier": stats(dropped),
                        "wrong_caught": f"{sum(l == 'wrong' for l in dropped)}/{sum(l == 'wrong' for _, l in lab)}",
                        "correct_lost": f"{sum(l == 'correct' for l in dropped)}/{sum(l == 'correct' for _, l in lab)}"}
    with (B / "unlabelled.txt").open("w", encoding="utf8") as f:
        for d in missing:
            f.write(f"### {d['id']}  [{d['verdict']} {d['entailment']}]  {d['note']}\nS: {d['sentence']}\n"
                    f"E: {d['cited_text'][:900]}\n\n")
    (ROOT / "eval/reports").mkdir(exist_ok=True)
    (ROOT / "eval/reports/baseline_controlled.json").write_text(json.dumps(report, indent=1), encoding="utf8")
    print(json.dumps(report, indent=1))
    print(f"{len(missing)} unlabelled -> {B / 'unlabelled.txt'}")


if __name__ == "__main__":
    main()
