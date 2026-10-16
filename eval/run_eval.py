"""Evaluation harness - produces the numbers for the README and the resume.

  python eval/run_eval.py verifier  [--data eval/datasets/scifact_dev.jsonl] [--threshold 0.7]
      Verifier quality on labelled (premise, hypothesis) pairs: accuracy, precision, recall, F1,
      plus a threshold sweep (the precision/recall trade-off).

  python eval/run_eval.py citations
      System verdicts vs. your human labels from the dashboard: citation precision and recall,
      i.e. "of the sentences Michael marked verified, how many really are".

  python eval/run_eval.py rerank --questions eval/questions.txt
      Saves top-8 evidence with and without the reranker for side-by-side judging (ablation).
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
REPORTS = ROOT / "eval" / "reports"


def prf(tp, fp, fn, tn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4),
            "accuracy": round((tp + tn) / max(1, tp + fp + fn + tn), 4), "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def eval_verifier(path, threshold, limit):
    from michael.host.raguel import NLI
    rows = [json.loads(l) for l in Path(path).read_text(encoding="utf8").splitlines() if l.strip()][:limit]
    nli = NLI()
    t0 = time.time()
    ent = [e for e, _ in nli.scores([(r["premise"], r["hypothesis"]) for r in rows])]
    secs = time.time() - t0
    gold = [r["label"] == "supported" for r in rows]
    sweep = {}
    for th in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        pred = [e >= th for e in ent]
        sweep[th] = prf(*_counts(gold, pred))
    report = {"dataset": str(path), "n": len(rows), "threshold": threshold, "seconds": round(secs, 1),
              "ms_per_pair": round(1000 * secs / max(1, len(rows)), 1),
              "at_threshold": prf(*_counts(gold, [e >= threshold for e in ent])), "sweep": sweep}
    _save("verifier", report)


def _counts(gold, pred):
    tp = sum(g and p for g, p in zip(gold, pred))
    fp = sum((not g) and p for g, p in zip(gold, pred))
    fn = sum(g and (not p) for g, p in zip(gold, pred))
    tn = sum((not g) and (not p) for g, p in zip(gold, pred))
    return tp, fp, fn, tn


def eval_citations():
    from michael import db
    db.init()
    labels = db.all_labels()
    if not labels:
        print("No human labels yet. Label claims in the dashboard (or via POST /runs/{id}/claims/{idx}/label) first.")
        return
    gold = [l["human_label"] == "supported" for l in labels]
    pred = [l["system_label"] == "SUPPORTED" for l in labels]
    _save("citations", {"n": len(labels), **prf(*_counts(gold, pred))})


def eval_rerank(questions_file):
    from michael import db
    from michael.host.jophiel import hybrid_search
    from michael.host.archangel import EMBEDDER, RERANKER, collect_candidates
    db.init()
    questions = [q.strip() for q in Path(questions_file).read_text(encoding="utf8").splitlines() if q.strip()]
    out = []
    for q in questions:
        chunks = collect_candidates(q, [q])
        cands = hybrid_search([q], chunks, EMBEDDER)
        before = cands[:8]
        after = RERANKER.rerank(q, list(cands))
        out.append({"question": q,
                    "without_rerank": [{"title": c.title, "text": c.text[:400]} for c in before],
                    "with_rerank": [{"title": c.title, "text": c.text[:400]} for c in after]})
        print(f"done: {q}")
    _save("rerank_ablation", {"questions": out,
                              "how_to_judge": "mark each passage relevant/irrelevant; compare precision@8"})


def _save(name, report):
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{name}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf8")
    print(json.dumps({k: v for k, v in report.items() if k != "questions"}, indent=2))
    print(f"saved {path}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verifier")
    v.add_argument("--data", default=str(ROOT / "eval" / "datasets" / "scifact_dev.jsonl"))
    v.add_argument("--threshold", type=float, default=0.7)
    v.add_argument("--limit", type=int, default=100000)
    sub.add_parser("citations")
    r = sub.add_parser("rerank")
    r.add_argument("--questions", default=str(ROOT / "eval" / "questions.txt"))
    a = ap.parse_args()
    if a.cmd == "verifier":
        eval_verifier(a.data, a.threshold, a.limit)
    elif a.cmd == "citations":
        eval_citations()
    else:
        eval_rerank(a.questions)


if __name__ == "__main__":
    main()
