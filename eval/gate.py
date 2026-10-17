"""Precision gate: re-judge labelled sentences with the CURRENT verifier and score the result against the labels.

Two labelled sets, both with the text each sentence cited:
  gold      200 sentences from Michael's notes that were shown (quote saved in the note)   eval/gold/
  baseline  198 raw writer drafts (7B + 3B), re-verified against their note's full evidence pool   eval/baseline/

Each sentence is re-verified with raguel.verify_claims against its cited text (no repair, no LLM; NLI scores come
from the cache after the first run). Reported:
  precision_strict   correct / accepted         (accepted = SUPPORTED)
  precision_lenient  (correct + partly) / accepted
  wrong_accepted     wrong sentences the verifier lets through
  lost_correct       correct sentences it does not accept (recall loss), baseline set only

    python eval/gate.py            -> prints the table, writes eval/reports/gate.json
    pytest -m eval                 -> fails if precision drops below the floors in tests/test_eval_gate.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval"))

jl = lambda p: [json.loads(l) for l in p.read_text(encoding="utf8").splitlines() if l.strip()] if p.exists() else []


def gold_rows():
    cands = {c["id"]: c for c in jl(ROOT / "eval/gold/candidates.jsonl")}
    out = []
    for g in jl(ROOT / "eval/gold/gold.jsonl"):
        c = cands.get(g["id"])
        if c and c.get("quote"):
            src = (c.get("source") or "").strip("[]").split("#")[0]
            out.append({"id": g["id"], "sentence": c["sentence"].strip("="), "evidence": c["quote"], "title": src,
                        "label": g["label"]})
    return out


def baseline_rows():
    from baseline_controlled import labels_for
    out = []
    for name in ("7b", "3b"):
        drafts = jl(ROOT / f"eval/baseline/drafts_{name}.jsonl")
        for d, lab in zip(drafts, labels_for(drafts)):
            if lab:
                out.append({"id": d["id"], "sentence": d["sentence"], "note": d["note"],
                            "citations": d.get("citations", []), "label": lab})
    return out


EVIDENCE_CACHE = ROOT / "eval" / "baseline" / "evidence.json"


def baseline_evidence() -> dict:
    """Each baseline note's full evidence pool (rebuilt once, then cached: reranking on CPU takes minutes)."""
    from michael.models import Chunk
    if not EVIDENCE_CACHE.exists():
        from dataclasses import asdict
        from baseline_drafts import evidence_by_note
        ev = evidence_by_note()
        EVIDENCE_CACHE.write_text(json.dumps({n: [asdict(c) for c in cs] for n, cs in ev.items()}, ensure_ascii=False),
                                  encoding="utf8")
    raw = json.loads(EVIDENCE_CACHE.read_text(encoding="utf8"))
    return {n: [Chunk(**c) for c in cs] for n, cs in raw.items()}


def judge_baseline(rows):
    """Drafts re-verified the way the pipeline does it: against the note's whole evidence pool, with re-citation
    (a sentence citing the neighbouring passage is checked against the right one) - but no LLM repair."""
    from michael.host.archangel import VERIFIER
    from michael.host.raguel import verify_claims
    from michael.models import Claim
    pools = baseline_evidence()
    by_note = {}
    for r in rows:
        by_note.setdefault(r["note"], []).append(r)
    for note, rs in by_note.items():
        evidence = {c.label: c for c in pools.get(note, [])}
        claims = [Claim(index=i, sentence=r["sentence"], citations=[l for l in r["citations"] if l in evidence])
                  for i, r in enumerate(rs)]
        for r, c, v in zip(rs, claims, verify_claims(claims, evidence, VERIFIER, recite=True)):
            r["verdict"], r["entailment"], r["shown"] = v.label, round(v.entailment, 3), c.sentence
    return rows


def judge(rows):
    """Current verdict for each row (verify_claims against its own cited text, no rescue across rows)."""
    from michael.host.archangel import VERIFIER
    from michael.host.raguel import verify_claims
    from michael.models import Chunk, Claim
    claims, evidence = [], {}
    for i, r in enumerate(rows):
        label = f"p{i}"
        evidence[label] = Chunk(source_id=r["id"], kind="vault", title=r["title"], url=r["title"], text=r["evidence"],
                                start=0, end=len(r["evidence"]), label=label)
        claims.append(Claim(index=i, sentence=r["sentence"], citations=[label]))
    verdicts = verify_claims(claims, evidence, VERIFIER, recite=False)
    for r, c, v in zip(rows, claims, verdicts):
        r["verdict"], r["entailment"], r["shown"] = v.label, round(v.entailment, 3), c.sentence
    return rows


def score(rows):
    acc = [r for r in rows if r["verdict"] == "SUPPORTED"]
    pct = lambda a, b: round(100 * a / b, 1) if b else None
    correct = [r for r in rows if r["label"] == "correct"]
    return {"n": len(rows), "accepted": len(acc),
            "precision_strict": pct(sum(r["label"] == "correct" for r in acc), len(acc)),
            "precision_lenient": pct(sum(r["label"] in ("correct", "partly") for r in acc), len(acc)),
            "wrong_accepted": sum(r["label"] == "wrong" for r in acc),
            "lost_correct": f"{sum(r['verdict'] != 'SUPPORTED' for r in correct)}/{len(correct)}",
            "lost_correct_pct": pct(sum(r["verdict"] != "SUPPORTED" for r in correct), len(correct))}


def run():
    gold, base = judge(gold_rows()), judge_baseline(baseline_rows())
    report = {"gold": score(gold), "baseline": score(base)}
    out = ROOT / "eval" / "reports" / "gate.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({**report, "rows": {"gold": gold, "baseline": base}}, indent=1, ensure_ascii=False),
                   encoding="utf8")
    return report


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(run(), indent=1))
