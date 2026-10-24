"""Recall of the FULL pipeline, repair included: verify -> claim-driven retrieval -> LLM repair -> re-verify, on the
198 labelled baseline drafts against each note's evidence pool.

eval/gate.py skips repair (no LLM), so a correct draft that repair rewrites into a provable sentence counts as lost
there. Here such a draft counts as recovered - but only if its rewrite is itself correct: rewrites get their own
labels in eval/baseline/repair_labels.jsonl (claude-audit); unlabelled ones are written to
eval/baseline/repair_unlabelled.txt and the report says how many are still open.

    python eval/gate_repair.py          (uses the writer model: several minutes per note)
"""
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval"))

B = ROOT / "eval" / "baseline"
import os
TAG = os.getenv("GATE_TAG", "")                    # e.g. GATE_TAG=quote -> gate_repair_quote.json (one file per experiment)
OUT = ROOT / "eval" / "reports" / f"gate_repair{'_' + TAG if TAG else ''}.json"
LABELS = B / f"repair_labels{'_' + TAG if TAG else ''}.jsonl"   # rewrites differ per experiment, so do their labels
jl = lambda p: [json.loads(l) for l in p.read_text(encoding="utf8").splitlines() if l.strip()] if p.exists() else []
norm = lambda s: " ".join(s.split())


def question_for(note: str) -> str:
    if note.endswith(" - key points.md"):
        state = json.loads((ROOT / "library" / "state.json").read_text(encoding="utf8"))
        stem = note.removesuffix(" - key points.md")
        title = next((v["title"] for v in state.values() if isinstance(v, dict) and v.get("path", "").endswith(stem + ".md")), stem)
        return f"What are the key points of “{title}”?"
    from baseline_drafts import TOPICS
    key = next(k for k in TOPICS if k.endswith("/" + note.removesuffix(".md")))
    subject, topic = key.split("/", 1)
    return f"Explain {topic} ({subject}): the key definitions, results and algorithms."


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    from gate import baseline_evidence, baseline_rows
    from baseline_drafts import pool_paths_by_note
    from michael.host.archangel import verify_and_repair
    from michael.host.heralds.vault import file_chunks
    from michael.models import Claim
    rows, pools, paths = baseline_rows(), baseline_evidence(), pool_paths_by_note()
    done = {r["id"]: r for r in jl(OUT.with_suffix(".rows.jsonl"))}         # resumable: one note at a time
    # each writer's drafts form their own note: run together, the pipeline's duplicate filter would drop the
    # near-identical sentences both writers wrote (right inside one note, wrong for this measurement)
    writer = {json.loads(l)["id"]: w for w in ("7b", "3b")
              for l in (B / f"drafts_{w}.jsonl").read_text(encoding="utf8").splitlines() if l.strip()}
    by_note = {}
    for r in rows:
        by_note.setdefault((r["note"], writer.get(r["id"], "?")), []).append(r)
    for (note, w), rs in by_note.items():
        if all(r["id"] in done for r in rs):
            continue
        evidence = [deepcopy(c) for c in pools.get(note, [])]
        labels = {c.label for c in evidence}
        claims = [Claim(index=i, sentence=r["sentence"], citations=[l for l in r["citations"] if l in labels])
                  for i, r in enumerate(rs)]
        pool = [ch for p in paths.get(note, []) for ch in file_chunks(Path(p))]
        kept, verdicts, removed = verify_and_repair(question_for(note), claims, evidence, pool=pool)
        final = {c.index: c for c in kept}
        with OUT.with_suffix(".rows.jsonl").open("a", encoding="utf8") as f:
            for i, r in enumerate(rs):
                c = final.get(i)
                status = c.status if c else "REMOVED"
                out = {"id": r["id"], "note": note, "label": r["label"], "sentence": r["sentence"], "status": status,
                       "final": c.sentence if c else "", "rewritten": bool(c) and norm(c.sentence) != norm(r["sentence"]),
                       "quote": verdicts[i].quote if c and i in verdicts else ""}
                f.write(json.dumps(out, ensure_ascii=False) + "\n")
                done[r["id"]] = out
        print(f"{note} [{w}]: {sum(1 for c in kept if c.status == 'SUPPORTED')}/{len(rs)} verified", flush=True)
    report(list(done.values()))


def report(rows):
    labels = {r["id"]: r["label"] for r in jl(LABELS)}
    open_ = [r for r in rows if r["status"] == "SUPPORTED" and r["rewritten"] and r["id"] not in labels]
    with (B / f"repair_unlabelled{'_' + TAG if TAG else ''}.txt").open("w", encoding="utf8") as f:
        for r in open_:
            f.write(f"### {r['id']}  {r['note']}\nORIGINAL: {r['sentence']}\nREWRITE:  {r['final']}\nQUOTE:    {r['quote'][:600]}\n\n")
    # a draft counts as kept-correct if it is shown verified and (unchanged and labelled correct, or rewritten and
    # its rewrite labelled correct)
    def shown_label(r):
        if r["status"] != "SUPPORTED":
            return None
        return labels.get(r["id"]) if r["rewritten"] else r["label"]
    correct_drafts = [r for r in rows if r["label"] == "correct"]
    shown = [(r, shown_label(r)) for r in rows if r["status"] == "SUPPORTED"]
    lab = [l for _, l in shown if l]
    pct = lambda a, b: round(100 * a / b, 1) if b else None
    rep = {"drafts": len(rows), "verified_shown": len(shown), "rewrites_unlabelled": len(open_),
           "precision_strict": pct(sum(l == "correct" for l in lab), len(lab)),
           "wrong_shown": sum(l == "wrong" for l in lab),
           "correct_drafts_lost": pct(sum(shown_label(r) != "correct" for r in correct_drafts), len(correct_drafts))}
    OUT.write_text(json.dumps(rep, indent=1), encoding="utf8")
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    if "--report" in sys.argv:
        report(jl(OUT.with_suffix(".rows.jsonl")))
    else:
        main()
