"""Pravuil, the archangel who keeps the heavenly records: adds an article to the vault and summarises it.

1. Fetch with the most exact route available:
     arXiv id/link -> author's LaTeX via pandoc (exact math) -> arXiv HTML (LaTeXML alttext) -> PDF text
     web page      -> HTML with math recovered from alttext / TeX annotations
     PDF           -> plain text (math is not reliable; flagged in the note)
2. Check every formula with MathJax; broken ones become flagged code, never silently wrong math.
3. Save the article verbatim (no LLM involved) to <vault>/Sources/<title>.md with its metadata.
4. Optionally write a key-points note from it with the normal pipeline: every sentence cites a quote
   from the saved article ([[Title#Section]]) and is checked by the independent verifier.
"""
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

from .. import db, llm
from ..config import settings
from . import gabriel, metatron
from .archangel import select_evidence, verify_and_repair
from .heralds import arxiv_latex, mathcheck, pdf as pdf_src, webmath
from .heralds.arxiv_latex import Article
from .heralds.vault import file_chunks

ROUTE_LABEL = {
    "arxiv-latex": "author's LaTeX source from arXiv (exact math)",
    "arxiv-html": "arXiv HTML version (math from LaTeX alt-text)",
    "web-math": "web page, math recovered from its LaTeX source",
    "web": "web page (no LaTeX math found)",
    "pdf-text": "PDF text layer (math may be garbled - check against the PDF)",
}
SUMMARY_QUERIES = ["main contribution and key idea", "proposed method and how it works",
                   "main results and findings", "limitations and future work"]


def _pdf_article(path_or_url: str) -> Article:
    if re.match(r"https?://", path_or_url):
        import tempfile
        from .heralds.http import get
        data = get(path_or_url).content
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(data)
        local = f.name
    else:
        local = path_or_url
    pages = pdf_src.load(local)
    title = pages[0].title.rsplit(", p. ", 1)[0] if pages else Path(local).stem
    md = "\n\n".join(f"## Page {i}\n\n{p.text.strip()}" for i, p in enumerate(pages, 1))
    return Article(title=title, url=path_or_url, markdown=md, route="pdf-text",
                   notes=["PDF text extraction cannot recover LaTeX; formulas may be garbled"])


def fetch(target: str) -> Article:
    """Pick the most exact extraction route for a URL, arXiv id or PDF path; fall back step by step."""
    errors = []
    if aid := arxiv_latex.parse_arxiv_id(target):
        try:
            return arxiv_latex.fetch(aid)
        except Exception as e:
            errors.append(f"LaTeX source: {e}")
        try:
            meta = arxiv_latex.metadata(aid)
        except Exception:
            meta = {}
        try:
            a = webmath.fetch(f"https://arxiv.org/html/{aid}")
            if len(a.markdown) < 2000:
                raise ValueError("no HTML version of this paper")
            a.route, a.url, a.notes = "arxiv-html", f"https://arxiv.org/abs/{aid}", errors + a.notes
        except Exception as e:
            errors.append(f"arXiv HTML: {e}")
            a = _pdf_article(f"https://arxiv.org/pdf/{aid}")
            a.notes = errors + a.notes
        # the page title of arXiv HTML includes author footnotes ("...Thanks: ..."); trust the metadata
        a.title = meta.get("title") or re.split(r"Thanks:|\s{2,}", a.title)[0].strip()
        a.authors, a.date, a.abstract = meta.get("authors", a.authors), meta.get("date", a.date), meta.get("abstract", "")
        return a
    if target.lower().split("?")[0].endswith(".pdf"):
        return _pdf_article(target)
    return webmath.fetch(target)


def _yaml(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


SITE_SUFFIX = re.compile(r"\s+[-—–|]\s+(Wikipedia|Algorithms for Competitive Programming|scikit-learn.*|Dive into Deep Learning.*)$")


def clean_title(title: str) -> str:
    title = re.split(r"\s+(?:Colab \[|Open the notebook|SageMaker Studio)", title)[0]   # d2l.ai buttons
    title = SITE_SUFFIX.sub("", title.replace("¶", "")).strip()
    return re.sub(r"^\d+(\.\d+)*\.\s+", "", title)      # "1.4. Support Vector Machines" -> "Support Vector Machines"


def source_note(a: Article, md: str, math: dict, tags=()) -> str:
    lines = ["---", f"title: {_yaml(a.title)}", f"url: {_yaml(a.url)}"]
    if a.authors:
        lines.append("authors: [" + ", ".join(_yaml(x) for x in a.authors) + "]")
    if a.date:
        lines.append(f"published: {a.date}")
    lines += [f"added: {datetime.now().isoformat(timespec='seconds')}", f"extraction: {a.route}",
              f"formulas: {math['formulas']}"]
    if math["checked"]:
        lines.append(f"formulas_rendered: {math['rendered']}")
    lines += ["tags: [" + ", ".join(["source", *tags]) + "]", "---", f"# {a.title}", ""]
    info = [f"> [!info] Saved by Michael", f"> Extracted from: {ROUTE_LABEL.get(a.route, a.route)} · [original]({a.url})"]
    if math["formulas"]:
        info.append(f"> Math check: {math['rendered']}/{math['formulas']} formulas render" if math["checked"]
                    else f"> Math check: not run (Node or tools/mathcheck missing) · {math['formulas']} formulas")
    info += [f"> ⚠ {n}" for n in a.notes]
    lines += info + [""]
    if a.authors:
        lines += [f"**Authors:** {', '.join(a.authors)}", ""]
    if a.abstract:
        lines += ["> [!abstract] Abstract", "> " + a.abstract, ""]
    body = re.sub(r"\A#\s[^\n]*\n+", "", md.strip())       # the page's own H1 duplicates our title
    return "\n".join(lines) + "\n" + body + "\n"


def _unique(folder: Path, stem: str, url: str) -> Path:
    """Same article again -> same file (updated). Different article with the same title -> numbered file."""
    path = folder / f"{stem}.md"
    i = 2
    while path.exists() and f"url: {_yaml(url)}" not in path.read_text(encoding="utf8", errors="ignore")[:2000]:
        path = folder / f"{stem} {i}.md"
        i += 1
    return path


def folders(vault_path: str | None, subject: str | None) -> tuple[Path, Path]:
    """(sources folder, key-points folder). With a subject: <vault>/<subject>/Sources and .../Key points."""
    base = Path(vault_path) if vault_path else Path(settings.notes_dir)
    if subject:
        return base / subject / "Sources", base / subject / "Key points"
    return base / settings.sources_folder, base / settings.notes_folder


def save_article(target: str, vault_path=None, subject=None, title=None, tags=(), emit=lambda *a, **k: None,
                 title_suffix: str = ""):
    """Fetch + math check + write the verbatim source note. Returns (Article, path, math stats)."""
    emit("fetch", f"fetching {target}")
    a = fetch(target)
    a.title = title or (clean_title(a.title) + title_suffix)
    md, math = mathcheck.guard(a.markdown)
    emit("extract", f"{a.route}: {len(md):,} characters, {math['formulas']} formulas"
         + (f", {math['failed']} flagged" if math.get("failed") else ""), route=a.route, math=math)
    src_dir, _ = folders(vault_path, subject)
    src_dir.mkdir(parents=True, exist_ok=True)
    src_path = _unique(src_dir, gabriel.slugify(a.title, 80), a.url)
    src_path.write_text(source_note(a, md, math, tags), encoding="utf8")
    emit("saved", f"article saved to {src_path.name}", source_note=str(src_path))
    return a, src_path, math


def verified_note(question: str, queries: list[str], chunks: list, note_path: Path, intro: str,
                  emit=lambda *a, **k: None, run_id=None, keep: int | None = None) -> dict:
    """Write -> verify -> repair over the given chunks and save an Obsidian note. Returns the note, its stats and
    the verified facts [(sentence, link to the supporting quote)] for flashcards."""
    evidence = select_evidence(question, queries, chunks, emit, keep)
    claims = metatron.write(question, evidence)
    emit("write", f"{len(claims)} sentences drafted")
    drafted = len(claims)
    claims, verdicts, removed = verify_and_repair(question, claims, evidence, emit)
    stats = {"total": len(claims), "drafted": drafted, "removed": len(removed),
             "supported": sum(1 for c in claims if c.status == "SUPPORTED"),
             "partial": sum(1 for c in claims if c.status == "PARTIAL"),
             "unsupported": sum(1 for c in claims if c.status == "UNSUPPORTED")}
    note_md = gabriel.render(question, claims, verdicts, evidence, removed, settings.llm_model, stats)
    note_md = note_md.replace(f"# {question}\n", f"# {question}\n\n{intro}\n", 1)
    note_md, _ = mathcheck.guard(note_md)
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(note_md, encoding="utf8")
    if run_id:
        db.save_results(run_id, evidence, claims + removed, list(verdicts.values()))
    by_id = {c.id: c for c in evidence}
    facts = [(c.sentence, by_id[verdicts[c.index].chunk_id].link) for c in claims
             if c.status == "SUPPORTED" and c.index in verdicts and verdicts[c.index].chunk_id in by_id]
    return {"note": note_path, "markdown": note_md, "stats": stats, "facts": facts}


def key_points(src_path: Path, title: str, notes_dir: Path, emit=lambda *a, **k: None, run_id=None) -> dict:
    """Verified key-points note for a saved source note: every point cites a quote from it ([[Title#Section]])."""
    question = f"What are the key points of “{title}”?"
    chunks = file_chunks(src_path)
    emit("gather", f"{len(chunks)} sections from the article")
    return verified_note(question, [question] + SUMMARY_QUERIES, chunks, notes_dir / f"{src_path.stem} - key points.md",
                         f"Key points of [[{src_path.stem}]].", emit, run_id)


def topic_note(subject: str, topic: str, sources: list[Path], note_path: Path, emit=lambda *a, **k: None) -> dict:
    """One verified overview per topic, drawing on every saved article of that topic."""
    question = f"Explain {topic} ({subject}): the key definitions, results and algorithms."
    chunks = [c for p in sources for c in file_chunks(p)]
    emit("gather", f"{len(chunks)} sections from {len(sources)} articles")
    links = ", ".join(f"[[{p.stem}]]" for p in sources)
    return verified_note(question, [question, topic, f"{topic} definition", f"{topic} theorem algorithm example"],
                         chunks, note_path, f"Overview of **{topic}** from: {links}.", emit, keep=8)


def add_article(target: str, summary: bool = True, vault_path: str | None = None, on_event=None,
                run_id: str | None = None, subject: str | None = None, title: str | None = None, tags=()) -> dict:
    run_id = run_id or uuid.uuid4().hex[:12]
    t0 = time.time()
    timings = {}

    def emit(stage, detail="", **data):
        timings[stage] = round(time.time() - t0, 2)
        if on_event:
            on_event({"run_id": run_id, "stage": stage, "detail": detail, "t": timings[stage], **data})

    db.init()
    db.create_run(run_id, f"Add article: {target}", settings.llm_model)
    try:
        if summary and not llm.available():
            raise llm.LLMUnavailable(f"Ollama model {settings.llm_model} is not available. "
                                     f"Run `ollama pull {settings.llm_model}` and make sure Ollama is running.")
        a, src_path, math = save_article(target, vault_path, subject, title, tags, emit)
        stats = {"route": a.route, "math": math, "source_note": str(src_path), "title": a.title,
                 "total": 0, "supported": 0, "partial": 0, "unsupported": 0, "removed": 0}
        note_md, note_path = None, None
        if summary:
            kp = key_points(src_path, a.title, folders(vault_path, subject)[1], emit, run_id)
            note_md, note_path = kp["markdown"], kp["note"]
            stats.update(kp["stats"])
        stats.update({"seconds": round(time.time() - t0, 1), "timings": timings})
        db.finish_run(run_id, "done", str(note_path or src_path), note_md or "", stats)
        detail = (f"{stats['supported']}/{stats['total']} key points verified" if summary else "article saved")
        emit("done", detail, stats=stats, note=str(note_path) if note_path else None, source_note=str(src_path))
        return {"run_id": run_id, "source_note": str(src_path), "note": str(note_path) if note_path else None,
                "markdown": note_md, "stats": stats}
    except Exception as e:
        db.finish_run(run_id, "error", error=str(e))
        emit("error", str(e))
        raise
