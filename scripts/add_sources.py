"""Add pages from trusted subject-specific sites to library/manifest.json (never removes anything).

    python scripts/add_sources.py "DSA and Competitive Programming" "Graphs" URL [URL ...]

Items are stored as "url:<URL>"; build_library.py labels them by site, e.g. "Shortest Paths (Princeton Algorithms)".
Then run: python scripts/build_library.py fetch
"""
import json
import sys
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "library" / "manifest.json"


def main():
    subject, topic, urls = sys.argv[1], sys.argv[2], sys.argv[3:]
    m = json.loads(MANIFEST.read_text(encoding="utf8"))
    s = next(s for s in m["subjects"] if s["name"] == subject)
    t = next((t for t in s["topics"] if t["name"] == topic), None)
    if t is None:
        t = {"name": topic, "items": []}
        s["topics"].append(t)
    existing = {i for x in m["subjects"] for y in x["topics"] for i in y["items"]}
    new = [f"url:{u}" for u in urls if f"url:{u}" not in existing]
    t["items"] += new
    MANIFEST.write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf8")
    print(f"{subject} / {topic}: +{len(new)}")


if __name__ == "__main__":
    main()
