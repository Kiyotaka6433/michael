"""Raziel, the angel who knows where every secret belongs: files a web page under the right library topic.

classify(title, text)   -> top topics with confidences (embedding similarity to each topic's articles; no LLM)
already_saved(url)      -> where the page already is in the vault, if anywhere
link_note(...)          -> a small note with just the page's name and URL, inside its topic's Links folder

Used by the browser extension: a page you read is suggested a topic, and one click adds its link to that node.
"""
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import numpy as np

from .. import db
from ..config import settings

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "library" / "manifest.json"
STATE = ROOT / "library" / "state.json"
INBOX = "Inbox"
TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|ref_|source$)")

_centroids = {"key": None, "topics": [], "matrix": None}


# ------------------------------------------------------------------ urls
def normalize_url(url: str) -> str:
    """Same page, same key: no fragment, no tracking parameters, no trailing slash, lower-case host."""
    p = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if not TRACKING.match(k.lower())])
    path = p.path.rstrip("/") or "/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower().removeprefix("www."), path, query, ""))


def already_saved(url: str) -> dict | None:
    """The vault note (article or link) with this URL, if any."""
    from .. import vault_index
    vault_index.init()
    key = normalize_url(url)
    with db.connect() as con:
        for r in con.execute("SELECT rel, title, subject, kind, url FROM vault_notes WHERE url != ''"):
            if normalize_url(r["url"]) == key:
                return {"note": r["rel"], "title": r["title"], "subject": r["subject"], "kind": r["kind"]}
    return None


# ------------------------------------------------------------------ topics
def topic_articles() -> dict[tuple[str, str], list[str]]:
    """(subject, topic) -> resolved paths of its saved articles, from the library manifest and build state."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf8"))
    state = json.loads(STATE.read_text(encoding="utf8")) if STATE.exists() else {}
    out = {}
    for subj in manifest["subjects"]:
        for topic in subj["topics"]:
            paths = [str(Path(state[i]["path"]).resolve()) for i in topic["items"]
                     if state.get(i, {}).get("status") == "saved"]
            if paths:
                out[(subj["name"], topic["name"])] = paths
    return out


def topic_centroids(chunks_per_article: int = 4):
    """One vector per topic: the mean embedding of the opening chunks of its articles (cached until the index
    changes). Returns ([(subject, topic)], matrix)."""
    with db.connect() as con:
        n = con.execute("SELECT COUNT(*) FROM vault_chunks").fetchone()[0]
    key = (n, STATE.stat().st_mtime if STATE.exists() else 0)
    if _centroids["key"] == key:
        return _centroids["topics"], _centroids["matrix"]
    from .archangel import EMBEDDER
    topics, vecs, per_topic = [], [], []
    with db.connect() as con:          # read everything first: db.connect's lock is not re-entrant
        for (subject, topic), paths in topic_articles().items():
            rows = []
            for p in paths:
                rows += [dict(r) for r in con.execute(
                    "SELECT hash, text FROM vault_chunks WHERE path=? ORDER BY start LIMIT ?", (p, chunks_per_article))]
            if rows:
                per_topic.append(((subject, topic), rows))
    for (subject, topic), rows in per_topic:
        cached = db.get_embeddings([r["hash"] for r in rows], settings.embed_model)
        missing = [r for r in rows if r["hash"] not in cached]
        if missing:
            for r, v in zip(missing, EMBEDDER.encode([r["text"] for r in missing])):
                cached[r["hash"]] = v
        m = np.mean([cached[r["hash"]] for r in rows], axis=0)
        topics.append((subject, topic))
        vecs.append(m / (np.linalg.norm(m) or 1))
    _centroids.update(key=key, topics=topics, matrix=np.stack(vecs) if vecs else None)
    return topics, _centroids["matrix"]


def classify(title: str, text: str, k: int = 3, embed=None, centroids=None, temperature: float = 0.05) -> list[dict]:
    """Top-k topics for a page. Confidence = softmax over cosine similarity to every topic centroid."""
    topics, matrix = centroids or topic_centroids()
    if matrix is None or not len(topics):
        return []
    if embed is None:
        from .archangel import EMBEDDER
        embed = lambda s: EMBEDDER.encode([s])[0]
    v = np.asarray(embed(f"{title}. {' '.join(text.split())[:3000]}"), dtype=np.float32)
    v = v / (np.linalg.norm(v) or 1)
    sims = matrix @ v
    p = np.exp((sims - sims.max()) / temperature)
    p = p / p.sum()
    order = np.argsort(-p)[:k]
    # "match" maps cosine similarity to 0-1 for display: unrelated pages sit around 0.55, real matches 0.8-0.9
    return [{"subject": topics[i][0], "topic": topics[i][1], "confidence": round(float(p[i]), 3),
             "similarity": round(float(sims[i]), 3), "match": round(float(np.clip((sims[i] - 0.6) / 0.3, 0, 1)), 2)}
            for i in order]


# decisions use raw similarity (stable), not the softmax share (depends on how many neighbouring topics exist)
RELEVANT_SIMILARITY = 0.65      # below: the page has nothing to do with the library - no pop-up
TOPIC_SIMILARITY = 0.75         # below (but relevant): file it in the subject's Inbox


# ------------------------------------------------------------------ link notes
SITE_SUFFIX = re.compile(r"\s+[-|·–—]\s+(Wikipedia|GeeksforGeeks|Medium|Towards Data Science|Stack Overflow|"
                         r"Mathematics Stack Exchange|Codeforces|CP-Algorithms|Algorithms for Competitive Programming|"
                         r"Brilliant Math & Science Wiki|Khan Academy)\s*$", re.I)


def clean_link_title(title: str) -> str:
    """'Bloom filter - Wikipedia' -> 'Bloom filter' (the site is in the URL already)."""
    title = " ".join(title.split())
    while SITE_SUFFIX.search(title):
        title = SITE_SUFFIX.sub("", title)
    return title or "Link"


def _yaml(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def link_note(vault: str | Path, url: str, title: str, subject: str, topic: str, tag: str = "") -> Path:
    """Write (or update) <vault>/<subject>/Links/<title>.md: just the page's name and URL, filed under its topic.
    The same URL always maps to the same note."""
    from .gabriel import slugify
    folder = Path(vault) / subject / "Links"
    folder.mkdir(parents=True, exist_ok=True)
    key = normalize_url(url)
    for existing in folder.glob("*.md"):                     # same page already linked: update in place
        head = existing.read_text(encoding="utf8", errors="ignore")[:800]
        m = re.search(r'(?m)^url: "(.*)"$', head)
        if m and normalize_url(m.group(1)) == key:
            path = existing
            break
    else:
        stem, i = slugify(title, 80) or "Link", 2
        path = folder / f"{stem}.md"
        while path.exists():
            path, i = folder / f"{stem} {i}.md", i + 1
    tags = ", ".join(t for t in ("link", tag) if t)
    path.write_text("\n".join([
        "---", f"title: {_yaml(title)}", f"url: {_yaml(url)}", f"subject: {_yaml(subject)}", f"topic: {_yaml(topic)}",
        f"added: {datetime.now().isoformat(timespec='minutes')}", "michael: link", f"tags: [{tags}]", "---",
        f"# {title}", "",
        f"Saved from the browser into [[{subject}]] › **{topic}**.", "", f"[Open the page]({url})", ""]), encoding="utf8")
    return path


def subject_tag(subject: str) -> str:
    manifest = json.loads(MANIFEST.read_text(encoding="utf8"))
    return next((s["tag"] for s in manifest["subjects"] if s["name"] == subject), "")


def refresh_hubs(vault: str | Path):
    """Rewrite the hub notes (and maps) so a new link shows under its topic. Reuses the library builder."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_library", ROOT / "scripts" / "build_library.py")
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    manifest = json.loads(MANIFEST.read_text(encoding="utf8"))
    b.phase_hubs(str(vault), manifest, b.load_state())
