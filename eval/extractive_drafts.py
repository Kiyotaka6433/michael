"""Recall experiment: redraft the 14 baseline notes in the EXTRACTIVE writer style (each sentence restates one
passage sentence) from the same cached evidence the gate verifies against, so the comparison with the original
drafts is fair. Saved after every note (resumable: a sleep or restart loses at most the note in progress).

    MICHAEL_WRITER_STYLE=extractive python eval/extractive_drafts.py   ->  eval/baseline/drafts_7b_extractive.jsonl
"""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval"))

OUT = ROOT / "eval" / "baseline" / "drafts_7b_extractive.jsonl"


def main():
    from michael.config import settings
    if settings.writer_style != "extractive":
        sys.exit("set MICHAEL_WRITER_STYLE=extractive")
    from michael.host import metatron
    from gate import baseline_evidence
    from gate_repair import question_for
    done = {json.loads(l)["note"] for l in OUT.read_text(encoding="utf8").splitlines() if l.strip()} if OUT.exists() else set()
    for note, evidence in baseline_evidence().items():
        if note in done:
            continue
        t = time.time()
        claims = metatron.write(question_for(note), evidence)
        with OUT.open("a", encoding="utf8") as f:
            for c in claims:
                f.write(json.dumps({"id": "x" + hashlib.sha1(f"{note}|{c.sentence}".encode("utf8")).hexdigest()[:10],
                                    "note": note, "sentence": c.sentence, "citations": c.citations},
                                   ensure_ascii=False) + "\n")
        print(f"{len(claims):2d} drafts  {time.time() - t:5.0f}s  {note}", flush=True)


if __name__ == "__main__":
    main()
