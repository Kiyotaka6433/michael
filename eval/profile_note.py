"""Where does the time go when Michael writes a note? Times each pipeline stage for one key-points note.

    python eval/profile_note.py "<path to a source note>" [--out <folder>]
Stages come from the pipeline's own progress events (gather, search, rerank, write, verify, repair); the note is
written to --out (default: a temp folder), never into the vault.
"""
import argparse
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--out", default=tempfile.mkdtemp(prefix="michael-profile-"))
    a = ap.parse_args()
    from michael.host import pravuil
    from michael.host.archangel import VERIFIER, warm_up
    warm_up()                                     # model loading is not part of a note's cost
    marks = [("start", time.time(), "")]
    emit = lambda stage, detail="", **_: marks.append((stage, time.time(), detail))
    src = Path(a.source)
    r = pravuil.key_points(src, src.stem, Path(a.out), emit)
    marks.append(("done", time.time(), ""))
    total = marks[-1][1] - marks[0][1]
    print(f"{src.stem}: {total:.0f}s, {r['stats']['supported']}/{r['stats']['total']} verified")
    for (s, t, d), (_, t2, _) in zip(marks, marks[1:]):
        print(f"  {s:8s} {t2 - t:6.1f}s  {100 * (t2 - t) / total:4.0f}%  {d[:70]}")


if __name__ == "__main__":
    main()
