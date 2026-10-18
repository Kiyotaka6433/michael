"""Compare a gate report with a reference report: headline metrics, and every sentence whose verdict changed
(with its label), so a recall idea can't hide a new wrong acceptance in an aggregate.

    python eval/gate_compare.py eval/reports/gate_rescue3.json eval/reports/gate.json
"""
import json
import sys


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ref, new = (json.load(open(p, encoding="utf8")) for p in sys.argv[1:3])
    for k in ("gold", "baseline"):
        keep = ("accepted", "precision_strict", "precision_lenient", "wrong_accepted", "lost_correct", "lost_correct_pct")
        print(k, "before", {x: ref[k][x] for x in keep})
        print(k, "after ", {x: new[k][x] for x in keep})
        old = {r["id"]: r["verdict"] for r in ref["rows"][k]}
        for r in new["rows"][k]:
            if old.get(r["id"]) != r["verdict"]:
                print(f"   {old.get(r['id'])} -> {r['verdict']}  [{r['label']}]  {r['sentence'][:110]}")


if __name__ == "__main__":
    main()
