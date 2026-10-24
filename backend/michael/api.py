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
import re
import json
import queue
import threading
from pathlib import Path
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


# ------------------------------------------------------------------ v1: library (read-only, for the web app)
def _vault() -> "Path":
    from pathlib import Path
    v = jobs.kv_get("vault_path") or settings.vault_path
    if not v:
        raise HTTPException(400, "no vault known yet")
    return Path(v).resolve()


@app.get("/api/v1/library")
def library():
    """Subjects -> topics -> overview, articles (with key points), saved links. Built from the manifest, the build
    state and the files actually present in the vault."""
    from pathlib import Path
    from .host import raziel
    vault = _vault()
    manifest = json.loads(raziel.MANIFEST.read_text(encoding="utf8"))
    state = json.loads(raziel.STATE.read_text(encoding="utf8")) if raziel.STATE.exists() else {}
    rel = lambda p: Path(p).resolve().relative_to(vault).as_posix() if p and Path(p).exists() else None
    out = []
    for subj in manifest["subjects"]:
        links = {}
        for p in sorted((vault / subj["name"] / "Links").glob("*.md")):
            m = re.search(r'(?m)^topic: "(.*)"$', p.read_text(encoding="utf8", errors="ignore")[:800])
            links.setdefault(m.group(1) if m else "Inbox", []).append({"title": p.stem, "path": rel(p)})
        topics = []
        for t in subj["topics"]:
            ts = state.get(f"topic:{subj['name']}/{t['name']}", {})
            arts = []
            for i in t["items"]:
                st = state.get(i, {})
                if st.get("status") == "saved":
                    arts.append({"title": st["title"], "path": rel(st["path"]), "route": st.get("route"),
                                 "formulas": st.get("formulas"), "rendered": st.get("rendered"),
                                 "keypoints": rel(st.get("keypoints")), "url": st.get("url")})
            topics.append({"name": t["name"], "overview": rel(ts.get("note")), "verified": ts.get("supported"),
                           "total": ts.get("total"), "deck": rel(ts.get("deck")), "articles": arts,
                           "links": links.get(t["name"], [])})
        out.append({"name": subj["name"], "tag": subj["tag"], "intro": subj["intro"], "topics": topics,
                    "inbox": links.get("Inbox", [])})
    return out


@app.get("/api/v1/note")
def note(path: str):
    """One vault note as Markdown, with [[wikilinks]] resolved to vault paths, plus its backlinks.
    Only files inside the vault can be read."""
    from pathlib import Path
    from . import vault_index
    vault = _vault()
    f = (vault / path).resolve()
    if vault not in f.parents or f.suffix != ".md" or not f.exists():
        raise HTTPException(404, "note not found")
    text = f.read_text(encoding="utf8", errors="ignore")
    front = {}
    if m := re.match(r"\A---\n(.*?)\n---\n", text, re.S):
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            front[k.strip()] = v.strip().strip('"')
        text = text[m.end():]
    stems = {}
    for p in vault.rglob("*.md"):
        if ".obsidian" not in p.parts and ".trash" not in p.parts:
            stems.setdefault(p.stem, p.relative_to(vault).as_posix())

    def link(m):
        target, heading, label = m.group(1).strip(), m.group(2), m.group(3)
        rp = stems.get(target)
        shown = label or (f"{target} › {heading}" if heading else target)
        from urllib.parse import quote          # paths have spaces: a Markdown link URL must not
        return f"[{shown}](note:{quote(rp)}{'#' + quote(heading) if heading else ''})" if rp else shown

    text = re.sub(r"\[\[([^\]|#]+)(?:#([^\]|]*))?(?:\|([^\]]*))?\]\]", link, text)
    text = re.sub(r"(?s)<!-- /?michael:[a-z]+ -->", "", text)
    vault_index.init()
    with db.connect() as con:
        back = [r["rel"] for r in con.execute(
            "SELECT DISTINCT n.rel FROM vault_links l JOIN vault_notes n ON n.path = l.src WHERE l.dst = ?", (f.stem,))]
    return {"path": f.relative_to(vault).as_posix(), "title": front.get("title") or front.get("question") or f.stem,
            "frontmatter": front, "markdown": text, "backlinks": back,
            "obsidian": f"obsidian://open?vault={vault.name}&file={f.relative_to(vault).as_posix()}"}


@app.get("/api/v1/graph")
def graph(subject: str | None = None):
    """Notes and the links between them (from the vault index), for the web app's graph view.
    Flashcard decks and maps are left out, like in the Obsidian graph settings."""
    from . import vault_index
    vault_index.init()
    with db.connect() as con:
        notes = [dict(r) for r in con.execute("SELECT path, rel, title, subject, kind FROM vault_notes "
                                              "WHERE kind NOT IN ('flashcards', 'map')")]
        links = con.execute("SELECT src, dst FROM vault_links").fetchall()
    if subject:
        notes = [n for n in notes if n["subject"] == subject]
    from pathlib import Path
    by_stem = {Path(n["path"]).stem: n["rel"] for n in notes}
    ids = {n["path"]: n["rel"] for n in notes}
    edges = {(ids[s], by_stem[d]) for s, d in links if s in ids and d in by_stem and ids[s] != by_stem[d]}
    return {"nodes": [{"id": n["rel"], "label": Path(n["rel"]).stem, "subject": n["subject"], "kind": n["kind"]}
                      for n in notes],
            "edges": [{"source": s, "target": t} for s, t in sorted(edges)]}


# ------------------------------------------------------------------ v1: flashcards (shared with the SR plugin)
class ReviewRequest(BaseModel):
    deck: str
    line: int
    question: str
    grade: str                            # easy | good | hard


def _resolve_wikilinks(text: str, vault) -> str:
    from urllib.parse import quote
    stems = {p.stem: p.relative_to(vault).as_posix() for p in vault.rglob("*.md")
             if ".obsidian" not in p.parts and ".trash" not in p.parts}

    def link(m):
        target, heading, label = m.group(1).strip(), m.group(2), m.group(3)
        rp, shown = stems.get(target), label or (f"{target} › {heading}" if heading else target)
        return f"[{shown}](note:{quote(rp)}{'#' + quote(heading) if heading else ''})" if rp else shown

    return re.sub(r"\[\[([^\]|#]+)(?:#([^\]|]*))?(?:\|([^\]]*))?\]\]", link, text)


@app.get("/api/v1/flashcards")
def flashcards(subject: str | None = None, limit: int = 50):
    from . import cards
    vault = _vault()
    out = cards.due_cards(vault, subject, limit=min(limit, 200))
    for c in out["cards"]:
        c["answer"] = _resolve_wikilinks(c["answer"], vault)
    return out


@app.post("/api/v1/flashcards/review")
def review_card(req: ReviewRequest):
    from . import cards, learning
    try:
        r = cards.review(_vault(), req.deck, req.line, req.question, req.grade)
        learning.log_review(req.deck, req.question, req.grade, r["interval"], r["ease"], r.get("was_new", False))
        return r
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError:
        raise HTTPException(404, "deck not found")
    except LookupError as e:
        raise HTTPException(409, str(e))


@app.get("/api/v1/flashcards/stats")
def flashcard_stats():
    from . import learning
    return learning.review_stats()


# ------------------------------------------------------------------ v1: claims, labels, calibration
@app.get("/api/v1/claims")
def claims(status: str | None = None, source: str | None = None, subject: str | None = None,
           q: str | None = None, limit: int = 100, path: str | None = None, conflicts: bool = False):
    """Every sentence of Michael's notes with its verdict: e.g. ?status=partial, ?source=Euclidean algorithm,
    ?path=Number Theory/Topics/Primes.md (one note: the Obsidian trust panel), ?conflicts=true."""
    from . import learning
    return learning.query_claims(status, source, subject, q, min(limit, 1000), path, conflicts)


@app.get("/api/v1/quiz")
def quiz(subject: str | None = None, n: int = 10, seed: int | None = None):
    """Study mode: multiple-choice questions from verified facts (key term blanked; answer proven by a quote)."""
    from .quiz import make_quiz
    return {"questions": make_quiz(subject or None, min(max(n, 1), 30), seed)}


@app.get("/api/v1/calibration")
def calibration(target: float = 0.95, strict: bool = True):
    """Recommended support threshold from the gold labels (eval/gold, imported into the database)."""
    from pathlib import Path
    from . import learning
    learning.import_gold(Path(__file__).resolve().parents[2] / "eval" / "gold")
    return learning.calibrate(target, strict)


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
    # empty text = a badge-only check from a page already asked about: no need to classify
    suggestions = [] if saved or not req.text.strip() else raziel.classify(req.title, req.text)
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
    path = raziel.link_note(vault, req.url, raziel.clean_link_title(req.title or req.url), req.subject, req.topic,
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


class CheckRequest(BaseModel):
    text: str                              # any text, e.g. another AI's answer
    evidence: str | None = None            # judge against this text; omitted: against the library's sources
    k: int = 6                             # passages searched per sentence (library mode)
    subject: str | None = None


@app.post("/api/v1/check")
def check(req: CheckRequest):
    """Fact-check a text sentence by sentence with Michael's verifier: verdict, exact quote and source per sentence."""
    if not req.text.strip():
        raise HTTPException(400, "text is empty")
    from .host.archangel import check_text
    return check_text(req.text, req.evidence, min(max(req.k, 1), 12), req.subject)


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
