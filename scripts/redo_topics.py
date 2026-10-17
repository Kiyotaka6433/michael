"""Mark topic notes for rewriting (the next `build_library.py topics` run writes them again).

    python scripts/redo_topics.py "DSA and Competitive Programming/Geometry" ...
"""
import json
import sys
from pathlib import Path

STATE = Path(__file__).resolve().parents[1] / "library" / "state.json"
state = json.loads(STATE.read_text(encoding="utf8"))
for name in sys.argv[1:]:
    state.get(f"topic:{name}", {}).pop("note", None)
    print("will rewrite", name)
STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf8")
