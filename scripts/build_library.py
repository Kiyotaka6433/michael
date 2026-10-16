"""Build the subject library in an Obsidian vault from library/manifest.json.

    python scripts/build_library.py fetch      save every article verbatim (exact LaTeX), fast
    python scripts/build_library.py hubs       subject hub notes + "Related" links between articles
    python scripts/build_library.py topics     one verified overview note per topic, from all its articles
    python scripts/build_library.py keypoints  verified key-points note per article (slow: LLM + verifier)
    python scripts/build_library.py all        fetch, hubs, topics, keypoints, hubs
Every topic / key-points note also gets a flashcard deck (Spaced Repetition plugin format).

Options: --vault PATH (default: Desktop/Michael Vault), --subject NAME, --limit N.
Resumable: progress is kept in library/state.json, finished items are skipped.

Vault layout:
    Home.md                                  links to every subject
    <Subject>/<Subject>.md                   hub: topics -> articles and key points
    <Subject>/Sources/<Article>.md           verbatim article (never edited by an LLM) + Related links
    <Subject>/Topics/<Topic>.md              verified overview of a topic, citing quotes from its articles
    <Subject>/Key points/<Article> - key points.md   verified key points, each citing a quote
    <Subject>/Flashcards/<Note> - cards.md   questions whose answers are verified sentences
"""
import argparse
import json
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from michael.host import pravuil, zachriel  # noqa: E402

MANIFEST = ROOT / "library" / "manifest.json"
STATE = ROOT / "library" / "state.json"
DEFAULT_VAULT = ROOT.parent / "Michael Vault"
SUFFIX = {"cp": " (cp-algorithms)", "skl": " (scikit-learn)", "d2l": " (d2l.ai)"}
KEYPOINT_ORDER = {"arxiv": 0, "cp": 1, "skl": 2, "d2l": 3, "wiki": 4}    # papers first: the longest reads


def resolve(item: str) -> dict:
    kind, _, ref = item.partition(":")
    if kind == "wiki":
        return {"kind": kind, "url": "https://en.wikipedia.org/wiki/" + quote(ref.replace(" ", "_")), "title": ref}
    if kind == "cp":
        return {"kind": kind, "url": f"https://cp-algorithms.com/{ref}.html", "title": None}
    if kind == "skl":
        return {"kind": kind, "url": f"https://scikit-learn.org/stable/modules/{ref}.html", "title": None}
    if kind == "d2l":
        return {"kind": kind, "url": f"https://d2l.ai/{ref}.html", "title": None}
    if kind == "arxiv":
        return {"kind": kind, "url": ref, "title": None}
    raise ValueError(f"unknown item {item}")


def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf8")) if STATE.exists() else {}


def save_state(state: dict):
    STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf8")


def items(manifest, subject_filter=None):
    for subj in manifest["subjects"]:
        if subject_filter and subj["name"] != subject_filter:
            continue
        for topic in subj["topics"]:
            for item in topic["items"]:
                yield subj, topic, item


def phase_fetch(vault, manifest, state, subject=None, limit=None):
    todo = [(s, t, i) for s, t, i in items(manifest, subject) if state.get(i, {}).get("status") != "saved"]
    print(f"fetch: {len(todo)} articles to save", flush=True)
    for n, (subj, topic, item) in enumerate(todo[:limit] if limit else todo, 1):
        r = resolve(item)
        t = time.time()
        try:
            a, path, math = pravuil.save_article(r["url"], str(vault), subj["name"], r["title"], tags=[subj["tag"]],
                                                 title_suffix=SUFFIX.get(r["kind"], ""))
            state[item] = {"status": "saved", "subject": subj["name"], "topic": topic["name"], "title": a.title,
                           "path": str(path), "route": a.route, "formulas": math["formulas"],
                           "rendered": math["rendered"], "chars": path.stat().st_size, "url": a.url}
            print(f"[{n}/{len(todo)}] ok  {time.time() - t:4.1f}s  {a.route:11s} {math['formulas']:4d} formulas  {a.title}",
                  flush=True)
        except Exception as e:
            state[item] = {"status": "failed", "subject": subj["name"], "topic": topic["name"], "error": str(e)[:300]}
            print(f"[{n}/{len(todo)}] FAIL {item}: {str(e)[:150]}", flush=True)
        save_state(state)


def flashcards(vault, subj, note_path: Path, facts) -> dict:
    cards = zachriel.make_cards(facts)
    if not cards:
        return {"cards": 0}
    deck = Path(vault) / subj["name"] / "Flashcards" / f"{note_path.stem} - cards.md"
    deck.parent.mkdir(parents=True, exist_ok=True)
    deck.write_text(zachriel.render_deck(note_path.stem, subj["tag"], cards, note_path.stem), encoding="utf8")
    return {"cards": len(cards), "deck": str(deck)}


def phase_topics(vault, manifest, state, subject=None, limit=None):
    todo = []
    for subj in manifest["subjects"]:
        if subject and subj["name"] != subject:
            continue
        for topic in subj["topics"]:
            key = f"topic:{subj['name']}/{topic['name']}"
            paths = [Path(state[i]["path"]) for i in topic["items"] if state.get(i, {}).get("status") == "saved"]
            if paths and not state.get(key, {}).get("note"):
                todo.append((subj, topic, key, paths))
    print(f"topics: {len(todo)} topic notes to write", flush=True)
    for n, (subj, topic, key, paths) in enumerate(todo[:limit] if limit else todo, 1):
        t = time.time()
        try:
            note = Path(vault) / subj["name"] / "Topics" / f"{pravuil.gabriel.slugify(topic['name'], 80)}.md"
            r = pravuil.topic_note(subj["name"], topic["name"], paths, note)
            s = r["stats"]
            fc = flashcards(vault, subj, note, r["facts"])
            state[key] = {"note": str(note), "supported": s["supported"], "total": s["total"], "removed": s["removed"],
                          "seconds": round(time.time() - t, 1), **fc}
            print(f"[{n}/{len(todo)}] {s['supported']}/{s['total']} verified, {fc['cards']} cards, "
                  f"{time.time() - t:5.0f}s  {subj['name']} / {topic['name']}", flush=True)
        except Exception as e:
            state[key] = {"error": str(e)[:300]}
            print(f"[{n}/{len(todo)}] FAIL {topic['name']}: {e}", flush=True)
            traceback.print_exc()
        save_state(state)


def phase_keypoints(vault, manifest, state, subject=None, limit=None, all_kinds=False):
    # papers and tutorial pages get their own key points; Wikipedia articles are covered by the topic notes
    # (use --all-kinds to include them too)
    todo = [(s, t, i) for s, t, i in items(manifest, subject)
            if state.get(i, {}).get("status") == "saved" and not state[i].get("keypoints")
            and (all_kinds or not i.startswith("wiki:"))]
    todo.sort(key=lambda x: KEYPOINT_ORDER[x[2].split(":")[0]])
    print(f"keypoints: {len(todo)} articles to summarise", flush=True)
    for n, (subj, topic, item) in enumerate(todo[:limit] if limit else todo, 1):
        st = state[item]
        t = time.time()
        try:
            kp = pravuil.key_points(Path(st["path"]), st["title"], pravuil.folders(str(vault), subj["name"])[1])
            s = kp["stats"]
            fc = flashcards(vault, subj, kp["note"], kp["facts"])
            st.update({"keypoints": str(kp["note"]), "kp_supported": s["supported"], "kp_total": s["total"],
                       "kp_removed": s["removed"], "kp_seconds": round(time.time() - t, 1), "kp_cards": fc["cards"]})
            print(f"[{n}/{len(todo)}] {s['supported']}/{s['total']} verified, {s['removed']} removed, {fc['cards']} cards, "
                  f"{time.time() - t:5.0f}s  {st['title']}", flush=True)
        except Exception as e:
            st["kp_error"] = str(e)[:300]
            print(f"[{n}/{len(todo)}] FAIL {st['title']}: {e}", flush=True)
            traceback.print_exc()
        save_state(state)


RELATED_START, RELATED_END = "<!-- michael:related -->", "<!-- /michael:related -->"


def phase_related(state, k=5):
    """Embed each article (title + opening text) and link its k nearest articles: the graph view then shows
    real clusters, and Obsidian's backlinks connect topics across subjects."""
    import numpy as np
    from michael.host.archangel import EMBEDDER
    saved = [(i, st) for i, st in state.items() if st.get("status") == "saved" and Path(st["path"]).exists()]
    texts = []
    for _, st in saved:
        body = Path(st["path"]).read_text(encoding="utf8", errors="ignore")
        body = re.sub(r"\A---\n.*?\n---\n", "", body, flags=re.S)
        body = re.sub(r"(?s)" + re.escape(RELATED_START) + r".*?" + re.escape(RELATED_END), "", body)
        body = re.sub(r"(?m)^>.*$", "", body)                      # callouts
        texts.append(st["title"] + ". " + " ".join(body.split())[:1500])
    vecs = np.stack([EMBEDDER.model.encode(t, normalize_embeddings=True) for t in texts])
    sims = vecs @ vecs.T
    for a, (item, st) in enumerate(saved):
        order = [b for b in np.argsort(-sims[a]) if b != a][:k]
        links = []
        for b in order:
            other = saved[b][1]
            where = "" if other["subject"] == st["subject"] else f" ({other['subject']})"
            links.append(f"- [[{Path(other['path']).stem}]]{where}")
        block = f"{RELATED_START}\n## Related\n" + "\n".join(links) + f"\n{RELATED_END}\n"
        p = Path(st["path"])
        text = p.read_text(encoding="utf8")
        text = re.sub(r"\n?" + re.escape(RELATED_START) + r".*?" + re.escape(RELATED_END) + r"\n?", "\n", text, flags=re.S)
        p.write_text(text.rstrip() + "\n\n" + block, encoding="utf8")
    print(f"related: linked {len(saved)} articles", flush=True)


def phase_hubs(vault, manifest, state):
    vault = Path(vault)
    home = ["---", "michael: hub", "tags: [hub]", "---", "# Home", "",
            "Michael's library. Every article in `Sources/` is saved verbatim from a trusted site (math kept as "
            "exact LaTeX); every note in `Key points/` was written by Michael and each sentence is checked against a "
            "quote from the article.", ""]
    for subj in manifest["subjects"]:
        name = subj["name"]
        lines = ["---", "michael: hub", f"tags: [hub, {subj['tag']}]", f"updated: {datetime.now():%Y-%m-%d %H:%M}",
                 "---", f"# {name}", "", subj["intro"], ""]
        n_saved = n_kp = n_cards = 0
        for topic in subj["topics"]:
            lines += [f"## {topic['name']}", ""]
            ts = state.get(f"topic:{name}/{topic['name']}", {})
            if ts.get("note") and Path(ts["note"]).exists():
                n_cards += ts.get("cards", 0)
                lines += [f"**Overview:** [[{Path(ts['note']).stem}]] ({ts['supported']}/{ts['total']} verified)"
                          + (f" · [[{Path(ts['deck']).stem}|{ts['cards']} flashcards]]" if ts.get("deck") else ""), ""]
            for item in topic["items"]:
                st = state.get(item, {})
                if st.get("status") != "saved":
                    continue
                n_saved += 1
                stem = Path(st["path"]).stem
                row = f"- [[{stem}]]"
                if st.get("keypoints") and Path(st["keypoints"]).exists():
                    n_kp += 1
                    row += f" · [[{Path(st['keypoints']).stem}|key points]] ({st['kp_supported']}/{st['kp_total']} verified)"
                    n_cards += st.get("kp_cards", 0)
                if st.get("formulas"):
                    row += f" · {st['rendered']}/{st['formulas']} formulas"
                lines.append(row)
            lines.append("")
        lines.insert(8, f"> [!info] {n_saved} articles · {n_kp} with verified key points · {n_cards} flashcards"
                        f" (tag #flashcards/{subj['tag']})\n")
        hub = vault / name / f"{name}.md"
        hub.parent.mkdir(parents=True, exist_ok=True)
        hub.write_text("\n".join(lines), encoding="utf8")
        home.append(f"- [[{name}]] - {n_saved} articles, {n_kp} key-point notes, {n_cards} flashcards")
    (vault / "Home.md").write_text("\n".join(home) + "\n", encoding="utf8")
    print("hubs: written", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["fetch", "hubs", "topics", "keypoints", "all"])
    ap.add_argument("--vault", default=str(DEFAULT_VAULT))
    ap.add_argument("--subject", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--all-kinds", action="store_true", help="key points for Wikipedia articles too")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf8"))
    state = load_state()
    if a.phase in ("fetch", "all"):
        phase_fetch(a.vault, manifest, state, a.subject, a.limit)
    if a.phase in ("hubs", "all"):
        phase_related(state)
        phase_hubs(a.vault, manifest, state)
    if a.phase in ("topics", "all"):
        phase_topics(a.vault, manifest, state, a.subject, a.limit)
        phase_hubs(a.vault, manifest, state)
    if a.phase in ("keypoints", "all"):
        phase_keypoints(a.vault, manifest, state, a.subject, a.limit, a.all_kinds)
        phase_hubs(a.vault, manifest, state)


if __name__ == "__main__":
    main()
