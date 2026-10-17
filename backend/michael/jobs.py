"""Persistent job queue, event stream and nightly scheduler.

Every long task (research, add article, index, library build, quote re-check) is a row in the `jobs` table.
One worker thread runs them in priority order: the models share one CPU, so one at a time is the fastest.
A job that was running when the backend stopped is put back in the queue on start-up, and every progress event is
stored, so a client can reconnect and replay a job's history.

    enqueue(kind, params, title, priority) -> job id
    cancel(job_id)
    subscribe(job_id) -> queue of events (history first, then live; None marks the end)
"""
import json
import queue
import threading
import time
import traceback
import uuid
from datetime import datetime

from . import db
from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, kind TEXT, title TEXT, params TEXT, status TEXT, priority INTEGER,
    created REAL, started REAL, finished REAL, progress TEXT, result TEXT, error TEXT, attempts INTEGER
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, priority, created);
CREATE TABLE IF NOT EXISTS job_events (job_id TEXT, t REAL, stage TEXT, detail TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS job_events_job ON job_events(job_id);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""

PRIORITY = {"research": 10, "verify": 10, "article": 20, "index": 30, "library": 50, "recheck": 60}


class Cancelled(Exception):
    pass


_subscribers: dict[str, list[queue.Queue]] = {}
_sub_lock = threading.Lock()
_cancel: set[str] = set()
_wake = threading.Event()
_started = False


def init():
    with db.connect() as con:
        con.executescript(SCHEMA)
        # whatever was running when the backend stopped runs again
        con.execute("UPDATE jobs SET status='queued', progress='restarted after a stop' WHERE status='running'")


# ------------------------------------------------------------------ key-value settings (e.g. the active vault)
def kv_get(key: str, default=None):
    with db.connect() as con:
        r = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def kv_set(key: str, value):
    with db.connect() as con:
        con.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json.dumps(value)))


# ------------------------------------------------------------------ queue
def enqueue(kind: str, params: dict, title: str = "", priority: int | None = None, job_id: str | None = None) -> str:
    if kind not in HANDLERS:
        raise ValueError(f"unknown job kind {kind!r}; known: {sorted(HANDLERS)}")
    job_id = job_id or uuid.uuid4().hex[:12]
    with db.connect() as con:
        con.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (job_id, kind, title or kind, json.dumps(params), "queued", PRIORITY.get(kind, 50) if priority is None
                     else priority, time.time(), None, None, "queued", None, None, 0))
    _publish(job_id, {"run_id": job_id, "stage": "queued", "detail": "waiting for the models", "t": 0})
    _wake.set()
    return job_id


def cancel(job_id: str) -> bool:
    # (db.connect holds a non-reentrant lock: never call _publish inside a `with db.connect()` block)
    with db.connect() as con:
        r = con.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        status = r["status"] if r else None
        if status == "queued":
            con.execute("UPDATE jobs SET status='cancelled', finished=? WHERE id=?", (time.time(), job_id))
    if status not in ("queued", "running"):
        return False
    if status == "queued":
        _publish(job_id, {"run_id": job_id, "stage": "cancelled", "detail": "cancelled", "t": 0}, final=True)
        return True
    _cancel.add(job_id)           # running: stops at the next progress event
    return True


def get(job_id: str) -> dict | None:
    with db.connect() as con:
        r = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _row(r) if r else None


def list_jobs(limit: int = 50, status: str | None = None) -> list[dict]:
    with db.connect() as con:
        rows = con.execute("SELECT * FROM jobs" + (" WHERE status=?" if status else "") +
                           " ORDER BY created DESC LIMIT ?", ((status, limit) if status else (limit,))).fetchall()
    return [_row(r) for r in rows]


def _row(r) -> dict:
    d = dict(r)
    for k in ("params", "result"):
        d[k] = json.loads(d[k]) if d.get(k) else None
    return d


# ------------------------------------------------------------------ events
def _publish(job_id: str, event: dict, final: bool = False):
    with db.connect() as con:
        con.execute("INSERT INTO job_events VALUES (?,?,?,?,?)",
                    (job_id, time.time(), event.get("stage"), event.get("detail", ""),
                     json.dumps({k: v for k, v in event.items() if k not in ("stage", "detail")}, default=str)))
        if event.get("stage") not in ("done", "error", "cancelled"):
            con.execute("UPDATE jobs SET progress=? WHERE id=?", (f"{event.get('stage')}: {event.get('detail', '')}", job_id))
    with _sub_lock:
        for q in _subscribers.get(job_id, []):
            q.put(event)
            if final:
                q.put(None)


def subscribe(job_id: str) -> queue.Queue:
    """History first, then live events; None ends the stream."""
    q: queue.Queue = queue.Queue()
    with _sub_lock:
        with db.connect() as con:
            for r in con.execute("SELECT stage, detail, data FROM job_events WHERE job_id=? ORDER BY rowid", (job_id,)):
                q.put({"stage": r["stage"], "detail": r["detail"], **json.loads(r["data"] or "{}")})
            status = (con.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone() or {"status": None})["status"]
        if status in ("done", "error", "cancelled", None):
            q.put(None)
        else:
            _subscribers.setdefault(job_id, []).append(q)
    return q


def unsubscribe(job_id: str, q: queue.Queue):
    with _sub_lock:
        if q in _subscribers.get(job_id, []):
            _subscribers[job_id].remove(q)


# ------------------------------------------------------------------ worker
def _next_job():
    with db.connect() as con:
        r = con.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY priority, created LIMIT 1").fetchone()
        if r:
            con.execute("UPDATE jobs SET status='running', started=?, attempts=attempts+1 WHERE id=?", (time.time(), r["id"]))
    return _row(r) if r else None


def _run(job: dict):
    jid = job["id"]

    def emit(event: dict):
        if jid in _cancel:
            raise Cancelled()
        _publish(jid, {**event, "run_id": jid})

    try:
        result = HANDLERS[job["kind"]](job["params"] or {}, emit, jid)
        status, error = "done", None
    except Cancelled:
        result, status, error = None, "cancelled", "cancelled by user"
    except Exception as e:
        result, status, error = None, "error", f"{type(e).__name__}: {e}"
        traceback.print_exc()
    _cancel.discard(jid)
    with db.connect() as con:
        con.execute("UPDATE jobs SET status=?, finished=?, result=?, error=? WHERE id=?",
                    (status, time.time(), json.dumps(result, default=str) if result is not None else None, error, jid))
    final = {"done": {"stage": "done", "detail": "finished", **(result if isinstance(result, dict) else {})},
             "cancelled": {"stage": "cancelled", "detail": "cancelled"},
             "error": {"stage": "error", "detail": error}}[status]
    _publish(jid, {**final, "run_id": jid, "t": 0}, final=True)


def _worker():
    while True:
        job = _next_job()
        if job is None:
            _wake.wait(timeout=5)
            _wake.clear()
            continue
        _run(job)


def _scheduler():
    """Nightly maintenance at settings.nightly_hour: re-index the vault, re-check citations, and build key points
    for articles added since the last run. Runs at most once per day."""
    while True:
        time.sleep(60)
        now = datetime.now()
        if now.hour != settings.nightly_hour or kv_get("nightly_last") == now.strftime("%Y-%m-%d"):
            continue
        kv_set("nightly_last", now.strftime("%Y-%m-%d"))
        vault = kv_get("vault_path") or settings.vault_path
        if vault:
            enqueue("index", {"vault_path": vault}, "nightly: re-index vault")
            enqueue("recheck", {"vault_path": vault}, "nightly: re-check citations")
            enqueue("library", {"vault_path": vault, "phase": "keypoints"}, "nightly: key points for new articles")


def start():
    """Start the worker and scheduler threads once per process."""
    global _started
    if _started:
        return
    _started = True
    init()
    threading.Thread(target=_worker, name="michael-worker", daemon=True).start()
    threading.Thread(target=_scheduler, name="michael-scheduler", daemon=True).start()


# ------------------------------------------------------------------ job handlers: params, emit, job id -> result
def _research(p, emit, jid):
    from .host.archangel import run_research
    r = run_research(p["question"], kinds=p.get("sources"), urls=p.get("urls", []), use_vault=p.get("use_vault", True),
                     repair_enabled=p.get("repair", True), on_event=emit, run_id=jid, vault_path=p.get("vault_path"))
    return {"note": r["note"], "stats": r["stats"]}


def _article(p, emit, jid):
    from .host.pravuil import add_article
    r = add_article(p["target"], summary=p.get("summary", True), vault_path=p.get("vault_path"), on_event=emit,
                    run_id=jid, subject=p.get("subject"))
    return {"note": r["note"], "source_note": r["source_note"], "stats": r["stats"]}


def _index(p, emit, jid):
    from . import vault_index
    vault = p.get("vault_path") or kv_get("vault_path") or settings.vault_path
    r = vault_index.index_vault(vault, on_progress=lambda d: emit({"stage": "index", "detail": d}))
    return {**r, "stats": vault_index.stats()}


def _recheck(p, emit, jid):
    from .provenance import recheck_vault
    return recheck_vault(p.get("vault_path") or kv_get("vault_path") or settings.vault_path,
                         on_progress=lambda d: emit({"stage": "recheck", "detail": d}))


def _library(p, emit, jid):
    """Run a library build phase in a subprocess (it is long and uses its own state file)."""
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    cmd = [sys.executable, "-u", str(root / "scripts" / "build_library.py"), p.get("phase", "keypoints")]
    if p.get("vault_path"):
        cmd += ["--vault", p["vault_path"]]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf8",
                            errors="replace", cwd=root)
    try:
        for line in proc.stdout:
            line = line.strip()
            if line and not line.lower().startswith(("warning", "loading")):
                emit({"stage": "library", "detail": line[:300]})
    except Cancelled:
        proc.kill()
        raise
    return {"exit_code": proc.wait()}


HANDLERS = {"research": _research, "article": _article, "index": _index, "recheck": _recheck, "library": _library}
