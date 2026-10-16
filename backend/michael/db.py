"""SQLite storage: source cache, embedding cache, runs, claims, verdicts and human labels."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

import numpy as np

from .config import settings
from .models import Source

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, kind TEXT, title TEXT, url TEXT, text TEXT,
    query TEXT, fetched_at REAL, hash TEXT
);
CREATE TABLE IF NOT EXISTS search_cache (
    key TEXT PRIMARY KEY, source_ids TEXT, fetched_at REAL
);
CREATE TABLE IF NOT EXISTS embeddings (
    hash TEXT, model TEXT, vector BLOB, PRIMARY KEY (hash, model)
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, question TEXT, model TEXT, status TEXT,
    started_at REAL, finished_at REAL, note_path TEXT, markdown TEXT, stats TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS evidence (
    run_id TEXT, label TEXT, chunk_id TEXT, kind TEXT, title TEXT, url TEXT,
    heading TEXT, text TEXT, score REAL
);
CREATE TABLE IF NOT EXISTS claims (
    run_id TEXT, idx INTEGER, sentence TEXT, citations TEXT, status TEXT, rounds INTEGER,
    PRIMARY KEY (run_id, idx)
);
CREATE TABLE IF NOT EXISTS verdicts (
    run_id TEXT, claim_idx INTEGER, label TEXT, evidence_label TEXT, chunk_id TEXT,
    quote TEXT, quote_start INTEGER, quote_end INTEGER, entailment REAL, contradiction REAL
);
CREATE TABLE IF NOT EXISTS human_labels (
    run_id TEXT, claim_idx INTEGER, human_label TEXT, system_label TEXT, created_at REAL,
    PRIMARY KEY (run_id, claim_idx)
);
"""

_lock = threading.Lock()


@contextmanager
def connect():
    with _lock:
        con = sqlite3.connect(settings.db_path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()


def init():
    with connect() as con:
        con.executescript(SCHEMA)


# ----------------------------------------------------------------- source cache
def cached_search(key: str, max_age_days: float):
    with connect() as con:
        row = con.execute("SELECT source_ids, fetched_at FROM search_cache WHERE key=?", (key,)).fetchone()
        if not row or time.time() - row["fetched_at"] > max_age_days * 86400:
            return None
        ids = json.loads(row["source_ids"])
        rows = {r["id"]: r for r in con.execute(
            f"SELECT * FROM sources WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
        return [Source(kind=r["kind"], title=r["title"], url=r["url"], text=r["text"], id=r["id"])
                for i in ids if (r := rows.get(i))]


def store_search(key: str, sources: list[Source]):
    now = time.time()
    with connect() as con:
        for s in sources:
            con.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?,?)",
                        (s.id, s.kind, s.title, s.url, s.text, key, now, ""))
        con.execute("INSERT OR REPLACE INTO search_cache VALUES (?,?,?)",
                    (key, json.dumps([s.id for s in sources]), now))


# -------------------------------------------------------------- embedding cache
def get_embeddings(hashes: list[str], model: str) -> dict:
    if not hashes:
        return {}
    out = {}
    with connect() as con:
        for i in range(0, len(hashes), 500):
            part = hashes[i:i + 500]
            for r in con.execute(f"SELECT hash, vector FROM embeddings WHERE model=? AND hash IN ({','.join('?' * len(part))})",
                                 [model, *part]):
                out[r["hash"]] = np.frombuffer(r["vector"], dtype=np.float32)
    return out


def put_embeddings(items: dict, model: str):
    with connect() as con:
        con.executemany("INSERT OR REPLACE INTO embeddings VALUES (?,?,?)",
                        [(h, model, v.astype(np.float32).tobytes()) for h, v in items.items()])


# ------------------------------------------------------------------------ runs
def create_run(run_id: str, question: str, model: str, status: str = "running"):
    """Insert the run, or mark an already queued run as running."""
    with connect() as con:
        con.execute("INSERT INTO runs (id, question, model, status, started_at) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET status=excluded.status, started_at=excluded.started_at",
                    (run_id, question, model, status, time.time()))


def finish_run(run_id, status, note_path=None, markdown=None, stats=None, error=None):
    with connect() as con:
        con.execute("UPDATE runs SET status=?, finished_at=?, note_path=?, markdown=?, stats=?, error=? WHERE id=?",
                    (status, time.time(), note_path, markdown, json.dumps(stats or {}), error, run_id))


def save_results(run_id, evidence, claims, verdicts):
    with connect() as con:
        con.execute("DELETE FROM evidence WHERE run_id=?", (run_id,))
        con.execute("DELETE FROM claims WHERE run_id=?", (run_id,))
        con.execute("DELETE FROM verdicts WHERE run_id=?", (run_id,))
        con.executemany("INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?)",
                        [(run_id, c.label, c.id, c.kind, c.title, c.url, c.heading, c.text, c.score) for c in evidence])
        con.executemany("INSERT INTO claims VALUES (?,?,?,?,?,?)",
                        [(run_id, c.index, c.sentence, json.dumps(c.citations), c.status, c.rounds) for c in claims])
        con.executemany("INSERT INTO verdicts VALUES (?,?,?,?,?,?,?,?,?,?)",
                        [(run_id, v.claim_index, v.label, v.evidence_label, v.chunk_id, v.quote, v.quote_start,
                          v.quote_end, v.entailment, v.contradiction) for v in verdicts])


def list_runs(limit=100):
    with connect() as con:
        rows = con.execute("SELECT id, question, model, status, started_at, finished_at, stats FROM runs "
                           "ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    return [{**dict(r), "stats": json.loads(r["stats"] or "{}")} for r in rows]


def get_run(run_id):
    with connect() as con:
        run = con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not run:
            return None
        ev = [dict(r) for r in con.execute("SELECT * FROM evidence WHERE run_id=? ORDER BY rowid", (run_id,))]
        cl = [dict(r) for r in con.execute("SELECT * FROM claims WHERE run_id=? ORDER BY idx", (run_id,))]
        vd = {r["claim_idx"]: dict(r) for r in con.execute("SELECT * FROM verdicts WHERE run_id=?", (run_id,))}
        hl = {r["claim_idx"]: r["human_label"] for r in con.execute("SELECT * FROM human_labels WHERE run_id=?", (run_id,))}
    for c in cl:
        c["citations"] = json.loads(c["citations"])
        c["verdict"] = vd.get(c["idx"])
        c["human_label"] = hl.get(c["idx"])
    return {**dict(run), "stats": json.loads(run["stats"] or "{}"), "evidence": ev, "claims": cl}


def save_label(run_id, claim_idx, human_label, system_label):
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO human_labels VALUES (?,?,?,?,?)",
                    (run_id, claim_idx, human_label, system_label, time.time()))


def all_labels():
    with connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT h.*, c.sentence, v.quote FROM human_labels h "
            "JOIN claims c ON c.run_id=h.run_id AND c.idx=h.claim_idx "
            "LEFT JOIN verdicts v ON v.run_id=h.run_id AND v.claim_idx=h.claim_idx")]
