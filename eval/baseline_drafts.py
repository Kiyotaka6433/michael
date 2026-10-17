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


def main():
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
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf8")
    print(f"{len(rows)} draft sentences -> {OUT}")


def draft(note, question, evidence):
    t = time.time()
    claims = metatron.write(question, evidence)
    by_label = {c.label: c for c in evidence}
    print(f"{len(claims):2d} drafts  {time.time() - t:5.1f}s  {note}", flush=True)
    return [{"id": sid(note, c.sentence), "note": note, "sentence": c.sentence, "citations": c.citations,
             "cited_text": " ".join(by_label[l].text for l in c.citations if l in by_label)[:1500]} for c in claims]


if __name__ == "__main__":
    main()
