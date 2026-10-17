"""Vault index: the database side of "local-first".

The vault's Markdown files are the source of truth. This module keeps a derived index of them in SQLite:
notes (title, subject, kind), chunks (per heading section), full-text search (FTS5), embeddings (shared cache)
and links. It is incremental (only files whose modification time or content changed are re-read) and can be
rebuilt from the vault at any time.

    index_vault(vault)          -> {"indexed": n, "unchanged": n, "removed": n}
    search(query, k, subject)   -> hybrid full-text + vector results, fused with reciprocal rank fusion
"""
import re
import time
from pathlib import Path

import numpy as np

from . import db
from .config import settings
from .models import Chunk, sha

SCHEMA = """
CREATE TABLE IF NOT EXISTS vault_notes (
    path TEXT PRIMARY KEY, vault TEXT, rel TEXT, title TEXT, subject TEXT, kind TEXT, generated INTEGER,
    url TEXT, mtime REAL, hash TEXT, chars INTEGER, indexed_at REAL
);
CREATE TABLE IF NOT EXISTS vault_chunks (
    id TEXT PRIMARY KEY, path TEXT, heading TEXT, start INTEGER, end_ INTEGER, text TEXT, hash TEXT
);
CREATE INDEX IF NOT EXISTS vault_chunks_path ON vault_chunks(path);
CREATE VIRTUAL TABLE IF NOT EXISTS vault_fts USING fts5(chunk_id UNINDEXED, title, heading, text,
    tokenize = 'porter unicode61');
CREATE TABLE IF NOT EXISTS vault_links (src TEXT, dst TEXT, kind TEXT);
CREATE INDEX IF NOT EXISTS vault_links_src ON vault_links(src);
CREATE INDEX IF NOT EXISTS vault_links_dst ON vault_links(dst);
"""

LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
FM_FIELD = lambda name: re.compile(rf'(?m)^{name}:\s*"?(.*?)"?\s*$')
SKIP_DIRS = {".obsidian", ".trash", ".git"}

_vectors = {"key": None, "ids": [], "matrix": None}       # in-memory embedding matrix for vector search


def init():
    with db.connect() as con:
        con.executescript(SCHEMA)


def _kind(rel: str, front: str) -> str:
    parts = rel.split("/")
    if "michael: hub" in front:
        return "hub"
    for folder, kind in (("Sources", "source"), ("Topics", "topic"), ("Key points", "keypoints"),
                         ("Flashcards", "flashcards"), ("Michael", "answer"), ("Maps", "map")):
        if folder in parts[:-1]:
            return kind
    return "note"


def _parse(path: Path, vault: Path):
    from .host.heralds.vault import FRONTMATTER, file_chunks, is_generated
    text = path.read_text(encoding="utf8", errors="ignore")
    m = FRONTMATTER.match(text)
    front = m.group(0) if m else ""
    rel = path.relative_to(vault).as_posix()
    title = (FM_FIELD("title").search(front) or FM_FIELD("question").search(front))
    note = {"path": str(path), "vault": str(vault), "rel": rel, "title": title.group(1) if title else path.stem,
            "subject": rel.split("/")[0] if "/" in rel else "", "kind": _kind(rel, front),
            "generated": int(is_generated(path)), "url": (FM_FIELD("url").search(front) or [None, ""])[1],
            "mtime": path.stat().st_mtime, "hash": sha(text), "chars": len(text)}
    chunks = file_chunks(path)
    links = {(l.strip(), "body") for l in LINK.findall(text)}
    return note, chunks, links


def index_vault(vault: str | Path, embed: bool = True, on_progress=None) -> dict:
    """Bring the index up to date with the vault. Unchanged files are skipped (mtime, then content hash)."""
    vault = Path(vault).resolve()
    init()
    with db.connect() as con:
        known = {r["path"]: (r["mtime"], r["hash"]) for r in
                 con.execute("SELECT path, mtime, hash FROM vault_notes WHERE vault=?", (str(vault),))}
    seen, changed, new_chunks = set(), 0, []
    files = [p for p in vault.rglob("*.md") if not any(part in SKIP_DIRS for part in p.relative_to(vault).parts)]
    for i, path in enumerate(files):
        key = str(path)
        seen.add(key)
        mtime = path.stat().st_mtime
        if key in known and known[key][0] == mtime:
            continue
        note, chunks, links = _parse(path, vault)
        if key in known and known[key][1] == note["hash"]:
            with db.connect() as con:
                con.execute("UPDATE vault_notes SET mtime=? WHERE path=?", (mtime, key))
            continue
        changed += 1
        with db.connect() as con:
            _delete(con, key)
            con.execute("INSERT INTO vault_notes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (note["path"], note["vault"], note["rel"], note["title"], note["subject"], note["kind"],
                         note["generated"], note["url"], note["mtime"], note["hash"], note["chars"], time.time()))
            for c in chunks:
                cid = sha(f"{key}|{c.start}|{c.end}")[:20]
                con.execute("INSERT OR REPLACE INTO vault_chunks VALUES (?,?,?,?,?,?,?)",
                            (cid, key, c.heading, c.start, c.end, c.text, sha(c.text)))
                con.execute("INSERT INTO vault_fts (chunk_id, title, heading, text) VALUES (?,?,?,?)",
                            (cid, note["title"], c.heading, c.text))
                new_chunks.append(c)
            con.executemany("INSERT INTO vault_links VALUES (?,?,?)", [(key, d, k) for d, k in links])
        if note["generated"] and note["kind"] in ("topic", "keypoints", "answer"):
            from .learning import index_note_claims          # every sentence, verdict and quote -> note_claims
            index_note_claims(key, path.read_text(encoding="utf8", errors="ignore"))
        if on_progress and changed % 25 == 0:
            on_progress(f"indexed {changed} notes ({i + 1}/{len(files)} checked)")
    removed = [p for p in known if p not in seen]
    with db.connect() as con:
        for p in removed:
            _delete(con, p)
    embedded = _backfill_embeddings(on_progress) if embed else 0
    if changed or removed or embedded:
        _vectors["key"] = None
    return {"indexed": changed, "unchanged": len(seen) - changed, "removed": len(removed), "embedded": embedded}


def _backfill_embeddings(on_progress=None, batch: int = 256) -> int:
    """Embed every indexed chunk that has no vector yet: new chunks, and chunks left over by an interrupted run."""
    with db.connect() as con:
        rows = con.execute("SELECT DISTINCT hash, text FROM vault_chunks").fetchall()
    have = db.get_embeddings([r["hash"] for r in rows], settings.embed_model)
    todo = [r for r in rows if r["hash"] not in have]
    if not todo:
        return 0
    from .host.archangel import EMBEDDER
    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
        vecs = EMBEDDER.encode([r["text"] for r in part])
        db.put_embeddings({r["hash"]: v for r, v in zip(part, vecs)}, settings.embed_model)
        if on_progress:
            on_progress(f"embedded {min(i + batch, len(todo))}/{len(todo)} passages")
    return len(todo)


def _delete(con, path: str):
    ids = [r["id"] for r in con.execute("SELECT id FROM vault_chunks WHERE path=?", (path,))]
    if ids:
        con.executemany("DELETE FROM vault_fts WHERE chunk_id=?", [(i,) for i in ids])
    con.execute("DELETE FROM vault_chunks WHERE path=?", (path,))
    con.execute("DELETE FROM vault_links WHERE src=?", (path,))
    con.execute("DELETE FROM vault_notes WHERE path=?", (path,))


def _fts_query(q: str) -> str:
    words = re.findall(r"\w+", q.lower())
    return " OR ".join(f'"{w}"' for w in words if len(w) > 1) or '""'


def _vector_matrix():
    with db.connect() as con:
        rows = con.execute("SELECT id, hash FROM vault_chunks ORDER BY id").fetchall()
    key = (len(rows), rows[0]["id"] if rows else None, rows[-1]["id"] if rows else None)
    if _vectors["key"] != key:
        vecs = db.get_embeddings([r["hash"] for r in rows], settings.embed_model)
        ids = [r["id"] for r in rows if r["hash"] in vecs]
        _vectors.update(key=key, ids=ids,
                        matrix=np.stack([vecs[r["hash"]] for r in rows if r["hash"] in vecs]) if ids else None)
    return _vectors["ids"], _vectors["matrix"]


def search(query: str, k: int = 10, subject: str | None = None, include_generated: bool = True,
           kinds: tuple | None = None, vector: bool = True) -> list[dict]:
    """Hybrid search over the indexed vault: FTS5 (BM25) + embedding similarity, fused with RRF."""
    init()
    where, params = ["1=1"], []
    if subject:
        where.append("n.subject = ?"); params.append(subject)
    if not include_generated:
        where.append("n.generated = 0")
    if kinds:
        where.append(f"n.kind IN ({','.join('?' * len(kinds))})"); params += list(kinds)
    filt = " AND ".join(where)
    with db.connect() as con:
        fts = [r["chunk_id"] for r in con.execute(
            f"SELECT f.chunk_id FROM vault_fts f JOIN vault_chunks c ON c.id=f.chunk_id JOIN vault_notes n "
            f"ON n.path=c.path WHERE vault_fts MATCH ? AND {filt} ORDER BY bm25(vault_fts, 0, 5.0, 2.0, 1.0) LIMIT 50",
            [_fts_query(query), *params])]
        allowed = None
        if subject or not include_generated or kinds:
            allowed = {r["id"] for r in con.execute(
                f"SELECT c.id FROM vault_chunks c JOIN vault_notes n ON n.path=c.path WHERE {filt}", params)}
    rankings = [fts]
    if vector:
        ids, matrix = _vector_matrix()
        if matrix is not None:
            from .host.archangel import EMBEDDER
            sims = matrix @ EMBEDDER.query(query)
            order = [ids[i] for i in np.argsort(-sims)[:200] if allowed is None or ids[i] in allowed][:50]
            rankings.append(order)
    from .host.jophiel import rrf
    pos = {cid: i for i, cid in enumerate(set(x for r in rankings for x in r))}
    back = {i: cid for cid, i in pos.items()}
    fused = rrf([[pos[c] for c in r] for r in rankings])
    top = [back[i] for i in sorted(fused, key=fused.get, reverse=True)[:k]]
    if not top:
        return []
    with db.connect() as con:
        rows = {r["id"]: dict(r) for r in con.execute(
            f"SELECT c.id, c.heading, c.start, c.end_, c.text, n.path, n.rel, n.title, n.subject, n.kind, n.url "
            f"FROM vault_chunks c JOIN vault_notes n ON n.path=c.path WHERE c.id IN ({','.join('?' * len(top))})", top)}
    return [{**rows[c], "score": round(fused[pos[c]], 5)} for c in top if c in rows]


def as_chunks(results: list[dict]) -> list[Chunk]:
    """Search results as pipeline Chunks (kind 'vault', citable as [[Note#Heading]])."""
    return [Chunk(source_id=sha(r["path"])[:16], kind="vault", title=Path(r["path"]).stem, url=r["path"],
                  text=r["text"], start=r["start"], end=r["end_"], heading=r["heading"]) for r in results]


def stats() -> dict:
    init()
    with db.connect() as con:
        kinds = {r["kind"]: r["n"] for r in con.execute("SELECT kind, COUNT(*) n FROM vault_notes GROUP BY kind")}
        n_chunks = con.execute("SELECT COUNT(*) FROM vault_chunks").fetchone()[0]
        n_links = con.execute("SELECT COUNT(*) FROM vault_links").fetchone()[0]
        subjects = {r["subject"]: r["n"] for r in con.execute(
            "SELECT subject, COUNT(*) n FROM vault_notes WHERE kind='source' GROUP BY subject")}
    return {"notes": sum(kinds.values()), "by_kind": kinds, "chunks": n_chunks, "links": n_links,
            "sources_by_subject": subjects}
