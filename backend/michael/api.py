"""FastAPI server used by the Obsidian plugin and the dashboard.

POST /research            start a run (background thread) -> {run_id}
POST /articles            add an article (URL, arXiv id or PDF path) to the vault, optionally with key points
GET  /runs/{id}/events    server-sent events with progress
GET  /runs, /runs/{id}    history and full results
POST /verify              check one sentence against pasted evidence
POST /runs/{id}/claims/{idx}/label   human correction (becomes evaluation data)
"""
import asyncio
import json
from contextlib import asynccontextmanager
import queue
import threading
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import db, llm
from .config import settings


@asynccontextmanager
async def lifespan(_app):
    db.init()
    from .host.archangel import warm_up
    threading.Thread(target=warm_up, daemon=True).start()   # models load while Obsidian starts up
    yield


app = FastAPI(title="Michael", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "app://obsidian.md", "capacitor://localhost"],
                   allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?", allow_methods=["*"], allow_headers=["*"])

_events: dict[str, queue.Queue] = {}
_run_lock = threading.Lock()          # one run at a time: the models share one CPU


class ResearchRequest(BaseModel):
    question: str
    sources: list[str] | None = None      # subset of wikipedia, arxiv, openalex
    urls: list[str] = []
    use_vault: bool = True
    vault_path: str | None = None        # sent by the Obsidian plugin (its own vault)
    repair: bool = True


class ArticleRequest(BaseModel):
    target: str                           # web URL, arXiv link/id, PDF URL or local PDF path
    summary: bool = True                  # also write a verified key-points note
    vault_path: str | None = None


class VerifyRequest(BaseModel):
    sentence: str
    evidence: str


class LabelRequest(BaseModel):
    human_label: str                      # "supported" | "unsupported"


@app.get("/health")
def health():
    return {"ok": True, "llm": settings.llm_model, "llm_available": llm.available(),
            "vault": settings.vault_path, "notes_dir": str(settings.notes_dir)}


def _start(title: str, job) -> dict:
    """Run job(on_event, run_id) in a background thread, one at a time; progress goes to an SSE queue."""
    run_id = uuid.uuid4().hex[:12]
    db.create_run(run_id, title, settings.llm_model, status="queued")   # visible to GET /runs/{id} at once
    q: queue.Queue = queue.Queue()
    _events[run_id] = q

    def work():
        with _run_lock:
            try:
                job(q.put, run_id)
            except Exception:
                pass                      # the error event has already been emitted
            finally:
                q.put(None)

    q.put({"run_id": run_id, "stage": "queued", "detail": "waiting for the models", "t": 0})
    threading.Thread(target=work, daemon=True).start()
    return {"run_id": run_id}


@app.post("/research")
def research(req: ResearchRequest):
    if not req.question.strip():
        raise HTTPException(400, "question is empty")
    from .host.archangel import run_research
    return _start(req.question, lambda on_event, run_id: run_research(
        req.question, kinds=req.sources, urls=req.urls, use_vault=req.use_vault, repair_enabled=req.repair,
        on_event=on_event, run_id=run_id, vault_path=req.vault_path))


@app.post("/articles")
def articles(req: ArticleRequest):
    if not req.target.strip():
        raise HTTPException(400, "target is empty")
    from .host.pravuil import add_article
    return _start(f"Add article: {req.target}", lambda on_event, run_id: add_article(
        req.target.strip(), summary=req.summary, vault_path=req.vault_path, on_event=on_event, run_id=run_id))


@app.get("/runs/{run_id}/events")
async def events(run_id: str):
    q = _events.get(run_id)
    if q is None:
        raise HTTPException(404, "unknown or finished run; use GET /runs/{id}")

    async def stream():
        while True:
            item = await asyncio.to_thread(q.get)
            if item is None:
                _events.pop(run_id, None)
                break
            yield {"event": item["stage"], "data": json.dumps(item)}

    return EventSourceResponse(stream())


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
    from . import vault_index
    vault = req.vault_path or settings.vault_path
    if not vault:
        raise HTTPException(400, "no vault: pass vault_path or set MICHAEL_VAULT")
    return {**vault_index.index_vault(vault), "stats": vault_index.stats()}


@app.get("/api/v1/library/stats")
def library_stats():
    from . import vault_index
    return vault_index.stats()


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
