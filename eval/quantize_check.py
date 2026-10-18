"""Does an int8 (dynamically quantized) verifier make the same decisions as the float32 one, and how much faster?

Uses the real verifier pairs recorded during a gate run (eval/reports/nli_pairs.jsonl, with float32 scores).
Reports ms/pair for both, and decision agreement at the SUPPORTED (0.70) and PARTIAL (0.40) thresholds:
  flips_up    pairs float32 rejects but int8 would accept   (precision risk)
  flips_down  pairs float32 accepts but int8 would reject   (recall risk)

    python eval/quantize_check.py [--n 1200]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1200)
    a = ap.parse_args()
    import torch
    from michael.host.raguel import NLI
    seen, rows = set(), []
    for line in PAIRS.read_text(encoding="utf8").splitlines():
        r = json.loads(line)
        if (r["p"], r["h"]) not in seen:
            seen.add((r["p"], r["h"]))
            rows.append(r)
    random.Random(1).shuffle(rows)
    pos = [r for r in rows if r["ent"] >= 0.40]
    sample = pos + [r for r in rows if r["ent"] < 0.40][: max(0, a.n - len(pos))]
    pairs = [(r["p"], r["h"]) for r in sample]

    fp32 = NLI()
    fp32._load()
    t = time.time()
    ref = fp32._scores(pairs[:200])                    # timing on a fixed subset (scores for all come from the cache)
    ms32 = 1000 * (time.time() - t) / 200

    q = NLI()
    q._load()
    q._model = torch.ao.quantization.quantize_dynamic(q._model, {torch.nn.Linear}, dtype=torch.qint8)
    t = time.time()
    q8 = q._scores(pairs)
    ms8 = 1000 * (time.time() - t) / len(pairs)
    ref_all = [(r["ent"], r["con"]) for r in sample]

    def flips(th):
        up = sum(e8 >= th > e32 for (e32, _), (e8, _) in zip(ref_all, q8))
        down = sum(e32 >= th > e8 for (e32, _), (e8, _) in zip(ref_all, q8))
        return up, down
    report = {"pairs": len(pairs), "fp32_ms_per_pair": round(ms32, 1), "int8_ms_per_pair": round(ms8, 1),
              "speedup": round(ms32 / ms8, 2), "fp32_accepts": sum(e >= 0.70 for e, _ in ref_all),
              "supported_flips_up": flips(0.70)[0], "supported_flips_down": flips(0.70)[1],
              "partial_flips_up": flips(0.40)[0], "partial_flips_down": flips(0.40)[1],
              "mean_abs_diff": round(sum(abs(e32 - e8) for (e32, _), (e8, _) in zip(ref_all, q8)) / len(q8), 4),
              "timing_check_fp32_vs_cache": round(max(abs(a[0] - b["ent"]) for a, b in zip(ref, sample[:200])), 4)}
    out = ROOT / "eval" / "reports" / "quantize_check.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
