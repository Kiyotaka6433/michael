"""Download the official SciFact release and convert the dev split into verifier test pairs.

Output: eval/datasets/scifact_dev.jsonl with {"premise", "hypothesis", "label"}:
  label "supported"    - rationale sentences that SUPPORT the claim
  label "unsupported"  - rationale sentences that CONTRADICT it, or an unrelated abstract sentence
Run: python eval/prepare_scifact.py
"""
import io
import json
import random
import tarfile
from pathlib import Path

import httpx

URL = "https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz"
OUT = Path(__file__).parent / "datasets" / "scifact_dev.jsonl"


def main():
    random.seed(0)
    print("downloading SciFact ...")
    data = httpx.get(URL, timeout=120, follow_redirects=True).content
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        def read(name):
            member = next(m for m in tar.getmembers() if m.name.endswith(name))
            return [json.loads(l) for l in tar.extractfile(member).read().decode().splitlines() if l.strip()]
        corpus = {d["doc_id"]: d for d in read("corpus.jsonl")}
        claims = read("claims_dev.jsonl")
    rows = []
    for c in claims:
        for doc_id, evs in c.get("evidence", {}).items():
            doc = corpus[int(doc_id)]
            for ev in evs:
                premise = " ".join(doc["abstract"][i] for i in ev["sentences"])
                rows.append({"premise": premise, "hypothesis": c["claim"],
                             "label": "supported" if ev["label"] == "SUPPORT" else "unsupported", "source": "scifact"})
        if not c.get("evidence"):   # claims with no evidence: pair with a random sentence of a cited doc
            for doc_id in c.get("cited_doc_ids", [])[:1]:
                doc = corpus.get(int(doc_id))
                if doc:
                    rows.append({"premise": random.choice(doc["abstract"]), "hypothesis": c["claim"],
                                 "label": "unsupported", "source": "scifact-noinfo"})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf8")
    sup = sum(r["label"] == "supported" for r in rows)
    print(f"wrote {len(rows)} pairs ({sup} supported, {len(rows) - sup} unsupported) -> {OUT}")


if __name__ == "__main__":
    main()
