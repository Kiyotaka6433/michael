"""Baseline: what the writer produces WITHOUT the verifier.

For a sample of library notes, rebuild the same evidence the note was written from and run only the writer
(qwen2.5:7b). Identical prompts come back from the LLM cache, so these are the drafts the notes started from.
Every draft sentence is then labelled (eval/baseline/labels.jsonl) and compared with the verified notes.

    python eval/baseline_drafts.py        ->  eval/baseline/drafts.jsonl
"""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from michael import db                                          # noqa: E402
from michael.host import metatron, pravuil                       # noqa: E402
from michael.host.archangel import select_evidence               # noqa: E402
from michael.host.heralds.vault import file_chunks               # noqa: E402

OUT = ROOT / "eval" / "baseline" / "drafts.jsonl"
TOPICS = ["Number Theory/Modular arithmetic", "Number Theory/Primes", "Number Theory/Arithmetic functions",
          "DSA and Competitive Programming/Graphs", "DSA and Competitive Programming/Range queries",
          "DSA and Competitive Programming/Dynamic programming", "Machine Learning/Ensembles",
          "Machine Learning/Neural networks"]
KEYPOINTS = ["arxiv:1706.03762", "arxiv:1810.04805", "arxiv:1512.03385", "arxiv:1603.02754",
             "cp:graph/dijkstra", "cp:algebra/extended-euclid-algorithm"]


def sid(note, sentence):
    return "b" + hashlib.sha1(f"{note}|{sentence}".encode("utf8")).hexdigest()[:10]


def evidence_by_note() -> dict:
    """The exact evidence each baseline note was drafted from (deterministic: hybrid search + reranker, no LLM)."""
    state = json.loads((ROOT / "library" / "state.json").read_text(encoding="utf8"))
    manifest = json.loads((ROOT / "library" / "manifest.json").read_text(encoding="utf8"))
    out = {}
    for key in TOPICS:
        subject, topic = key.split("/", 1)
        t = next(t for s in manifest["subjects"] if s["name"] == subject for t in s["topics"] if t["name"] == topic)
        # the drafts were made from the topic's articles as of 17 Oct afternoon: Wikipedia + cp-algorithms only
        paths = [Path(state[i]["path"]) for i in t["items"] if state.get(i, {}).get("status") == "saved"
                 and not i.startswith("url:")]
        question = f"Explain {topic} ({subject}): the key definitions, results and algorithms."
        chunks = [c for p in paths for c in file_chunks(p)]
        out[f"{topic}.md"] = select_evidence(question, [question, topic, f"{topic} definition",
                                                        f"{topic} theorem algorithm example"], chunks, keep=8)
    for item in KEYPOINTS:
        st = state.get(item, {})
        if st.get("status") == "saved":
            src = Path(st["path"])
            question = f"What are the key points of “{st['title']}”?"
            out[f"{src.stem} - key points.md"] = select_evidence(question, [question] + pravuil.SUMMARY_QUERIES,
                                                                 file_chunks(src))
    return out


def main():
    import argparse
    from michael.config import settings
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="writer model, e.g. qwen2.5:3b (default: the configured one)")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    if a.model:
        settings.llm_model = a.model
    global OUT_PATH
    OUT_PATH = Path(a.out)
    db.init()
    state = json.loads((ROOT / "library" / "state.json").read_text(encoding="utf8"))
    manifest = json.loads((ROOT / "library" / "manifest.json").read_text(encoding="utf8"))
    rows = []
    for key in TOPICS:
        subject, topic = key.split("/", 1)
        t = next(t for s in manifest["subjects"] if s["name"] == subject for t in s["topics"] if t["name"] == topic)
        paths = [Path(state[i]["path"]) for i in t["items"] if state.get(i, {}).get("status") == "saved"]
        question = f"Explain {topic} ({subject}): the key definitions, results and algorithms."
        chunks = [c for p in paths for c in file_chunks(p)]
        ev = select_evidence(question, [question, topic, f"{topic} definition", f"{topic} theorem algorithm example"],
                             chunks, keep=8)
        rows += draft(f"{topic}.md", question, ev)
    for item in KEYPOINTS:
        st = state.get(item, {})
        if st.get("status") != "saved":
            continue
        src = Path(st["path"])
        question = f"What are the key points of “{st['title']}”?"
        ev = select_evidence(question, [question] + pravuil.SUMMARY_QUERIES, file_chunks(src))
        rows += draft(f"{src.stem} - key points.md", question, ev)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf8")
    print(f"{len(rows)} draft sentences -> {OUT_PATH}")


def draft(note, question, evidence):
    """The writer's drafts, plus what the verifier alone (no repair, no rescue) says about each of them -
    so the same sentences can be scored with and without verification."""
    from copy import deepcopy
    from michael.host.archangel import VERIFIER
    from michael.host.raguel import verify_claims
    t = time.time()
    claims = metatron.write(question, evidence)
    by_label = {c.label: c for c in evidence}
    verdicts = verify_claims([deepcopy(c) for c in claims], by_label, VERIFIER) if claims else []
    print(f"{len(claims):2d} drafts, {sum(v.label == 'SUPPORTED' for v in verdicts)} verified  "
          f"{time.time() - t:5.1f}s  {note}", flush=True)
    return [{"id": sid(note, c.sentence), "note": note, "sentence": c.sentence, "citations": c.citations,
             "verdict": v.label, "math": v.math, "entailment": round(v.entailment, 3),
             "cited_text": " ".join(by_label[l].text for l in c.citations if l in by_label)[:1500]}
            for c, v in zip(claims, verdicts)]


if __name__ == "__main__":
    main()
