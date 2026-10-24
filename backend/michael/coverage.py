"""Coverage map: for every topic of the library, which source articles actually back verified facts.

Per topic: its overview's verified sentences, and per source article - does it have a key-points note, how many
verified facts (in any of Michael's notes) cite it. Gaps: articles nothing verified cites ("unused"), articles
without key points, and thin topics (fewer than 4 verified sentences in the overview). Built from the library
manifest/state and the claims table; no model.
"""
import json
import re
from pathlib import Path

from . import db

ROOT = Path(__file__).resolve().parents[2]
THIN = 4


def _stem(path: str) -> str:
    return Path(path).stem


def coverage() -> dict:
    manifest = json.loads((ROOT / "library" / "manifest.json").read_text(encoding="utf8"))
    state = json.loads((ROOT / "library" / "state.json").read_text(encoding="utf8"))
    cites = {}                                       # source note stem -> verified facts citing it
    with db.connect() as con:
        for row in con.execute("SELECT source FROM note_claims WHERE status = 'SUPPORTED'"):
            m = re.match(r"\[\[([^\]#|]+)", row[0] or "")
            if m:
                cites[m.group(1).strip()] = cites.get(m.group(1).strip(), 0) + 1
    subjects = []
    for subj in manifest["subjects"]:
        topics = []
        for t in subj["topics"]:
            info = state.get(f"topic:{subj['name']}/{t['name']}", {})
            sources = []
            for item in t["items"]:
                st = state.get(item, {})
                if st.get("status") != "saved":
                    continue
                stem = _stem(st["path"])
                sources.append({"title": st.get("title", stem), "note": stem, "kind": item.split(":")[0],
                                "verified_facts": cites.get(stem, 0), "key_points": bool(st.get("keypoints"))})
            unused = [s["title"] for s in sources if s["verified_facts"] == 0]
            topics.append({"topic": t["name"], "overview_verified": info.get("supported", 0),
                           "thin": info.get("supported", 0) < THIN, "sources": sources,
                           "unused_sources": len(unused),
                           "covered_pct": round(100 * (len(sources) - len(unused)) / max(1, len(sources)))})
        subjects.append({"subject": subj["name"], "topics": topics})
    all_sources = [s for su in subjects for t in su["topics"] for s in t["sources"]]
    return {"subjects": subjects,
            "summary": {"sources": len(all_sources),
                        "cited_by_verified_facts": sum(s["verified_facts"] > 0 for s in all_sources),
                        "with_key_points": sum(s["key_points"] for s in all_sources),
                        "thin_topics": [f"{su['subject']} / {t['topic']}" for su in subjects for t in su["topics"] if t["thin"]]}}
