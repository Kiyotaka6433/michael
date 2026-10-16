"""Source retrievers. Each `search(query, n)` returns a list of Source objects."""
import logging
from concurrent.futures import ThreadPoolExecutor

from ... import db
from ...config import settings
from . import arxiv_src, cpalgorithms, oeis, openalex, semantic_scholar, stackexchange, wikipedia

log = logging.getLogger(__name__)

SEARCHERS = {"wikipedia": wikipedia.search, "arxiv": arxiv_src.search, "openalex": openalex.search,
             "stackexchange": stackexchange.search, "semanticscholar": semantic_scholar.search,
             "cpalgorithms": cpalgorithms.search, "oeis": oeis.search}


def _search(q: str, kind: str, n: int) -> list:
    key = f"{kind}|{n}|{q.lower().strip()}"
    found = db.cached_search(key, settings.source_cache_days)
    if found is None:
        try:
            found = SEARCHERS[kind](q, n)
            db.store_search(key, found)
        except Exception as e:  # one failing source must not stop the run
            log.warning("%s search failed for %r: %s", kind, q, e)
            found = []
    return found


def gather(queries: list[str], kinds=None, n=None) -> list:
    """Run every query against every enabled source in parallel (with a 7-day cache); de-duplicate by source id.
    Per-host rate limits (arXiv: one request per 3 s) still apply inside the HTTP helper."""
    kinds = kinds or settings.sources
    n = n or settings.results_per_source
    jobs = [(q, kind) for q in queries for kind in kinds]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda job: _search(job[0], job[1], n), jobs))
    seen, out = set(), []
    for found in results:
        for s in found:
            if s.id not in seen and s.text.strip():
                seen.add(s.id)
                out.append(s)
    return out
