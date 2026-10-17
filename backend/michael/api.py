"""FastAPI server used by the Obsidian plugin and the dashboard.

Long tasks are jobs in a persistent queue (jobs.py): they survive restarts, can be cancelled, and stream progress.

POST /research            queue a research question -> {run_id}
POST /articles            queue an article (URL, arXiv id or PDF path), optionally with key points
GET  /runs/{id}/events    server-sent events: the job's history, then live progress
GET  /runs, /runs/{id}    history and full results
POST /verify              check one sentence against pasted evidence
POST /runs/{id}/claims/{idx}/label   human correction (becomes evaluation data)

/api/v1/jobs              list / create jobs (research, article, index, recheck, library); cancel; events
/api/v1/search            hybrid search over the indexed vault
/api/v1/index             bring the vault index up to date
/api/v1/library/stats     counts of notes, chunks, links
/api/v1/events            vault changes seen by the file watcher (server-sent events)
"""
import asyncio
import json
import queue
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import db, jobs, llm, watcher
from .config import settings


@asynccontextmanager
async def lifespan(_app):
    db.init()
    jobs.start()                                           # worker + nightly scheduler
    extension_token()                                      # writes browser-extension/local-token.json
    watcher.watch_vault(jobs.kv_get("vault_path") or settings.vault_path)
    from .host.archangel import warm_up
    threading.Thread(target=warm_up, daemon=True).start()  # models load while Obsidian starts up
    yield
    watcher.stop()


app = FastAPI(title="Michael", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "app://obsidian.md", "capacitor://localhost"],
                   allow_origin_regex=r"(https?://(localhost|127\.0\.0\.1)(:\d+)?|chrome-extension://[a-p]{32})",
                   allow_methods=["*"], allow_headers=["*"])


def extension_token() -> str:
    """Shared secret for the browser extension (created once). Only callers that know it may write links."""
    import secrets
    token = jobs.kv_get("extension_token")
    if not token:
        token = secrets.token_urlsafe(24)
        jobs.kv_set("extension_token", token)
    _write_extension_token(token)
    return token


def _write_extension_token(token: str):
    """Put the token next to the unpacked extension so it connects without any copy-paste.
    The file is git-ignored and never leaves this computer."""
    from pathlib import Path
    f = Path(__file__).resolve().parents[2] / "browser-extension" / "local-token.json"
    try:
        if not f.exists() or token not in f.read_text(encoding="utf8"):
            f.write_text(json.dumps({"token": token}), encoding="utf8")
    except OSError:
        pass


def _check_token(token: str | None):
    if not token or token != extension_token():
        raise HTTPException(401, "missing or wrong X-Michael-Token (copy it from Obsidian: 'Michael: Copy extension token')")


class ResearchRequest(BaseModel):
    question: str
    sources: list[str] | None = None      # subset of the search sources
    urls: list[str] = []
    use_vault: bool = True
    vault_path: str | None = None        # sent by the Obsidian plugin (its own vault)
    repair: bool = True


class ArticleRequest(BaseModel):
    target: str                           # web URL, arXiv link/id, PDF URL or local PDF path
    summary: bool = True                  # also write a verified key-points note
    vault_path: str | None = None
    subject: str | None = None


class JobRequest(BaseModel):
    kind: str                             # research | article | index | recheck | library
    params: dict = {}
    title: str = ""
    priority: int | None = None


class VerifyRequest(BaseModel):
    sentence: str
    evidence: str


class LabelRequest(BaseModel):
    human_label: str                      # "supported" | "unsupported"


def _remember_vault(path: str | None):
    """The plugin tells us which vault it is in: remember it for the watcher and the nightly jobs."""
    if path and path != jobs.kv_get("vault_path"):
        jobs.kv_set("vault_path", path)
    watcher.watch_vault(path)


@app.get("/health")
def health():
    return {"ok": True, "llm": settings.llm_model, "llm_available": llm.available(), "verifier": settings.nli_model,
            "vault": jobs.kv_get("vault_path") or settings.vault_path, "notes_dir": str(settings.notes_dir),
            "queued": len(jobs.list_jobs(status="queued")), "running": len(jobs.list_jobs(status="running"))}


@app.post("/research")
def research(req: ResearchRequest):
    if not req.question.strip():
        raise HTTPException(400, "question is empty")
    _remember_vault(req.vault_path)
    job_id = jobs.enqueue("research", req.model_dump(), req.question)
    db.create_run(job_id, req.question, settings.llm_model, status="queued")   # visible to GET /runs/{id} at once
    return {"run_id": job_id}


@app.post("/articles")
def articles(req: ArticleRequest):
    if not req.target.strip():
        raise HTTPException(400, "target is empty")
    _remember_vault(req.vault_path)
    title = f"Add article: {req.target}"
    job_id = jobs.enqueue("article", {**req.model_dump(), "target": req.target.strip()}, title)
    db.create_run(job_id, title, settings.llm_model, status="queued")
    return {"run_id": job_id}


def _sse(q: queue.Queue, on_close=None):
    async def stream():
        try:
            while True:
                item = await asyncio.to_thread(q.get)
                if item is None:
                    break
                yield {"event": item.get("stage", "message"), "data": json.dumps(item, default=str)}
        finally:
            if on_close:
                on_close()
    return EventSourceResponse(stream())


@app.get("/runs/{run_id}/events")
@app.get("/api/v1/jobs/{run_id}/events")
async def events(run_id: str):
    if not jobs.get(run_id):
        raise HTTPException(404, "unknown job")
    q = jobs.subscribe(run_id)
    return _sse(q, lambda: jobs.unsubscribe(run_id, q))


# ------------------------------------------------------------------ v1: jobs
@app.post("/api/v1/jobs")
def create_job(req: JobRequest):
    try:
        return {"id": jobs.enqueue(req.kind, req.params, req.title, req.priority)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/v1/jobs")
def list_jobs(limit: int = 50, status: str | None = None):
    return jobs.list_jobs(min(limit, 500), status)


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str):
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "unknown job")
    return j


@app.post("/api/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if not jobs.cancel(job_id):
        raise HTTPException(409, "job is not queued or running")
    return {"ok": True}


# ------------------------------------------------------------------ v1: vault index
@app.get("/api/v1/search")
def search(q: str, k: int = 10, subject: str | None = None, include_generated: bool = True):
    from . import vault_index
    return {"query": q, "results": vault_index.search(q, k=min(k, 50), subject=subject,
                                                      include_generated=include_generated)}


class IndexRequest(BaseModel):
    vault_path: str | None = None


@app.post("/api/v1/index")
def reindex(req: IndexRequest):
    vault = req.vault_path or jobs.kv_get("vault_path") or settings.vault_path
    if not vault:
        raise HTTPException(400, "no vault: pass vault_path or set MICHAEL_VAULT")
    _remember_vault(vault)
    return {"id": jobs.enqueue("index", {"vault_path": vault}, "re-index vault")}


@app.get("/api/v1/library/stats")
def library_stats():
    from . import vault_index
    return vault_index.stats()


@app.get("/api/v1/events")
async def vault_events():
    """Live vault changes (from the file watcher), for clients that show the library."""
    q: queue.Queue = queue.Queue()
    watcher.listeners.append(q.put)
    return _sse(q, lambda: watcher.listeners.remove(q.put) if q.put in watcher.listeners else None)


# ------------------------------------------------------------------ v1: browser extension
class ClassifyRequest(BaseModel):
    url: str
    title: str = ""
    text: str = ""


class LinkRequest(BaseModel):
    url: str
    title: str
    subject: str
    topic: str


@app.get("/api/v1/token")
def get_token(request: Request):
    """Only Obsidian (or a local command line, which sends no Origin) may read the extension token."""
    origin = request.headers.get("origin")
    if origin not in (None, "app://obsidian.md"):
        raise HTTPException(403, "the token is only shown inside Obsidian")
    return {"token": extension_token()}


@app.post("/api/v1/classify")
def classify(req: ClassifyRequest, x_michael_token: str | None = Header(None)):
    _check_token(x_michael_token)
    from .host import raziel
    saved = raziel.already_saved(req.url)
    suggestions = [] if saved else raziel.classify(req.title, req.text)
    top = suggestions[0]["similarity"] if suggestions else 0.0
    return {"already_saved": saved, "suggestions": suggestions,
            "relevant": bool(saved) or top >= raziel.RELEVANT_SIMILARITY,
            "inbox": not saved and top < raziel.TOPIC_SIMILARITY}


@app.post("/api/v1/links")
def add_link(req: LinkRequest, x_michael_token: str | None = Header(None)):
    _check_token(x_michael_token)
    from .host import raziel
    vault = jobs.kv_get("vault_path") or settings.vault_path
    if not vault:
        raise HTTPException(400, "no vault known yet: open Obsidian with the Michael plugin once")
    path = raziel.link_note(vault, req.url, req.title.strip() or req.url, req.subject, req.topic,
                            raziel.subject_tag(req.subject))
    raziel.refresh_hubs(vault)
    jobs.kv_set("recent_links", ([{"title": req.title, "url": req.url, "subject": req.subject, "topic": req.topic}]
                                 + (jobs.kv_get("recent_links") or []))[:20])
    return {"ok": True, "note": str(path)}


@app.get("/api/v1/links")
def recent_links(limit: int = 5, x_michael_token: str | None = Header(None)):
    _check_token(x_michael_token)
    return (jobs.kv_get("recent_links") or [])[:limit]


@app.get("/api/v1/topics")
def topics(x_michael_token: str | None = Header(None)):
    """Every subject and topic, for the extension's 'Other topic' menu."""
    _check_token(x_michael_token)
    from .host import raziel
    manifest = json.loads(raziel.MANIFEST.read_text(encoding="utf8"))
    return [{"subject": s["name"], "topics": [t["name"] for t in s["topics"]] + ["Inbox"]} for s in manifest["subjects"]]


# ------------------------------------------------------------------ runs (research history)
@app.get("/runs")
def runs():
    return db.list_runs()


@app.get("/runs/{run_id}")
def run(run_id: str):
    r = db.get_run(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    return r


@app.post("/verify")
def verify(req: VerifyRequest):
    from .host.archangel import verify_text
    return verify_text(req.sentence, req.evidence)


@app.post("/runs/{run_id}/claims/{idx}/label")
def label(run_id: str, idx: int, req: LabelRequest):
    r = db.get_run(run_id)
    claim = next((c for c in (r or {}).get("claims", []) if c["idx"] == idx), None)
    if not claim:
        raise HTTPException(404, "claim not found")
    if req.human_label not in ("supported", "unsupported"):
        raise HTTPException(400, "human_label must be 'supported' or 'unsupported'")
    db.save_label(run_id, idx, req.human_label, claim["status"])
    return {"ok": True}
