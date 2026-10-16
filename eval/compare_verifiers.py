"""Compare candidate verifier models on the same labelled pairs: accuracy AND speed on this machine.

    python eval/compare_verifiers.py [--limit N] [--models a b c]

For each model: ms per pair, and precision / recall / F1 at the threshold that maximises F1 (and at 0.5).
Results go to eval/reports/verifier_comparison_<time>.json.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
from run_eval import _counts, prf  # noqa: E402

CANDIDATES = [
    "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli",               # current
    "MoritzLaurer/deberta-v3-base-zeroshot-v2.0",                 # binary entailment, trained on many datasets
    "tasksource/deberta-small-long-nli",                          # small = fast
    "lytang/MiniCheck-DeBERTa-v3-Large",                          # trained specifically for grounding checks
    "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli",   # large NLI
]


def support_index(model) -> int:
    labels = {i: str(l).lower() for i, l in model.config.id2label.items()}
    for i, l in labels.items():
        if "entail" in l and "not" not in l:
            return i
    if len(labels) == 2:          # MiniCheck: LABEL_1 = supported
        return 1
    raise ValueError(f"no entailment label in {labels}")


def score(name, rows, threads=4):
    torch.set_num_threads(threads)
    tok = AutoTokenizer.from_pretrained(name)
    model = AutoModelForSequenceClassification.from_pretrained(name, dtype=torch.float32).eval()
    idx = support_index(model)
    pairs = [(r["premise"], r["hypothesis"]) for r in rows]
    order = sorted(range(len(pairs)), key=lambda i: len(pairs[i][0]) + len(pairs[i][1]))
    probs = [0.0] * len(pairs)
    t = time.time()
    for b in range(0, len(order), 16):
        ids = order[b:b + 16]
        enc = tok([pairs[i][0] for i in ids], [pairs[i][1] for i in ids], truncation="only_first", max_length=512,
                  padding=True, return_tensors="pt")
        with torch.inference_mode():
            p = model(**enc).logits.softmax(-1)[:, idx]
        for i, v in zip(ids, p.tolist()):
            probs[i] = v
    secs = time.time() - t
    gold = [r["label"] == "supported" for r in rows]
    sweep = {round(th, 2): prf(*_counts(gold, [p >= th for p in probs])) for th in [x / 20 for x in range(2, 20)]}
    best = max(sweep, key=lambda th: sweep[th]["f1"])
    return {"model": name, "ms_per_pair": round(1000 * secs / len(rows), 1), "best_threshold": best,
            "at_best": sweep[best], "at_0.5": sweep[0.5], "at_0.7": sweep[0.7], "sweep": sweep}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "eval" / "datasets" / "scifact_dev.jsonl"))
    ap.add_argument("--limit", type=int, default=100000)
    ap.add_argument("--models", nargs="*", default=CANDIDATES)
    a = ap.parse_args()
    rows = [json.loads(l) for l in Path(a.data).read_text(encoding="utf8").splitlines() if l.strip()][:a.limit]
    results = []
    for name in a.models:
        try:
            r = score(name, rows)
        except Exception as e:
            print(f"{name}: FAILED {e}", flush=True)
            continue
        results.append(r)
        b = r["at_best"]
        print(f"{name}: {r['ms_per_pair']} ms/pair | best th {r['best_threshold']}: P {b['precision']} R {b['recall']} "
              f"F1 {b['f1']} acc {b['accuracy']} | at 0.7: P {r['at_0.7']['precision']} R {r['at_0.7']['recall']}",
              flush=True)
    out = ROOT / "eval" / "reports" / f"verifier_comparison_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"dataset": a.data, "n": len(rows), "results": results}, indent=2), encoding="utf8")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
