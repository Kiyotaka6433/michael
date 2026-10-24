"""Score the extractive-style drafts (eval/extractive_drafts.py) through the full pipeline - verify, rescue, repair -
exactly as eval/gate_repair.py does for the original drafts, then compare with the original 7B drafts.

The measure is what a reader gets: CORRECT verified sentences per note (and wrong ones shown). The shown sentences of
the extractive run are new, so they need labels: eval/baseline/extractive_labels.jsonl (id, label: correct / partly /
wrong); unlabelled ones are written to eval/baseline/extractive_unlabelled.txt.

    python eval/extractive_score.py            (uses the writer model for repairs; resumable per note)
    python eval/extractive_score.py --report
"""
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval"))

B = ROOT / "eval" / "baseline"
DRAFTS = B / "drafts_7b_extractive.jsonl"
ROWS = ROOT / "eval" / "reports" / "extractive_score.rows.jsonl"
OUT = ROOT / "eval" / "reports" / "extractive_score.json"
LABELS = B / "extractive_labels.jsonl"
jl = lambda p: [json.loads(l) for l in p.read_text(encoding="utf8").splitlines() if l.strip()] if p.exists() else []


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    from gate import baseline_evidence
    from gate_repair import question_for
    from baseline_drafts import pool_paths_by_note
    from michael.host.archangel import verify_and_repair
    from michael.host.heralds.vault import file_chunks
    from michael.models import Claim
    pools, paths = baseline_evidence(), pool_paths_by_note()
    done = {r["note"] for r in jl(ROWS)}
    by_note = {}
    for d in jl(DRAFTS):
        by_note.setdefault(d["note"], []).append(d)
    for note, ds in by_note.items():
        if note in done:
            continue
        evidence = [deepcopy(c) for c in pools.get(note, [])]
        labels = {c.label for c in evidence}
        claims = [Claim(index=i, sentence=d["sentence"], citations=[l for l in d["citations"] if l in labels])
                  for i, d in enumerate(ds)]
        pool = [ch for p in paths.get(note, []) for ch in file_chunks(Path(p))]
        kept, verdicts, _ = verify_and_repair(question_for(note), claims, evidence, pool=pool)
        with ROWS.open("a", encoding="utf8") as f:
            for c in kept:
                if c.status != "SUPPORTED":
                    continue
                v = verdicts.get(c.index)
                f.write(json.dumps({"id": ds[c.index]["id"], "note": note, "draft": ds[c.index]["sentence"],
                                    "final": c.sentence, "quote": v.quote if v else ""}, ensure_ascii=False) + "\n")
            if not any(c.status == "SUPPORTED" for c in kept):
                f.write(json.dumps({"id": "", "note": note, "draft": "", "final": "", "quote": ""}) + "\n")
        print(f"{note}: {sum(c.status == 'SUPPORTED' for c in kept)}/{len(ds)} verified", flush=True)
    report()


def report():
    rows = [r for r in jl(ROWS) if r["id"]]
    notes = {r["note"] for r in jl(ROWS)}
    labels = {r["id"]: r["label"] for r in jl(LABELS)}
    with (B / "extractive_unlabelled.txt").open("w", encoding="utf8") as f:
        for r in rows:
            if r["id"] not in labels:
                f.write(f"### {r['id']}  {r['note']}\nSHOWN: {r['final']}\nQUOTE: {r['quote'][:600]}\n\n")
    lab = [labels[r["id"]] for r in rows if r["id"] in labels]
    # the original 7B drafts on the same notes, same pipeline (quote repair on): eval/gate_repair.py GATE_TAG=quote
    writer = {d["id"] for d in jl(B / "drafts_7b.jsonl")}
    orig = [r for r in jl(ROOT / "eval" / "reports" / "gate_repair_quote.rows.jsonl")
            if r["id"] in writer and r["note"] in notes and r["status"] == "SUPPORTED"]
    rl = {r["id"]: r["label"] for r in jl(B / "repair_labels_quote.jsonl")}
    olab = [rl.get(r["id"]) if r["rewritten"] else r["label"] for r in orig]
    n = max(1, len(notes))
    rep = {"notes": len(notes),
           "extractive": {"shown": len(rows), "unlabelled": len(rows) - len(lab),
                          "correct_per_note": round(sum(l == "correct" for l in lab) / n, 2),
                          "wrong": sum(l == "wrong" for l in lab), "partly": sum(l == "partly" for l in lab)},
           "original_7b": {"shown": len(orig), "correct_per_note": round(sum(l == "correct" for l in olab) / n, 2),
                           "wrong": sum(l == "wrong" for l in olab), "partly": sum(l == "partly" for l in olab)}}
    OUT.write_text(json.dumps(rep, indent=1), encoding="utf8")
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    report() if "--report" in sys.argv else main()
