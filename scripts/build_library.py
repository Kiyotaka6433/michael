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
# "url:" items: trusted subject-specific sites, labelled by domain so the source is visible in every title
SITES = {"usaco.guide": "USACO Guide", "algs4.cs.princeton.edu": "Princeton Algorithms",
         "opendatastructures.org": "Open Data Structures", "artofproblemsolving.com": "AoPS Wiki",
         "proofwiki.org": "ProofWiki", "brilliant.org": "Brilliant", "oeis.org": "OEIS",
         "cs231n.github.io": "Stanford CS231n", "distill.pub": "Distill", "lilianweng.github.io": "Lil'Log",
         "colah.github.io": "colah's blog", "developers.google.com": "Google ML Crash Course",
         "cs229.stanford.edu": "Stanford CS229", "jeffe.cs.illinois.edu": "Erickson, Algorithms",
         "people.csail.mit.edu": "MIT", "ocw.mit.edu": "MIT OCW", "mathworld.wolfram.com": "MathWorld",
         "cp-algorithms.com": "cp-algorithms", "codeforces.com": "Codeforces", "topcoder.com": "Topcoder",
         "web.stanford.edu": "Stanford", "www.cs.cmu.edu": "CMU", "cses.fi": "CSES", "primes.utm.edu": "Prime Pages",
         "t5k.org": "Prime Pages", "numbertheory.org": "numbertheory.org", "d2l.ai": "d2l.ai"}


def site_of(url: str) -> str:
    from urllib.parse import urlsplit
    host = urlsplit(url).netloc.lower()
    return next((v for k, v in SITES.items() if host == k or host.endswith("." + k)), host.removeprefix("www."))
KEYPOINT_ORDER = {"arxiv": 0, "cp": 1, "url": 2, "skl": 3, "d2l": 4, "wiki": 5}   # papers first: the longest reads


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
    if kind == "url":                       # "url:<URL>" or "url:<URL> | <Title>" for sites whose pages share one title
        url, _, title = ref.partition(" | ")
        return {"kind": kind, "url": url, "title": f"{title} ({site_of(url)})" if title else None,
                "suffix": f" ({site_of(url)})"}
    raise ValueError(f"unknown item {item}")


_snapshot: dict = {}


def load_state() -> dict:
    state = json.loads(STATE.read_text(encoding="utf8")) if STATE.exists() else {}
    _snapshot.clear()
    _snapshot.update(json.loads(json.dumps(state)))
    return state


def save_state(state: dict):
    """Merge, don't overwrite: only the entries this process changed are written over what is on disk, so a
    fetch can run while a long key-points batch is saving its own progress."""
    disk = json.loads(STATE.read_text(encoding="utf8")) if STATE.exists() else {}
    for k, v in state.items():
        if _snapshot.get(k) != v:
            disk[k] = v
            _snapshot[k] = json.loads(json.dumps(v))
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(disk, indent=1, ensure_ascii=False), encoding="utf8")
    tmp.replace(STATE)


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
                                                 title_suffix=r.get("suffix") or SUFFIX.get(r["kind"], ""))
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
    text = zachriel.render_deck(note_path.stem, subj["tag"], cards, note_path.stem)
    if deck.exists():                      # keep any review history from the Spaced Repetition plugin
        text = zachriel.keep_schedules(deck.read_text(encoding="utf8"), text)
    deck.write_text(text, encoding="utf8")
    return {"cards": len(cards), "deck": str(deck)}


def phase_cards(vault, manifest, state):
    """Rebuild every deck from the verified sentences of the notes that already exist (one card per fact)."""
    subjects = {s["name"]: s for s in manifest["subjects"]}
    jobs = [(k, st, Path(st["note"])) for k, st in state.items() if k.startswith("topic:") and st.get("note")]
    jobs += [(k, st, Path(st["keypoints"])) for k, st in state.items() if isinstance(st, dict) and st.get("keypoints")]
    print(f"cards: rebuilding {len(jobs)} decks", flush=True)
    for n, (key, st, note) in enumerate(jobs, 1):
        if not note.exists():
            continue
        subj = subjects[note.relative_to(Path(vault)).parts[0]]
        facts = zachriel.facts_from_note(note.read_text(encoding="utf8"))
        fc = flashcards(vault, subj, note, facts)
        st["cards" if key.startswith("topic:") else "kp_cards"] = fc["cards"]
        if fc.get("deck"):
            st["deck"] = fc["deck"] if key.startswith("topic:") else st.get("deck")
        print(f"[{n}/{len(jobs)}] {fc['cards']}/{len(facts)} cards  {note.stem}", flush=True)
        save_state(state)


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


def _cited_sources(md: str) -> int:
    part = md.split("## Sources", 1)[1] if "## Sources" in md else ""
    return len({m.split("#")[0] for m in re.findall(r"\[\[([^\]|]+)", part.split("\n## ", 1)[0])})


def still_verified(md: str) -> int:
    """How many of a note's verified sentences still pass under the CURRENT verifier, judged against the quote the
    note itself shows. A rule fix (e.g. the title-context overlap floor) can invalidate an old verification; the
    old note must not win a comparison on a count that no longer holds."""
    from michael.host.archangel import VERIFIER
    from michael.host.raguel import verify_claims
    from michael.learning import parse_note_claims
    from michael.models import Chunk, Claim
    rows = [r for r in parse_note_claims(md) if r["status"] == "SUPPORTED" and r["quote"]]
    if not rows:
        return 0
    evidence, claims = {}, []
    for i, r in enumerate(rows):
        title = r["source"].strip("[]").split("#")[0].split("](")[0]
        evidence[f"p{i}"] = Chunk(source_id=title, kind="vault", title=title, url=title, text=r["quote"], start=0,
                                  end=len(r["quote"]), label=f"p{i}")
        claims.append(Claim(index=i, sentence=r["sentence"], citations=[f"p{i}"]))
    return sum(v.label == "SUPPORTED" for v in verify_claims(claims, evidence, VERIFIER, recite=False))


def better(new: dict, old: dict) -> bool:
    """A rewrite replaces the current note only if it proves at least as many sentences and either proves more
    or draws on more distinct sources; ties keep the current note (and its flashcard history)."""
    if new["supported"] < old["supported"]:
        return False
    return new["supported"] > old["supported"] or new["sources"] > old["sources"]


def phase_retopics(vault, manifest, state, subject=None, limit=None, every=False):
    """Rewrite topic notes whose topic gained sources since the note was written. The rewrite goes to a hidden
    candidate file; it replaces the current note only when better(), and the old note moves to <Subject>/Archive/
    (nothing is deleted)."""
    todo = []
    for subj in manifest["subjects"]:
        if subject and subj["name"] != subject:
            continue
        for topic in subj["topics"]:
            key = f"topic:{subj['name']}/{topic['name']}"
            cur = state.get(key, {})
            paths = [Path(state[i]["path"]) for i in topic["items"] if state.get(i, {}).get("status") == "saved"]
            note = Path(cur.get("note", ""))
            if not cur.get("note") or not note.exists():
                continue
            text = note.read_text(encoding="utf8")
            # the intro links every source it was built from: a missing one means the topic gained sources; thin notes
            # (fewer than 4 verified sentences) are retried too - better() keeps the current note unless the rewrite wins
            if every or any(f"[[{p.stem}]]" not in text for p in paths) or cur.get("supported", 0) < 4:
                todo.append((subj, topic, key, paths, note))
    print(f"retopics: {len(todo)} topic notes to rewrite and compare", flush=True)
    for n, (subj, topic, key, paths, note) in enumerate(todo[:limit] if limit else todo, 1):
        t = time.time()
        try:
            cand = note.parent / ".candidates" / note.name
            r = pravuil.topic_note(subj["name"], topic["name"], paths, cand)
            old_md = note.read_text(encoding="utf8")
            old = {"supported": min(state[key].get("supported", 0), still_verified(old_md)),
                   "sources": _cited_sources(old_md)}
            new = {"supported": r["stats"]["supported"], "sources": _cited_sources(r["markdown"])}
            verdict = "replaced" if better(new, old) else "kept"
            if verdict == "replaced":
                archive = Path(vault) / subj["name"] / "Archive" / f"{note.stem} ({datetime.now():%Y-%m-%d %H%M}).md"
                archive.parent.mkdir(parents=True, exist_ok=True)
                note.replace(archive)
                cand.replace(note)
                fc = flashcards(vault, subj, note, r["facts"])
                state[key] = {**state[key], "supported": new["supported"], "total": r["stats"]["total"],
                              "removed": r["stats"]["removed"], "seconds": round(time.time() - t, 1),
                              "archived": str(archive), **fc}
            else:
                cand.unlink(missing_ok=True)
            state[key] = {**state[key], "compared": f"{datetime.now():%Y-%m-%d %H:%M} old {old} new {new} {verdict}"}
            print(f"[{n}/{len(todo)}] {verdict:8s} old {old['supported']} verified/{old['sources']} sources -> new "
                  f"{new['supported']}/{new['sources']}  {time.time() - t:5.0f}s  {subj['name']} / {topic['name']}",
                  flush=True)
        except Exception as e:
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
        body = body.split("<!-- michael:")[0]                       # our Related / Mentions link blocks
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


MENTIONS_START, MENTIONS_END = "<!-- michael:mentions -->", "<!-- /michael:mentions -->"
SITE_TAG = re.compile(r"\s*\((cp-algorithms|scikit-learn|d2l\.ai)\)$")
AMBIGUOUS = {"adam", "dropout", "divisor", "trie"}      # also common words / people's names


def phase_mentions(state, cap=30):
    """Link every article to the other library articles it mentions by name ("... by Bézout's identity ..." ->
    [[Bézouts identity]]). The article text is not touched; links go in a "Mentions" section at the end. This
    turns the graph into one dense web of real concept links."""
    saved = [st for st in state.values() if isinstance(st, dict) and st.get("status") == "saved" and Path(st["path"]).exists()]
    names, orig = {}, {}                         # lower-case name -> note stems / original spellings
    for st in saved:
        for name in {st["title"], SITE_TAG.sub("", st["title"])}:
            name = re.sub(r"\s*\(.*?\)\s*$", "", name).strip()          # "Heap (data structure)" -> "Heap"
            if len(name) >= 4 and not re.fullmatch(r"[\d.\s]+", name):
                names.setdefault(name.lower(), set()).add(Path(st["path"]).stem)
                orig.setdefault(name.lower(), set()).add(name)
    names = {n: v for n, v in names.items() if n not in AMBIGUOUS}
    # one-word names must match with their capitalisation ("Dropout" the technique, not every "dropout")
    patterns = [(re.compile(r"(?<![\w-])" + re.escape(next(iter(orig[n]))) + r"(?:s|es)?(?![\w-])",
                            0 if " " not in n else re.I), stems)
                for n, stems in sorted(names.items(), key=lambda x: -len(x[0]))]
    total = 0
    for st in saved:
        p = Path(st["path"])
        text = p.read_text(encoding="utf8")
        body = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S).split("<!-- michael:")[0]
        counts = {}
        for rx, stems in patterns:
            n = len(rx.findall(body))
            if n:
                for stem in stems:
                    if stem != p.stem:
                        counts[stem] = counts.get(stem, 0) + n
        top = sorted(counts, key=lambda s: -counts[s])[:cap]
        text = re.sub(r"\n?" + re.escape(MENTIONS_START) + r".*?" + re.escape(MENTIONS_END) + r"\n?", "\n", text, flags=re.S)
        if top:
            block = f"{MENTIONS_START}\n## Mentions\n" + " · ".join(f"[[{s}]]" for s in sorted(top)) + f"\n{MENTIONS_END}\n"
            text = text.rstrip() + "\n\n" + block
            total += len(top)
        p.write_text(text, encoding="utf8")
    print(f"mentions: {total} concept links across {len(saved)} articles", flush=True)


def saved_links(subject_dir: Path) -> dict[str, list[str]]:
    """Link notes added from the browser extension, grouped by topic (from their frontmatter)."""
    out = {}
    for p in sorted((subject_dir / "Links").glob("*.md")):
        m = re.search(r'(?m)^topic: "(.*)"$', p.read_text(encoding="utf8", errors="ignore")[:800])
        out.setdefault(m.group(1) if m else "Inbox", []).append(p.stem)
    return out


def phase_hubs(vault, manifest, state):
    vault = Path(vault)
    home = ["---", "michael: hub", "tags: [hub]", "---", "# Home", "",
            "Michael's library. Every article in `Sources/` is saved verbatim from a trusted site (math kept as "
            "exact LaTeX); every note in `Key points/` was written by Michael and each sentence is checked against a "
            "quote from the article.", "",
            "**Visual maps:** [[Maps/Library map.canvas|Library map]] · open the graph view (Ctrl+G): gold = hubs, "
            "purple = topic overviews, blue = Number Theory, green = DSA, orange = Machine Learning, grey = key points.",
            ""]
    for subj in manifest["subjects"]:
        name = subj["name"]
        lines = ["---", "michael: hub", f"tags: [hub, {subj['tag']}]", f"updated: {datetime.now():%Y-%m-%d %H:%M}",
                 "---", f"# {name}", "", subj["intro"], ""]
        n_saved = n_kp = n_cards = 0
        links = saved_links(vault / name)
        for topic in subj["topics"] + ([{"name": "Inbox", "items": []}] if links.get("Inbox") else []):
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
            if links.get(topic["name"]):
                lines += ["", "### Reading list", ""] + [f"- [[{stem}]]" for stem in links[topic["name"]]]
            lines.append("")
        n_links = sum(len(v) for v in links.values())
        lines.insert(8, f"> [!info] {n_saved} articles · {n_kp} with verified key points · {n_cards} flashcards"
                        f" (tag #flashcards/{subj['tag']}) · {n_links} saved links\n")
        hub = vault / name / f"{name}.md"
        hub.parent.mkdir(parents=True, exist_ok=True)
        hub.write_text("\n".join(lines), encoding="utf8")
        home.append(f"- [[{name}]] - {n_saved} articles, {n_kp} key-point notes, {n_cards} flashcards")
    (vault / "Home.md").write_text("\n".join(home) + "\n", encoding="utf8")
    print("hubs: written", flush=True)
    phase_graph(vault, manifest)
    phase_canvas(vault, manifest, state)


SUBJECT_COLORS = {"number-theory": (0x4C9AFF, "5"), "dsa-cp": (0x36B37E, "4"), "machine-learning": (0xFF8B00, "2")}
HUB_RGB, TOPIC_RGB, KEYPOINT_RGB = 0xFFD700, 0xE040FB, 0x8993A4


def phase_graph(vault, manifest):
    """Colour the graph view: hubs gold, topic overviews purple, key points grey, articles by subject; hide
    flashcard decks. Other graph settings the user changed are kept."""
    path = Path(vault) / ".obsidian" / "graph.json"
    g = json.loads(path.read_text(encoding="utf8")) if path.exists() else {}
    groups = [{"query": "tag:#hub", "color": {"a": 1, "rgb": HUB_RGB}},
              {"query": 'path:"/Topics/"', "color": {"a": 1, "rgb": TOPIC_RGB}},
              {"query": 'path:"Key points"', "color": {"a": 1, "rgb": KEYPOINT_RGB}}]
    # links saved from the browser: a lighter shade of their subject's colour
    lighten = lambda rgb: tuple((c + 255) // 2 for c in ((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255))
    groups += [{"query": f'path:"{s["name"]}/Links/"',
                "color": {"a": 1, "rgb": (lambda r, g, b: (r << 16) | (g << 8) | b)(
                    *lighten(SUBJECT_COLORS.get(s["tag"], (0x999999, ""))[0]))}}
               for s in manifest["subjects"]]
    groups += [{"query": f'path:"{s["name"]}/"', "color": {"a": 1, "rgb": SUBJECT_COLORS.get(s["tag"], (0x999999, ""))[0]}}
               for s in manifest["subjects"]]
    # look: one round, dense web of small nodes with thin links and readable labels
    g.update({"colorGroups": groups, "search": g.get("search") or "-path:Flashcards -path:Maps",
              "showTags": False, "showOrphans": True, "hideUnresolved": True, "showArrow": False,
              "textFadeMultiplier": -1.5, "nodeSizeMultiplier": 0.75, "lineSizeMultiplier": 0.45,
              "centerStrength": 0.55, "repelStrength": 9, "linkStrength": 0.8, "linkDistance": 110, "scale": 0.6})
    appearance = Path(vault) / ".obsidian" / "appearance.json"
    a = json.loads(appearance.read_text(encoding="utf8")) if appearance.exists() else {}
    a.setdefault("theme", "obsidian")                                # dark theme, as in the reference picture
    appearance.write_text(json.dumps(a, indent=2), encoding="utf8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(g, indent=2), encoding="utf8")
    print("graph: colour groups written (reopen the graph view to see them)", flush=True)


def phase_canvas(vault, manifest, state):
    """One Obsidian Canvas map per subject: the hub in the middle, one coloured group per topic holding its
    overview note and its articles, with arrows from the hub to each topic."""
    vault = Path(vault)
    rel = lambda p: Path(p).relative_to(vault).as_posix()
    maps = vault / "Maps"
    maps.mkdir(exist_ok=True)
    home_nodes = []
    for si, subj in enumerate(manifest["subjects"]):
        color = SUBJECT_COLORS.get(subj["tag"], (0, "1"))[1]
        hub = f"{subj['name']}/{subj['name']}.md"
        nodes = [{"id": "hub", "type": "file", "file": hub, "x": -200, "y": -900, "width": 400, "height": 300, "color": "3"}]
        edges = []
        cols, gw, gap = 3, 760, 80
        y_offsets = [0] * cols
        for ti, topic in enumerate(subj["topics"]):
            arts = [state[i] for i in topic["items"] if state.get(i, {}).get("status") == "saved"]
            ts = state.get(f"topic:{subj['name']}/{topic['name']}", {})
            rows = (len(arts) + 1) // 2
            gh = 120 + (200 if ts.get("note") else 0) + rows * 90
            col = min(range(cols), key=lambda c: y_offsets[c])          # shortest column first (masonry)
            gx, gy = (col - 1) * (gw + gap) - gw // 2, y_offsets[col]
            y_offsets[col] += gh + gap
            gid = f"t{ti}"
            nodes.append({"id": gid, "type": "group", "label": topic["name"], "x": gx, "y": gy, "width": gw,
                          "height": gh, "color": color})
            y = gy + 50
            target = gid
            if ts.get("note") and Path(ts["note"]).exists():
                nodes.append({"id": f"{gid}o", "type": "file", "file": rel(ts["note"]), "x": gx + 20, "y": y,
                              "width": gw - 40, "height": 180, "color": "6"})
                target, y = f"{gid}o", y + 200
            for ai, st in enumerate(arts):
                nodes.append({"id": f"{gid}a{ai}", "type": "file", "file": rel(st["path"]),
                              "x": gx + 20 + (ai % 2) * ((gw - 60) // 2 + 20), "y": y + (ai // 2) * 90,
                              "width": (gw - 60) // 2, "height": 70})
            edges.append({"id": f"e{ti}", "fromNode": "hub", "fromSide": "bottom", "toNode": target, "toSide": "top"})
        canvas = maps / f"{subj['name']} map.canvas"
        canvas.write_text(json.dumps({"nodes": nodes, "edges": edges}, indent=1), encoding="utf8")
        home_nodes.append({"id": f"s{si}", "type": "file", "file": f"Maps/{subj['name']} map.canvas",
                           "x": si * 520 - 520, "y": 0, "width": 480, "height": 360, "color": color})
    home = [{"id": "home", "type": "file", "file": "Home.md", "x": -240, "y": -420, "width": 480, "height": 300,
             "color": "3"}] + home_nodes
    edges = [{"id": f"h{n['id']}", "fromNode": "home", "fromSide": "bottom", "toNode": n["id"], "toSide": "top"}
             for n in home_nodes]
    (maps / "Library map.canvas").write_text(json.dumps({"nodes": home, "edges": edges}, indent=1), encoding="utf8")
    print(f"canvas: {len(manifest['subjects'])} subject maps + Library map in Maps/", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["fetch", "hubs", "topics", "retopics", "keypoints", "cards", "all"])
    ap.add_argument("--vault", default=str(DEFAULT_VAULT))
    ap.add_argument("--subject", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--all-kinds", action="store_true", help="key points for Wikipedia articles too")
    ap.add_argument("--all-topics", action="store_true", help="retopics: rewrite and compare every topic note")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf8"))
    state = load_state()
    if a.phase in ("fetch", "all"):
        phase_fetch(a.vault, manifest, state, a.subject, a.limit)
    if a.phase in ("hubs", "all"):
        phase_related(state)
        phase_mentions(state)
        phase_hubs(a.vault, manifest, state)
    if a.phase in ("topics", "all"):
        phase_topics(a.vault, manifest, state, a.subject, a.limit)
        phase_hubs(a.vault, manifest, state)
    if a.phase == "retopics":
        phase_retopics(a.vault, manifest, state, a.subject, a.limit, a.all_topics)
        phase_hubs(a.vault, manifest, state)
    if a.phase == "cards":
        phase_cards(a.vault, manifest, state)
        phase_hubs(a.vault, manifest, state)
    if a.phase in ("keypoints", "all"):
        phase_keypoints(a.vault, manifest, state, a.subject, a.limit, a.all_kinds)
        phase_hubs(a.vault, manifest, state)


if __name__ == "__main__":
    main()
