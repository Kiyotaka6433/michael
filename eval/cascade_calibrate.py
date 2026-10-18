"""Calibrate the verifier cascade on REAL verifier calls.

Input: pairs recorded during a gate run (MICHAEL_RECORD_NLI=eval/reports/nli_pairs.jsonl python eval/gate.py),
each with the large model's (entailment, contradiction). The small model scores the same pairs; for each cut we
report how many pairs the large model would still have to judge (cost) and how many pairs the large model ACCEPTS
(>= 0.70) or rates PARTIAL (>= 0.40) that the small model would have screened out (recall loss).

    python eval/cascade_calibrate.py [--n 3000]
"""
import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

PAIRS = ROOT / "eval" / "reports" / "nli_pairs.jsonl"
CUTS = [0.001, 0.002, 0.005, 0.01, 0.02, 0.03, 0.05, 0.1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3000)
    a = ap.parse_args()
    seen, rows = set(), []
    for line in PAIRS.read_text(encoding="utf8").splitlines():
        r = json.loads(line)
        if (r["p"], r["h"]) not in seen:
            seen.add((r["p"], r["h"]))
            rows.append(r)
    random.Random(0).shuffle(rows)
    # keep every pair the large model accepts or rates partial (rare, and what matters), sample the rest
    pos = [r for r in rows if r["ent"] >= 0.40]
    neg = [r for r in rows if r["ent"] < 0.40][: max(0, a.n - len(pos))]
    sample = pos + neg
    from michael.host.raguel import NLI
    t = time.time()
    small = NLI("tasksource/deberta-small-long-nli").scores([(r["p"], r["h"]) for r in sample])
    ms = 1000 * (time.time() - t) / max(1, len(sample))
    neg_share = 1 - len(pos) / max(1, len(rows))         # the real mix: most pairs are clear rejections
    report = {"unique_pairs": len(rows), "sampled": len(sample), "large_accepts": sum(r["ent"] >= 0.70 for r in sample),
              "large_partials": sum(0.40 <= r["ent"] < 0.70 for r in sample), "small_ms_per_pair": round(ms, 1),
              "cuts": {}}
    for cut in CUTS:
        kept_neg = sum(s[0] >= cut for r, s in zip(neg, small[len(pos):]))
        lost_acc = sum(r["ent"] >= 0.70 and s[0] < cut for r, s in zip(sample, small))
        lost_part = sum(0.40 <= r["ent"] < 0.70 and s[0] < cut for r, s in zip(sample, small))
        large_share = (1 - neg_share) + neg_share * kept_neg / max(1, len(neg))   # share of real pairs sent to large
        report["cuts"][cut] = {"large_share": round(large_share, 3), "lost_accepts": lost_acc, "lost_partials": lost_part}
    out = ROOT / "eval" / "reports" / "cascade_calibration.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
