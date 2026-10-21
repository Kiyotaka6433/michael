"""The full research run: plan -> gather -> index -> search -> rerank -> write -> verify -> repair -> export."""
import time
import uuid
from pathlib import Path

from .. import db, llm
from ..config import settings
from ..models import Chunk, Claim
from . import chamuel, gabriel, heralds, metatron, raphael
from .scrolls import chunk_source
from .jophiel import Embedder, hybrid_search
from .zadkiel import Reranker
from .heralds import pdf as pdf_src
from .heralds import web as web_src
from .heralds.vault import vault_chunks
from .raguel import NLI, make_verifier, verify_claim, verify_claims

# heavy models are loaded once per process and shared between runs
EMBEDDER, RERANKER, VERIFIER = Embedder(), Reranker(), make_verifier()   # MICHAEL_CASCADE_CUT > 0: two-stage


def warm_up():
    """Load every model before the first request (the API calls this at start-up, in the background)."""
    EMBEDDER.query("warm up")
    try:                                     # topic vectors for the browser extension: first suggestion is instant
        from .raziel import topic_centroids
        topic_centroids()
    except Exception:
        pass
    RERANKER.model
    VERIFIER.scores([("warm up", "warm up")])
    llm.warm_up()


def _noop(stage, detail="", **data):
    pass


def vault_evidence(vault_path: str, queries: list[str], per_query: int = 15) -> list[Chunk]:
    """The vault's best passages for these queries, from the vault index (milliseconds, instead of re-reading and
    re-scoring every note). Michael's own notes are never evidence. Falls back to a full scan if indexing fails."""
    from .. import vault_index
    try:
        vault_index.index_vault(vault_path)
        seen, out = set(), []
        for q in queries:
            for r in vault_index.search(q, k=per_query, include_generated=False, kinds=("source", "note")):
                if r["id"] not in seen:
                    seen.add(r["id"])
                    out.append(r)
        return vault_index.as_chunks(out)
    except Exception:
        return vault_chunks(vault_path)


def collect_candidates(question, queries, kinds=None, urls=(), pdfs=(), use_vault=True, emit=_noop,
                       vault_path=None) -> list[Chunk]:
    sources = heralds.gather(queries, kinds)
    for u in urls:
        try:
            if s := web_src.fetch(u):
                sources.append(s)
        except Exception as e:
            emit("warn", f"could not fetch {u}: {e}")
    for p in pdfs:
        sources += pdf_src.load(p)
    chunks = [c for s in sources for c in chunk_source(s, settings.chunk_chars)]
    vault_path = vault_path or settings.vault_path
    if use_vault and vault_path:
        vc = vault_evidence(vault_path, [question] + list(queries))
        emit("vault", f"{len(vc)} sections from your vault")
        chunks += vc
    emit("gather", f"{len(sources)} sources, {len(chunks)} passages",
         sources=[{"kind": s.kind, "title": s.title, "url": s.url} for s in sources])
    return chunks


def select_evidence(question, queries, chunks, emit=_noop, keep: int | None = None) -> list[Chunk]:
    candidates = hybrid_search(queries, chunks, EMBEDDER, settings.candidates)
    emit("search", f"hybrid search kept {len(candidates)} candidates")
    evidence = RERANKER.rerank(question, candidates, keep or settings.keep)
    for i, c in enumerate(evidence, 1):
        c.label = f"p{i}"
    emit("rerank", f"reranker kept the best {len(evidence)}",
         evidence=[{"label": c.label, "title": c.title, "score": round(c.score, 3)} for c in evidence])
    return evidence


def _drop_duplicates(claims, verdicts):
    """Two supported sentences proven by overlapping quotes of the same passage that say nearly the same thing:
    keep the first. (Small models restate a fact in different words.)"""
    from rapidfuzz import fuzz
    kept = []
    for c in claims:
        v = verdicts.get(c.index)
        dup = v and v.label == "SUPPORTED" and any(
            (w := verdicts.get(k.index)) and w.chunk_id == v.chunk_id
            and w.quote_start < v.quote_end and v.quote_start < w.quote_end
            and fuzz.token_set_ratio(c.sentence, k.sentence) >= 80 for k in kept)
        if dup:
            verdicts.pop(c.index, None)
        else:
            kept.append(c)
    return kept


def _rescue(failed, pool, evidence, by_label, verdicts, per_claim: int | None = None) -> list:
    """Claim-driven retrieval: a sentence that fails against the writer's passages may still be proven elsewhere
    in the collected material. Search the whole pool with the sentence itself as the query, check the best few
    passages, and keep the sentence (citing the new passage) if one proves it. Returns the claims still failing."""
    if not pool or not failed:
        return failed
    per_claim = per_claim or settings.rescue_k
    known = {c.id for c in evidence}
    rest = [c for c in pool if c.id not in known]
    if not rest:
        return failed
    still = []
    for claim in failed:
        found = hybrid_search([claim.sentence], rest, EMBEDDER, per_claim)
        extra = {}
        for c in found:
            if c.id not in known:
                c.label = f"p{len(evidence) + 1}"
                evidence.append(c)
                by_label[c.label] = c
                known.add(c.id)
            extra[c.label] = c
        if not extra:
            still.append(claim)
            continue
        trial = Claim(index=claim.index, sentence=claim.sentence, citations=list(extra), rounds=claim.rounds)
        v = verify_claims([trial], extra, VERIFIER, recite=False)[0]
        if v.label == "SUPPORTED":
            claim.citations, claim.status = trial.citations, "SUPPORTED"
            verdicts[claim.index] = v
        else:
            still.append(claim)
    return still


def verify_and_repair(question, claims, evidence, emit=_noop, repair_enabled=True, pool=None):
    """Each round: verify all pending sentences in one NLI batch, look for proof of the failures in the whole
    collected pool (claim-driven retrieval), then repair what is left in one LLM call."""
    by_label = {c.label: c for c in evidence}
    by_id = {c.id: c for c in evidence}
    verdicts, removed = {}, []
    pending = list(claims)
    for rnd in range(settings.max_repair_rounds + 1):
        failed = []
        for claim, v in zip(pending, verify_claims(pending, by_label, VERIFIER)):
            verdicts[claim.index] = v
            claim.status = v.label
            if v.label == "UNSUPPORTED":
                failed.append(claim)
        before = len(failed)
        failed = _rescue(failed, pool, evidence, by_label, verdicts)
        by_id = {c.id: c for c in evidence}
        rescued = f", {before - len(failed)} proven by other passages" if before - len(failed) else ""
        emit("verify", f"round {rnd}: {len(pending) - len(failed)}/{len(pending)} checked sentences passed{rescued}")
        if not failed or not repair_enabled or rnd == settings.max_repair_rounds:
            break
        related = {c.index: set(c.citations) | ({by_id[verdicts[c.index].chunk_id].label}
                                                if verdicts[c.index].chunk_id in by_id else set()) for c in failed}
        fixes = raphael.repair_many(failed, evidence, related)
        pending = []
        for claim in failed:
            fixed = fixes.get(claim.index)
            if fixed is None:
                claim.status = "REMOVED"
                removed.append(claim)
                verdicts.pop(claim.index, None)
            else:
                claims[claims.index(claim)] = fixed
                pending.append(fixed)
        emit("repair", f"rewrote {len(pending)}, dropped {len(failed) - len(pending)}")
    # anything still unsupported after the last round is removed from the note but kept in the report
    for claim in [c for c in claims if verdicts.get(c.index) and verdicts[c.index].label == "UNSUPPORTED"]:
        claim.status = "REMOVED"
        removed.append(claim)
    kept = _drop_duplicates([c for c in claims if c.status != "REMOVED"], verdicts)
    return kept, verdicts, removed


def run_research(question: str, kinds=None, urls=(), pdfs=(), use_vault=True, repair_enabled=True,
                 on_event=None, run_id: str | None = None, vault_path: str | None = None) -> dict:
    run_id = run_id or uuid.uuid4().hex[:12]
    t0 = time.time()
    timings = {}

    def emit(stage, detail="", **data):
        timings[stage] = round(time.time() - t0, 2)
        if on_event:
            on_event({"run_id": run_id, "stage": stage, "detail": detail, "t": timings[stage], **data})

    db.init()
    db.create_run(run_id, question, settings.llm_model)
    try:
        if not llm.available():
            raise llm.LLMUnavailable(f"Ollama model {settings.llm_model} is not available. "
                                     f"Run `ollama pull {settings.llm_model}` and make sure Ollama is running.")
        queries = chamuel.plan(question)
        emit("plan", f"{len(queries)} queries", queries=queries)
        chunks = collect_candidates(question, queries, kinds, urls, pdfs, use_vault, emit, vault_path)
        if not chunks:
            raise RuntimeError("No sources found for this question.")
        evidence = select_evidence(question, queries, chunks, emit)
        claims = metatron.write(question, evidence)
        emit("write", f"{len(claims)} sentences drafted")
        drafted = len(claims)
        claims, verdicts, removed = verify_and_repair(question, claims, evidence, emit, repair_enabled, pool=chunks)
        stats = {
            "total": len(claims),
            "drafted": drafted,
            "supported": sum(1 for c in claims if c.status == "SUPPORTED"),
            "partial": sum(1 for c in claims if c.status == "PARTIAL"),
            "unsupported": sum(1 for c in claims if c.status == "UNSUPPORTED"),
            "removed": len(removed),
            "sources": len({c.source_id for c in evidence}),
            "seconds": round(time.time() - t0, 1),
            "timings": timings,
        }
        md = gabriel.render(question, claims, verdicts, evidence, removed, settings.llm_model, stats)
        note = Path(settings.notes_dir) / f"{gabriel.slugify(question)}.md"
        note.write_text(md, encoding="utf8")
        db.save_results(run_id, evidence, claims + removed, list(verdicts.values()))
        db.finish_run(run_id, "done", str(note), md, stats)
        emit("done", f"{stats['supported']}/{stats['total']} sentences verified", stats=stats, note=str(note))
        return {"run_id": run_id, "markdown": md, "note": str(note), "stats": stats}
    except Exception as e:
        db.finish_run(run_id, "error", error=str(e))
        emit("error", str(e))
        raise


LIBRARY_BAR = 0.90   # checking arbitrary text against the library: a 0.73 "unlike Dijkstra" and a 0.88 worked example were accepted at 0.70


def check_text(text: str, evidence_text: str | None = None, k: int = 6, subject: str | None = None) -> dict:
    """Fact-check any text (e.g. another AI's answer) sentence by sentence, with the same verifier as Michael's notes.

    With evidence_text: every sentence is judged against that text. Without: against the library - each sentence
    searches the vault's SOURCE notes (never Michael's own generated notes, so it can't cite itself) for its k best
    passages, and the passages of all sentences are verified in one batch (any of them may prove any sentence).
    Returns {"sentences": [{sentence, verdict, entailment, quote, source, url, how}], "summary": {...}}."""
    from .scrolls import split_sentences
    sentences = [s.strip() for s in split_sentences(text) if len(s.split()) >= 4][:40]
    evidence, cites = {}, []
    if evidence_text:
        evidence["p1"] = Chunk(source_id="given", kind="manual", title="given evidence", url="", text=evidence_text,
                               start=0, end=len(evidence_text), label="p1")
        cites = [["p1"]] * len(sentences)
    else:
        from .. import vault_index
        by_id = {}
        for s in sentences:
            own = []
            for r in vault_index.search(s, k=k, subject=subject, include_generated=False, kinds=("source",)):
                if r["id"] not in by_id:
                    label = f"p{len(by_id) + 1}"
                    by_id[r["id"]] = label
                    evidence[label] = Chunk(source_id=r["path"], kind="vault", title=r["title"], url=r["path"],
                                            text=r["text"], start=r["start"], end=r["end_"], heading=r["heading"] or "",
                                            label=label)
                own.append(by_id[r["id"]])
            cites.append(own)
    claims = [Claim(index=i, sentence=s, citations=c) for i, (s, c) in enumerate(zip(sentences, cites))]
    verdicts = verify_claims(claims, evidence, VERIFIER, recite=not evidence_text) if claims else []
    out = []
    for s, c, v in zip(sentences, claims, verdicts):
        chunk = evidence.get(v.evidence_label)
        if not evidence_text and v.label == "SUPPORTED" and v.entailment < LIBRARY_BAR:
            # library mode: the passages were found by search, not chosen for the sentence, so a worked example or an
            # indirect remark ("unlike Dijkstra, ...") can score 0.7-0.9 for a general claim: report it as partial
            v.label = "PARTIAL"
        how = [h for h, on in (("formulas checked", v.math in ("match", "proven")), ("with source title as context", v.titled),
                               ("proven in parts", bool(v.parts)), ("in the context of its paragraph", v.in_context)) if on]
        out.append({"sentence": s, "verdict": v.label, "entailment": round(v.entailment, 3),
                    "quote": " ".join(v.quote.split()), "source": chunk.link if chunk else "",
                    "url": _source_url(chunk) if chunk else "", "how": how})
    count = lambda lab: sum(o["verdict"] == lab for o in out)
    return {"sentences": out, "summary": {"sentences": len(out), "supported": count("SUPPORTED"),
                                          "partial": count("PARTIAL"), "unsupported": count("UNSUPPORTED")}}


def _source_url(chunk: Chunk) -> str:
    """The original web address of a vault source note (from its frontmatter), else its vault path."""
    if chunk.kind != "vault":
        return chunk.url
    try:
        head = Path(chunk.url).read_text(encoding="utf8", errors="ignore")[:800]
        import re
        m = re.search(r'(?m)^url: "?([^"\n]+)"?$', head)
        return m.group(1) if m else chunk.url
    except OSError:
        return chunk.url


def verify_text(sentence: str, evidence_text: str) -> dict:
    """Stand-alone check: does this evidence text support this sentence?"""
    chunk = Chunk(source_id="manual", kind="manual", title="pasted text", url="", text=evidence_text,
                  start=0, end=len(evidence_text), label="p1")
    v = verify_claim(Claim(index=0, sentence=sentence, citations=["p1"]), {"p1": chunk}, VERIFIER)
    return v.to_dict()
